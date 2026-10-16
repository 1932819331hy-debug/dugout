"use client";

import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { predStat, resultStat, type Row } from "@/lib/scoreboard";
import { CardBody } from "./Num";

export const CARD_ID = "sb-card";
const CARD_W = 288; // w-72

/** One provenance card for the whole scoreboard table, filled for the number under the pointer, focus or tap.
 *  The table has ~500 numbers; a card per number (as <Num> renders) made the page ~5,000 elements.
 *  Buttons carry `data-sb="<row>:<cell>"` (cells 0-2: probabilities, 3: result). */
export default function ScoreCard({ rows, generated }: { rows: Row[]; generated: string }) {
  const [at, setAt] = useState<{ key: string; x: number; y: number } | null>(null);
  const pinned = useRef(false);
  const openKey = useRef<string | null>(null);
  const card = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const btn = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLElement>("button[data-sb]") : null);
    const inCard = (t: EventTarget | null) => t instanceof Node && !!card.current?.contains(t);
    const show = (b: HTMLElement) => {
      // anchored to a wrapper outside the table's scroll container, so the card is never clipped
      const box = b.closest<HTMLElement>("[data-sb-root]");
      if (!box) return;
      const r = b.getBoundingClientRect();
      const o = box.getBoundingClientRect();
      openKey.current = b.dataset.sb!;
      // set before a screen reader reads the description on focus
      // right edge under the number's right edge, kept inside the wrapper (CARD_W wide)
      const x = Math.max(0, Math.min(r.right - o.left - CARD_W, o.width - CARD_W));
      flushSync(() => setAt({ key: b.dataset.sb!, x, y: r.bottom - o.top }));
    };
    const hide = () => {
      pinned.current = false;
      openKey.current = null;
      flushSync(() => setAt(null));
    };
    const over = (e: PointerEvent) => {
      const b = btn(e.target);
      if (b && !pinned.current) show(b);
    };
    const out = (e: PointerEvent) => {
      if (pinned.current || (!btn(e.target) && !inCard(e.target))) return;
      if (!btn(e.relatedTarget) && !inCard(e.relatedTarget)) hide();
    };
    const focusIn = (e: FocusEvent) => {
      const b = btn(e.target);
      if (b) show(b);
    };
    const focusOut = (e: FocusEvent) => {
      if (btn(e.target) && !inCard(e.relatedTarget) && !btn(e.relatedTarget)) hide();
    };
    const click = (e: MouseEvent) => {
      const b = btn(e.target);
      if (b) {
        if (pinned.current && openKey.current === b.dataset.sb) return hide();
        show(b);
        pinned.current = true;
      } else if (!inCard(e.target)) hide();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && hide();
    document.addEventListener("pointerover", over);
    document.addEventListener("pointerout", out);
    document.addEventListener("focusin", focusIn);
    document.addEventListener("focusout", focusOut);
    document.addEventListener("click", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("pointerout", out);
      document.removeEventListener("focusin", focusIn);
      document.removeEventListener("focusout", focusOut);
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", key);
    };
  }, []);

  const [row, cell] = (at?.key ?? "").split(":").map(Number);
  const r = at ? rows[row] : undefined;
  const stat = r ? (cell === 3 ? resultStat(r) : predStat(r, cell, generated)) : undefined;
  return (
    <span
      ref={card}
      id={CARD_ID}
      role="tooltip"
      data-meta
      className={`absolute z-40 mt-2 w-72 border-l-4 border-red bg-chalk p-3 text-left font-mono text-xs leading-relaxed text-ink ${stat ? "block" : "hidden"}`}
      style={{ left: at?.x ?? 0, top: at?.y ?? 0, boxShadow: "6px 6px 0 rgba(20,20,20,0.85)" }}
    >
      {stat && <CardBody stat={stat} />}
    </span>
  );
}
