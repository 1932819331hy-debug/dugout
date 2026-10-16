"""Fail if the built website shows a digit that is not a ledger-backed number.

Walks every page in apps/web/out. Text inside an element marked `data-num` (a <Num>: a ledger stat with its
provenance card) or `data-meta` (provenance and audit metadata: timestamps, dates, report counts) or `data-name` (a proper name with
digits in it, e.g. "Parma Calcio 1913", which the Stat Auditor also allows) is allowed;
any other visible digit is reported. Scripts and styles are skipped. Standard library only.

    uv run python tools/check_site_numbers.py
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "apps" / "web" / "out"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "svg", "template", "title"}


class Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, bool]] = []  # (tag, allowed subtree)
        self.hits: list[str] = []

    def allowed(self) -> bool:
        return any(a for _, a in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        names = {k for k, _ in attrs}
        self.stack.append(
            (
                tag,
                tag in SKIP
                or "data-num" in names
                or "data-meta" in names
                or "data-name" in names
                or "aria-hidden" in names,
            )
        )

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.allowed() and re.search(r"\d", data):
            self.hits.append(data.strip()[:80])


def main() -> int:
    pages = sorted(OUT.rglob("*.html"))
    if not pages:
        print("no built site; run `npm --prefix apps/web run build` first", file=sys.stderr)
        return 2
    bad = 0
    for page in pages:
        s = Scan()
        s.feed(page.read_text(encoding="utf-8"))
        for h in s.hits:
            bad += 1
            print(f"{page.relative_to(OUT)}: {h!r}")
    print(f"{len(pages)} pages, {bad} untraceable digit(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
