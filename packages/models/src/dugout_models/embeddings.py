"""FootballBERT player embeddings (achadj/footballbert-base, Apache-2.0; RisingBALLER, arXiv:2410.00943).

Loaded *safely*: only `model.safetensors` (tensor format, no code) and JSON vocabularies are read, and the
id->name map (a pickle) is loaded with an unpickler that refuses every class lookup, so it can only yield
built-in dicts and strings. The repository's custom Python code (`trust_remote_code`) is never executed.

The masked-player-prediction head's weights are tied to the input token embeddings, so `decoder.weight`
gives one static 256-d vector per player. FootballBERT has its own player ids; we map them to ours by exact,
accent-normalised full name and keep only names that are unique on both sides.
"""

from __future__ import annotations

import io
import json
import pickle
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from dugout_pipeline.settings import get_settings

MODEL_DIR = get_settings().cache_dir / "models" / "footballbert"
REPO = "https://huggingface.co/achadj/footballbert-base/resolve/main/"
FILES = {
    "model.safetensors": "model.safetensors",
    "player_vocab.json": "player_vocab.json",
    "names.pkl": "baller_id2player_names_99316p.pkl",
}


class _NoClasses(pickle.Unpickler):
    def find_class(self, module, name):  # any class/function reference => refuse
        raise pickle.UnpicklingError(f"refusing to load {module}.{name}")


def safe_load_names(path: Path) -> dict[str, str]:
    obj = _NoClasses(io.BytesIO(path.read_bytes())).load()
    if not isinstance(obj, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in obj.items()
    ):
        raise ValueError("unexpected content in FootballBERT name map")
    return obj


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace(".", " ").replace("'", "").split())


def download(model_dir: Path = MODEL_DIR) -> None:
    import httpx

    model_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        follow_redirects=True, timeout=600, headers={"User-Agent": get_settings().user_agent}
    ) as c:
        for local, remote in FILES.items():
            if not (model_dir / local).exists():
                (model_dir / local).write_bytes(c.get(REPO + remote).raise_for_status().content)


def load_embeddings(model_dir: Path = MODEL_DIR) -> tuple[np.ndarray, pd.DataFrame]:
    """Returns (matrix [n_players x 256], frame with ba_id, row, name, key)."""
    from safetensors.numpy import load_file

    w = load_file(str(model_dir / "model.safetensors"))["decoder.weight"]
    vocab = json.loads((model_dir / "player_vocab.json").read_text())
    names = safe_load_names(model_dir / "names.pkl")
    df = pd.DataFrame({"ba_id": list(vocab), "row": list(vocab.values())})
    df["name"] = df.ba_id.map(names)
    df = df.dropna(subset=["name"])
    df["key"] = df.name.map(norm_name)
    return w, df


def match_players(players: pd.DataFrame, emb_index: pd.DataFrame) -> pd.DataFrame:
    """players: player_id + one or more candidate name columns (`names`: list[str]). Unique exact matches only."""
    counts = emb_index.key.value_counts()
    unique = emb_index[emb_index.key.map(counts) == 1].set_index("key")
    rows = []
    for p in players.itertuples():
        hits = {k for k in {norm_name(n) for n in p.names if isinstance(n, str) and n} if k in unique.index}
        if len(hits) == 1:
            k = hits.pop()
            rows.append(
                {"player_id": p.player_id, "ba_id": unique.at[k, "ba_id"], "row": int(unique.at[k, "row"])}
            )
    out = pd.DataFrame(rows)
    # two of our players must not share one embedding
    return out[~out.ba_id.duplicated(keep=False)] if len(out) else out


def player_vectors(con, model_dir: Path = MODEL_DIR) -> pd.DataFrame:
    """Embeddings for every player in our warehouse we can match. Index: player_id."""
    w, idx = load_embeddings(model_dir)
    ours = con.execute("SELECT player_id, name, web_name FROM players").df()
    tm = _transfermarkt_names(con)
    ours = ours.merge(tm, on="player_id", how="left")
    ours["names"] = ours[["name", "web_name", "tm_name"]].values.tolist()
    m = match_players(ours, idx)
    vec = w[m.row.to_numpy()]
    return pd.DataFrame(vec, index=m.player_id.to_numpy())


def _transfermarkt_names(con) -> pd.DataFrame:
    from dugout_pipeline.ids import attach_catalogue

    from dugout_models.valuation import TM_DIR

    if not attach_catalogue(con) or not (TM_DIR / "players.parquet").exists():
        return pd.DataFrame(columns=["player_id", "tm_name"])
    tm = pd.read_parquet(TM_DIR / "players.parquet", columns=["player_id", "name"])
    tm["player_id"] = tm.player_id.astype(str)
    bridge = con.execute("""SELECT reep_id, external_id FROM reep.bridges
                            WHERE provider='transfermarkt' AND namespace='spieler'""").df()
    return (
        bridge.merge(tm, left_on="external_id", right_on="player_id")[["reep_id", "name"]]
        .rename(columns={"reep_id": "player_id", "name": "tm_name"})
        .drop_duplicates("player_id")
    )
