"use client";

import { useEffect, useRef } from "react";

/** A small chalk crosshair that leaves a fading trail over the pitch (decorative; the real cursor is hidden here). */
export default function ChalkCursor() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const trail: { x: number; y: number; t: number }[] = [];
    let pos = { x: -100, y: -100 };
    let raf = 0;
    const resize = () => {
      const r = c.getBoundingClientRect();
      c.width = r.width * devicePixelRatio;
      c.height = r.height * devicePixelRatio;
    };
    const move = (e: PointerEvent) => {
      const r = c.getBoundingClientRect();
      pos = { x: e.clientX - r.left, y: e.clientY - r.top };
      trail.push({ ...pos, t: performance.now() });
    };
    const draw = (now: number) => {
      const d = devicePixelRatio;
      ctx.clearRect(0, 0, c.width, c.height);
      while (trail.length && now - trail[0].t > 900) trail.shift();
      ctx.lineCap = "round";
      for (let i = 1; i < trail.length; i++) {
        const a = 1 - (now - trail[i].t) / 900;
        ctx.strokeStyle = `rgba(246,243,234,${a * 0.55})`;
        ctx.lineWidth = 2.2 * d * a;
        ctx.beginPath();
        ctx.moveTo(trail[i - 1].x * d, trail[i - 1].y * d);
        ctx.lineTo(trail[i].x * d, trail[i].y * d);
        ctx.stroke();
      }
      ctx.strokeStyle = "rgba(246,243,234,0.95)";
      ctx.lineWidth = 1.5 * d;
      const { x, y } = pos;
      ctx.beginPath();
      ctx.moveTo((x - 9) * d, y * d);
      ctx.lineTo((x - 3) * d, y * d);
      ctx.moveTo((x + 3) * d, y * d);
      ctx.lineTo((x + 9) * d, y * d);
      ctx.moveTo(x * d, (y - 9) * d);
      ctx.lineTo(x * d, (y - 3) * d);
      ctx.moveTo(x * d, (y + 3) * d);
      ctx.lineTo(x * d, (y + 9) * d);
      ctx.stroke();
      raf = requestAnimationFrame(draw);
    };
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", move);
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", move);
    };
  }, []);
  return <canvas ref={canvas} aria-hidden="true" className="pointer-events-none absolute inset-0 z-10 h-full w-full" />;
}
