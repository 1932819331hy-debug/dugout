"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Num from "@/components/Num";
import { REPO } from "./constants";
import Scramble from "./Scramble";
import type { StatRef, StoryData } from "./types";

function N({ s, className }: { s?: StatRef; className?: string }) {
  return s ? <Num stat={s.stat} display={s.display} className={className} /> : <span className="text-pencil">n/a</span>;
}

/** The six chapters' copy. `active` = chapter index on screen (animated mode) or -1 (static: everything shown). */
export function chapterContent(d: StoryData, active: number) {
  const on = (i: number) => active === -1 || active === i;
  return [
    {
      kicker: "Chapter one · read the club",
      body: (
        <>
          <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.9]">
            <span className="block">{d.club},</span>
            <span className="block italic">read in full.</span>
          </h2>
          <p className="mt-6 max-w-md">
            {d.manager ? `${d.manager}'s side` : "The side"}
            {d.formation && (
              <>
                {" "}line up in a <N s={d.formation} />
              </>
            )}
            {d.position && (
              <>
                {d.formation ? " and" : ""} sit <N s={d.position} /> in the table
              </>
            )}
            .
            {d.threat && (
              <>
                {" "}His teams take <N s={d.threat} /> of the threat in their matches
                {d.defActions ? (
                  <>
                    {" "}and average <N s={d.defActions} /> defensive actions
                  </>
                ) : null}
                .
              </>
            )}
          </p>
        </>
      ),
    },
    {
      kicker: "Chapter two · find the gap",
      body: (
        <>
          <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.9]">
            The gap is at <span className="italic text-red">{d.need ? <N s={d.need} /> : "—"}</span>.
          </h2>
          <p className="mt-6 max-w-md">
            Every position is compared with the six squads closest in strength: depth, the best option&apos;s value, ageing.
            {d.signings.length > 0 && " Signings the club has already announced count before anything is recommended:"}
          </p>
          {d.signings.length > 0 && (
            <ul className="mt-2 max-w-md font-mono text-sm">
              {d.signings.map((s) => (
                <li key={s.title}>
                  {s.url ? (
                    <a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.title}
                    </a>
                  ) : (
                    s.title
                  )}{" "}
                  <span className="text-pencil">· official</span>
                </li>
              ))}
            </ul>
          )}
        </>
      ),
    },
    {
      kicker: "Chapter three · scout the fix",
      body: d.candidate ? (
        <>
          <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.9]">{d.candidate.name}</h2>
          <p className="mono-label mt-2">{d.candidate.club}</p>
          <dl className="mt-6 grid max-w-md grid-cols-2 gap-x-6 gap-y-2 font-mono text-sm">
            <dt className="text-pencil">Age</dt>
            <dd>{d.candidate.age && <Scramble s={d.candidate.age} active={on(2)} />}</dd>
            <dt className="text-pencil">Market value</dt>
            <dd>{d.candidate.value && <Scramble s={d.candidate.value} active={on(2)} />}</dd>
            <dt className="text-pencil">Fair fee (model)</dt>
            <dd>{d.candidate.fairFee && <Scramble s={d.candidate.fairFee} active={on(2)} />}</dd>
            <dt className="text-pencil">Chance of the move</dt>
            <dd>{d.candidate.realism && <Scramble s={d.candidate.realism} active={on(2)} />}</dd>
          </dl>
          {d.candidate.minutes && (
            <p className="stamp mt-6 text-xl">
              Plays <N s={d.candidate.minutes} /> of minutes
            </p>
          )}
        </>
      ) : (
        <p>No shortlist passed verification today.</p>
      ),
    },
    {
      kicker: "Chapter four · check every number",
      body: (
        <>
          <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.9]">
            Every number <span className="italic">has a receipt.</span>
          </h2>
          <ul className="mt-6 max-w-lg space-y-1 font-mono text-sm">
            {d.verifiedSamples.map((s) => (
              <li key={s.id} className="flex justify-between gap-4 border-b border-ink/30 py-1">
                <span className="text-pencil">
                  {s.stat.metric.replaceAll("_", " ")} · {s.stat.entity_name}
                </span>
                <Scramble s={s} active={on(3)} />
              </li>
            ))}
          </ul>
          <p className="mt-5 flex flex-wrap items-center gap-5">
            <span className="stamp text-2xl">Verified ×2</span>
            <span className="mono-label">
              Stat Auditor: every query re-run · Fact-Check: two independent sources or one official · hover any number
            </span>
          </p>
        </>
      ),
    },
    {
      kicker: "Chapter five · predict Saturday",
      body: d.prediction ? (
        <>
          <h2 className="font-display text-[clamp(2.4rem,7vw,6rem)] leading-[0.9]">
            {d.prediction.home} <span className="italic">v</span> {d.prediction.away}
          </h2>
          <p className="mono-label mt-2">
            <N s={d.prediction.kickoff} />
          </p>
          <ChalkLines d={d} />
        </>
      ) : (
        <p>No upcoming fixture.</p>
      ),
    },
    {
      kicker: "Chapter six · fork it",
      body: (
        <>
          <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.9]">
            Open source. Free. <span className="italic text-red">Yours.</span>
          </h2>
          <p className="mt-6 max-w-md">
            MIT-licensed, built only on free data and open-weight models. Clone it, point it at your club, check every number yourself.
          </p>
          <p className="mt-4 flex flex-wrap items-center gap-5 font-mono text-sm">
            <a className="border-b-2 border-red pb-0.5" href={REPO} target="_blank" rel="noopener noreferrer">
              github.com/delta96040/dugout
            </a>
            <Stars />
            <Link className="underline" href={`/club/${d.slug}/`}>
              Read the full dossier
            </Link>
          </p>
        </>
      ),
    },
  ];
}

function ChalkLines({ d }: { d: StoryData }) {
  const p = d.prediction!;
  const rows: [string, StatRef | undefined][] = [
    [`${p.home} win`, p.pHome],
    ["Draw", p.pDraw],
    [`${p.away} win`, p.pAway],
  ];
  return (
    <div className="mt-6 max-w-xl space-y-3">
      {rows.map(([label, s], i) => {
        const v = s ? Number(s.stat.value) : 0;
        return (
          <div key={label}>
            <div className="flex justify-between font-mono text-sm">
              <span>{label}</span>
              <N s={s} />
            </div>
            {/* a chalk stroke whose length is the probability */}
            <svg viewBox="0 0 100 4" preserveAspectRatio="none" className="mt-1 h-2 w-full" aria-hidden="true">
              <path d={`M0 2 Q ${v * 50} ${1 + 0.7 * i}, ${v * 100} 2`} stroke="#141414" strokeWidth="2.2" strokeLinecap="round" fill="none" opacity="0.85" />
            </svg>
          </div>
        );
      })}
      <p className="mono-label">Model: Elo + xG Dixon–Coles stack, beats Elo on both test seasons; bookmakers are still better.</p>
    </div>
  );
}

function Stars() {
  const [stars, setStars] = useState<{ n: number; at: string } | null>(null);
  useEffect(() => {
    fetch("https://api.github.com/repos/delta96040/dugout")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setStars({ n: j.stargazers_count, at: new Date().toISOString() }))
      .catch(() => undefined);
  }, []);
  if (!stars) return null;
  return (
    <span title={`Source: GitHub API (api.github.com), fetched live at ${stars.at}`} className="font-mono">
      ★ {stars.n} <span className="text-pencil">live from GitHub</span>
    </span>
  );
}
