"""Tiny, explicit JSON selector used in ledger queries so the Stat Auditor can re-extract a value.

A path is a list of steps: a str key, an int index, or {"match": {field: value, ...}} selecting the first
list element whose fields equal the given values. Example:
    ["elements", {"match": {"id": 328}}, "goals_scored"]
"""

from __future__ import annotations

from typing import Any


class PathError(LookupError):
    pass


def extract(doc: Any, path: list[Any]) -> Any:
    cur = doc
    for step in path:
        if isinstance(step, dict) and "match" in step:
            if not isinstance(cur, list):
                raise PathError(f"match step on non-list at {step}")
            want = step["match"]
            found = next((x for x in cur if all(_get(x, k) == v for k, v in want.items())), None)
            if found is None:
                raise PathError(f"no element matches {want}")
            cur = found
        elif isinstance(step, int):
            try:
                cur = cur[step]
            except (IndexError, TypeError, KeyError) as exc:
                raise PathError(f"bad index {step}") from exc
        else:
            if not isinstance(cur, dict) or step not in cur:
                raise PathError(f"missing key {step!r}")
            cur = cur[step]
    return cur


def _get(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj
