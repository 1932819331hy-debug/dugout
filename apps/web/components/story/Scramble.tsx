"use client";

import { useContext, useEffect, useRef, useState } from "react";
import Num from "@/components/Num";
import { ActiveChapter } from "./active";
import type { StatRef } from "./types";

const GLYPHS = "0123456789";

/** Scrambled digits that resolve to the verified value once their chapter is on screen; the resolved value is a
 *  hoverable Num. */
export default function Scramble({ s, chapter, className = "" }: { s: StatRef; chapter: number; className?: string }) {
  const on = useContext(ActiveChapter);
  const active = on === -1 || on === chapter;
  const [done, setDone] = useState(false);
  const [text, setText] = useState(() => s.display.replace(/\d/g, "0"));
  const raf = useRef(0);
  useEffect(() => {
    if (!active || done) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setDone(true);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = (now - start) / 900;
      if (t >= 1) {
        setDone(true);
        return;
      }
      const fixed = Math.floor(t * s.display.length);
      setText(
        s.display
          .split("")
          .map((ch, i) => (i < fixed || !/\d/.test(ch) ? ch : GLYPHS[Math.floor(Math.random() * 10)]))
          .join(""),
      );
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [active, done, s.display]);
  if (done) return <Num stat={s.stat} display={s.display} className={className} />;
  return (
    <>
      <span aria-hidden="true" className={`font-mono ${className}`}>
        {text}
      </span>
      <span className="sr-only">
        <Num stat={s.stat} display={s.display} />
      </span>
    </>
  );
}
