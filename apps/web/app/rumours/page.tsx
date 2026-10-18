import Link from "next/link";
import Num from "@/components/Num";
import { allDossiers, readData } from "@/lib/data";
import { int, pct, recordStat, type RumourRecord, RUMOURS_DOC } from "@/lib/rumours";
import { storyData } from "@/lib/story";

export const metadata = {
  title: "Rumour track record — dugout",
  description: "How often transfer rumours come true: every Guardian Rumour Mill column checked against the moves that happened.",
};

const SHOWN_RECENT = 12;

export default function RumoursPage() {
  const r = readData<RumourRecord>("rumours.json");
  // the rumours on the club pages: confirmed against the column by Fact-Check, each with its track record
  const recent = allDossiers()
    .flatMap((d) => {
      const s = storyData(d);
      return s.rumours.filter((x) => x.record).map((x) => ({ ...x, club: s.club, slug: s.slug }));
    })
    // likeliest first: "one time in N" with the smallest N
    .sort((a, b) => Number(a.record!.stat.value) - Number(b.record!.stat.value))
    .slice(0, SHOWN_RECENT);
  if (!r) {
    return (
      <section className="grid12 pt-10">
        <p className="hang">The rumour track record is written by the nightly pipeline (`dugout-models publish rumours`).</p>
      </section>
    );
  }
  const at = r.generated_at;
  const S = (value: number, display: string, metric: string, subject: string) => (
    <Num stat={recordStat(value, display, metric, subject, at)} display={display} />
  );
  const b = r.backtest;
  const B = (value: number | null, display: (v: number) => string, metric: string) =>
    value === null ? (
      <span className="text-pencil">n/a</span>
    ) : (
      <Num stat={recordStat(value, display(value), metric, "rumour track record test", b.generated_at ?? at, "backtest")} display={display(value)} />
    );
  const peak = Math.max(...r.seasons.map((s) => s.rate));
  return (
    <article className="grid12 pt-10">
      <p className="hang mono-label">Rumour track record · what became of the transfer talk</p>
      <h1 className="hang mt-3 font-display text-[clamp(3rem,9vw,7rem)] leading-[0.9]">
        Do rumours <span className="italic">come true?</span>
      </h1>
      <p className="hang mt-6 max-w-2xl">
        Every Guardian Rumour Mill column since its first, each player it linked with a club checked against the moves that
        actually happened. Of {S(r.overall.links, int(r.overall.links), "rumours traced", "all seasons")} rumours we could trace
        since <span data-meta>{r.first_season}</span>, {S(r.overall.came_true, int(r.overall.came_true), "came true within half a year", "all seasons")}{" "}
        came true within half a year: {S(r.overall.rate, pct(r.overall.rate), "share that came true", "all seasons")}.
        {r.overall.rate_modern !== null && (
          <>
            {" "}Since <span data-meta>{r.modern_season}</span>, when the column became shorter and more selective,{" "}
            {S(r.overall.rate_modern, pct(r.overall.rate_modern), "share that came true", `since ${r.modern_season}`)} of{" "}
            {S(r.overall.links_modern, int(r.overall.links_modern), "rumours traced", `since ${r.modern_season}`)}.
          </>
        )}
      </p>
      <p className="hang mt-4 max-w-2xl">
        Next to every rumour on a club page we say how often reports like it came true. That reading comes from what the
        rumour itself shows: how often the same link was reported before, how many clubs it names, the transfer window, the
        player&apos;s value. On the latest season it scored a Brier of {B(b.brier, (v) => v.toFixed(3), "Brier score, rumour track record")}{" "}
        against {B(b.brier_recent_base, (v) => v.toFixed(3), "Brier score, recent base rate")} for the recent average (lower is better),
        and the rumours it rated likelier did come true more often.{" "}
        <a className="underline" href={RUMOURS_DOC}>How it is tested</a>.
      </p>

      {recent.length > 0 && (
        <section className="hang mt-10 max-w-3xl">
          <h2 className="mono-label">Linked in the press now · likeliest first · rumours, not facts</h2>
          <ul className="mt-2 space-y-2">
            {recent.map((x) => (
              <li key={`${x.slug}:${x.text}`} className="ruled pb-2">
                <Link className="font-display text-xl underline" href={`/club/${x.slug}/`}>
                  {x.club}
                </Link>
                <span className="block">
                  {x.text}{" "}
                  <span className="text-pencil">
                    Reports like this came true within half a year about one time in{" "}
                    <Num stat={x.record!.stat} display={x.record!.display} />.
                  </span>{" "}
                  {x.url && (
                    <a className="font-mono text-xs underline" href={x.url} target="_blank" rel="noopener noreferrer">
                      The Guardian
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="hang mt-10 max-w-3xl">
        <h2 className="mono-label">By outlet · where the column credits one</h2>
        <p className="mt-2">
          Most items are the column&apos;s own round-ups; an outlet is known only when the column links to it or names it.
          Each record is pulled towards the average in proportion to how little there is of it, so a handful of lucky
          calls does not make an outlet look reliable. They barely differ: the source tells you less than the rumour.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse font-mono text-sm">
            <caption className="sr-only">Outlets&apos; records: rumours traced, how many came true, that share as counted, and the record pulled towards the average</caption>
            <thead>
              <tr className="ruled text-left">
                <th scope="col" className="mono-label py-2 font-normal">Outlet</th>
                <th scope="col" className="mono-label py-2 text-right font-normal">Rumours</th>
                <th scope="col" className="mono-label py-2 text-right font-normal">Came true</th>
                <th scope="col" className="mono-label py-2 text-right font-normal">As counted</th>
                <th scope="col" className="mono-label py-2 text-right font-normal">Record</th>
              </tr>
            </thead>
            <tbody>
              {r.outlets.map((o) => (
                <tr key={o.outlet} className="border-b border-ink/15">
                  <td data-name className="py-1.5 pr-3 font-body text-base">
                    {o.outlet === "The Guardian" ? "The Rumour Mill itself" : o.outlet}
                  </td>
                  <td className="py-1.5 text-right">{S(o.links, int(o.links), "rumours traced", o.outlet)}</td>
                  <td className="py-1.5 text-right">{S(o.came_true, int(o.came_true), "came true within half a year", o.outlet)}</td>
                  <td className="py-1.5 text-right text-pencil">{S(o.raw, pct(o.raw), "share that came true, as counted", o.outlet)}</td>
                  <td className="py-1.5 text-right">{S(o.shrunk, pct(o.shrunk), "record, pulled towards the average", o.outlet)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="hang mt-10 max-w-3xl">
        <h2 className="mono-label">By season · share that came true within half a year</h2>
        <ul className="mt-3 space-y-1 font-mono text-sm">
          {r.seasons.map((s) => (
            <li key={s.season} className="grid grid-cols-[5.5rem_1fr_4rem_5rem] items-center gap-3">
              <span data-meta className="text-pencil">{s.season}</span>
              <span className="block h-2 bg-ink/10" aria-hidden="true">
                <span className="block h-2 bg-red" style={{ width: `${(s.rate / peak) * 100}%` }} />
              </span>
              <span className="text-right">{S(s.rate, pct(s.rate), "share that came true", s.season)}</span>
              <span className="text-right text-pencil">{S(s.links, int(s.links), "rumours traced", s.season)}</span>
            </li>
          ))}
        </ul>
        <p className="mono-label mt-4">
          Before <span data-meta>2012-13</span> fewer moves are on record, so early seasons are probably understated. A move counts
          only if Transfermarkt&apos;s open dataset or Wikipedia&apos;s transfer lists have it.
        </p>
      </section>
    </article>
  );
}
