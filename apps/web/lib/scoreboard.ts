// Scoreboard rows and the provenance of their numbers. No file access, so client components can use it too.
import type { Stat } from "./data";

const REPO_URL = "https://github.com/delta96040/dugout";

export interface Row {
  match_id: string;
  date: string;
  home: string;
  away: string;
  probs: [number, number, number];
  pick: "H" | "D" | "A";
  home_goals: number;
  away_goals: number;
  outcome: "H" | "D" | "A";
  hit: boolean;
  kind: "live" | "backtest";
  predicted_at: string;
  result: { sources: string[]; fetched_at: string | null; status: string };
}

export interface Board {
  generated_at: string;
  model: string;
  summary: { matches: number; live: number; hit_rate: number | null; rps: number | null };
  rows: Row[];
}

export const pct = (p: number) => `${Math.round(p * 100)}%`;
export const score = (r: Row) => `${r.home_goals}–${r.away_goals}`;

export function predStat(r: Row, i: number, generated: string): Stat {
  return {
    value: r.probs[i],
    display: pct(r.probs[i]),
    unit: null,
    metric: ["home win", "draw", "away win"][i] + " probability",
    entity_type: "match",
    entity_id: r.match_id,
    entity_name: `${r.home} v ${r.away}`,
    source: r.kind === "live" ? "dugout_model:predictor (published before kick-off)" : "dugout_model:predictor (walk-forward backtest)",
    source_url: `${REPO_URL}/blob/main/docs/backtests/predictor.md`,
    source_tier: 3,
    fetched_at: r.kind === "live" ? r.predicted_at : generated,
    query_kind: r.kind,
    status: "model_output",
    cross_checks: [],
  };
}

export function resultStat(r: Row): Stat {
  return {
    value: `${r.home_goals}-${r.away_goals}`,
    display: score(r),
    unit: "goals",
    metric: "result",
    entity_type: "match",
    entity_id: r.match_id,
    entity_name: `${r.home} v ${r.away}`,
    source: r.result.sources.join(" + "),
    source_url: null,
    source_tier: 1,
    fetched_at: r.result.fetched_at ?? r.date,
    query_kind: "sql",
    status: r.result.status,
    cross_checks: [],
  };
}
