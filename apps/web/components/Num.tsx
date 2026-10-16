"use client";

import { useId, useState } from "react";
import type { Stat } from "@/lib/data";
import { sourceName, when } from "@/lib/format";

const STATUS: Record<string, string> = {
  verified: "Verified",
  single_source: "Single source, re-checked",
  model_output: "dugout model output, re-checked",
  disputed: "Sources disagree",
};

/** A number on the site: shows its value; hover or focus reveals where it came from and how it was checked. */
export default function Num({ stat, display, className = "" }: { stat: Stat; display: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const verified = stat.status === "verified";
  return (
    <span data-num className="relative inline-block" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-describedby={id}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={`cursor-help ${className.includes("font-") ? "" : "font-mono"} underline decoration-dotted decoration-1 underline-offset-4 ${
          verified ? "decoration-ink" : "decoration-pencil"
        } ${className}`}
      >
        {display}
      </button>
      <span
        id={id}
        role="tooltip"
        className={`absolute left-0 top-full z-40 mt-2 w-72 border-l-4 border-red bg-chalk p-3 text-left font-mono text-xs leading-relaxed text-ink ${
          open ? "block" : "hidden"
        }`}
        style={{ boxShadow: "6px 6px 0 rgba(20,20,20,0.85)" }}
      >
        <span className="block text-[0.65rem] uppercase tracking-widest text-pencil">
          {stat.metric.replaceAll("_", " ")} · {stat.entity_name}
        </span>
        <span className="mt-1 block">
          Source:{" "}
          {stat.source_url ? (
            <a className="underline" href={stat.source_url} target="_blank" rel="noopener noreferrer">
              {sourceName(stat.source)}
            </a>
          ) : (
            sourceName(stat.source)
          )}{" "}
          (tier {stat.source_tier})
        </span>
        <span className="block">Fetched: {when(stat.fetched_at)}</span>
        <span className={`block ${verified ? "text-red" : ""}`}>Status: {STATUS[stat.status] ?? stat.status}</span>
        {stat.cross_checks.length > 0 && (
          <span className="block text-pencil">
            Cross-checked with {stat.cross_checks.map((c) => `${c.source} (${c.agrees ? "agrees" : "differs"})`).join(", ")}
          </span>
        )}
      </span>
    </span>
  );
}
