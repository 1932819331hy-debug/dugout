import type { Claim, Dossier, Section } from "@/lib/data";
import Num from "./Num";

export function ClaimText({ claim, d }: { claim: Claim; d: Dossier }) {
  return (
    <>
      {claim.segments.map((seg, i) =>
        "stat" in seg ? (
          <Num key={i} stat={d.stats[seg.stat]} display={seg.display} />
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  );
}

/** A published section: verified claims as prose; analysis marked; sources listed for news claims. */
export function SectionProse({ section, d }: { section: Section; d: Dossier }) {
  if (section.status !== "published") {
    return <p className="text-pencil">Nothing in this section passed verification today.</p>;
  }
  return (
    <div className="space-y-3">
      {section.claims.map((c, i) => (
        <p key={i} className={c.status === "analysis" ? "border-l-2 border-pencil pl-3 italic text-ink/80" : ""}>
          {c.status === "analysis" && <span className="mono-label mr-2 not-italic">Analysis</span>}
          <ClaimText claim={c} d={d} />
          {c.sources.length > 0 && (
            <span className="ml-2 font-mono text-xs text-pencil">
              [
              {c.sources.map((s, j) => (
                <span key={j}>
                  {j > 0 && ", "}
                  {s.url ? (
                    <a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.outlet}
                    </a>
                  ) : (
                    s.outlet
                  )}
                  {s.official && " · official"}
                </span>
              ))}
              ]
            </span>
          )}
        </p>
      ))}
      <p className="mono-label pt-1">
        Written by {section.writer.startsWith("llm:") ? <>an open-weight LLM (<span data-meta>{section.writer.slice(4)}</span>)</> : "deterministic templates"};
        every number filled from the evidence ledger.
      </p>
    </div>
  );
}
