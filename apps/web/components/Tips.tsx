"use client";

import { useEffect } from "react";

/** One page-wide listener for the CSS provenance cards: tap toggles a card, tapping elsewhere or Escape closes it. */
export default function Tips() {
  useEffect(() => {
    const tips = () => document.querySelectorAll<HTMLElement>(".tip[data-open], .tip[data-closed]");
    const onClick = (e: MouseEvent) => {
      const btn = (e.target as Element).closest(".tip > button");
      const tip = btn?.parentElement;
      for (const t of tips()) if (t !== tip) t.removeAttribute("data-open");
      if (tip) tip.toggleAttribute("data-open");
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      for (const t of document.querySelectorAll<HTMLElement>(".tip:hover, .tip:focus-within, .tip[data-open]")) {
        t.removeAttribute("data-open");
        t.setAttribute("data-closed", "");
      }
    };
    // reopenable once the pointer or focus has really left the number (not just moved onto its card)
    const onLeave = (e: MouseEvent | FocusEvent) => {
      const tip = (e.target as Element).closest?.(".tip");
      if (tip && !tip.contains(e.relatedTarget as Node | null)) tip.removeAttribute("data-closed");
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    document.addEventListener("mouseout", onLeave);
    document.addEventListener("focusout", onLeave);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mouseout", onLeave);
      document.removeEventListener("focusout", onLeave);
    };
  }, []);
  return null;
}
