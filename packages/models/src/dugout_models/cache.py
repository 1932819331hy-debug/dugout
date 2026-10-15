"""On-disk cache for training frames built from transfermarkt-datasets.

Frames depend only on the dataset files and on the builder's parameters, so they are keyed by a fingerprint of
both. A new dataset release (or a CACHE_VERSION bump when a builder changes) rebuilds them automatically.
Stored under the git-ignored `.cache/frames/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from dugout_pipeline.settings import get_settings

log = logging.getLogger(__name__)
CACHE_VERSION = 1


def fingerprint(sources: list[Path]) -> str:
    files = [f for s in sources for f in (sorted(s.glob("*.parquet")) if s.is_dir() else [s])]
    parts = [(f.name, f.stat().st_size, int(f.stat().st_mtime)) for f in files if f.exists()]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:12]


def cached_frame(
    name: str, params: dict, sources: list[Path], build: Callable[[], pd.DataFrame]
) -> pd.DataFrame:
    key = hashlib.sha256(
        json.dumps([CACHE_VERSION, name, params, fingerprint(sources)], sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    path = get_settings().cache_dir / "frames" / f"{name}-{key}.parquet"
    if path.exists():
        log.info("frame cache hit: %s", path.name)
        return pd.read_parquet(path)
    df = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df
