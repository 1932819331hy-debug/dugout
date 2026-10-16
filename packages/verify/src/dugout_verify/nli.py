"""Fact-Check models: an NLI cross-encoder (DeBERTa-v3) and a dense retriever (BGE).

Weights are loaded from the Hugging Face Hub at pinned revisions, safetensors only, never with remote code.
Both are behind small protocols so tests can use deterministic fakes (no network, no torch).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class HubModel:
    repo: str
    revision: str  # commit sha: a moved tag can never silently change the weights we run
    licence: str


NLI_MODELS = {
    "base": HubModel(
        "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli", "6f5cf0a2b59cabb106aca4c287eed12e357e90eb", "MIT"
    ),
    "large": HubModel(
        "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli",
        "b3546ea6b0346eb6f8d5d68b13c7dc6d0376b3d7",
        "MIT",
    ),
}
RETRIEVERS = {
    "bge-small": HubModel("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", "MIT"),
}
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class NLI(Protocol):
    def scores(self, premises: list[str], hypothesis: str) -> np.ndarray:
        """(n, 3) probabilities: entailment, neutral, contradiction for each premise."""
        ...


class Embedder(Protocol):
    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        """(n, d) L2-normalised embeddings."""
        ...


class DebertaNLI:
    def __init__(self, size: str = "base", max_length: int = 512, batch: int = 8):
        self.spec, self.max_length, self.batch = NLI_MODELS[size], max_length, batch

    @cached_property
    def _model(self):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(self.spec.repo, revision=self.spec.revision)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.spec.repo, revision=self.spec.revision, use_safetensors=True
        ).eval()
        labels = {v.lower(): int(k) for k, v in model.config.id2label.items()}
        order = [labels["entailment"], labels["neutral"], labels["contradiction"]]
        return tok, model, order

    def scores(self, premises: list[str], hypothesis: str) -> np.ndarray:
        import torch

        tok, model, order = self._model
        out = []
        for i in range(0, len(premises), self.batch):
            enc = tok(
                premises[i : i + self.batch],
                [hypothesis] * len(premises[i : i + self.batch]),
                truncation="only_first",
                max_length=self.max_length,
                padding=True,
                return_tensors="pt",
            )
            with torch.inference_mode():  # per call: grad mode is thread-local (LangGraph uses threads)
                logits = model(**enc).logits
            out.append(torch.softmax(logits, -1)[:, order].numpy())
        return np.vstack(out) if out else np.zeros((0, 3))


class BgeEmbedder:
    def __init__(self, name: str = "bge-small", batch: int = 32):
        self.spec, self.batch = RETRIEVERS[name], batch

    @cached_property
    def _model(self):
        from transformers import AutoModel, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(self.spec.repo, revision=self.spec.revision)
        model = AutoModel.from_pretrained(
            self.spec.repo, revision=self.spec.revision, use_safetensors=True
        ).eval()
        return tok, model

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        import torch

        tok, model = self._model
        if query:
            texts = [BGE_QUERY_PREFIX + t for t in texts]
        out = []
        for i in range(0, len(texts), self.batch):
            enc = tok(
                texts[i : i + self.batch], truncation=True, max_length=512, padding=True, return_tensors="pt"
            )
            with torch.inference_mode():
                cls = model(**enc).last_hidden_state[:, 0].numpy()  # BGE uses the [CLS] vector
            out.append(cls / np.linalg.norm(cls, axis=1, keepdims=True))
        return np.vstack(out) if out else np.zeros((0, 384))
