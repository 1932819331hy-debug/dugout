import Story from "@/components/story/Story";
import type { StatRef, StoryData } from "@/components/story/types";
import { claimText, displays, dossier, section, type Dossier } from "@/lib/data";
import { FORMATION_SLOTS, GAP_ZONES, opposition, scatter, slotPositions } from "@/lib/formations";

const SHOWCASE = "liverpool";

// which slot a position-group gap occupies, by formation
const GAP_SLOTS: Record<string, string[]> = {
  goalkeeper: ["GK"],
  "centre-back": ["CB"],
  "full-back": ["RB", "RWB"],
  "defensive midfield": ["DM", "CM"],
  "central midfield": ["CM", "AM"],
  winger: ["RW", "RM", "AM"],
  "centre-forward": ["CF"],
};

function storyData(d: Dossier): StoryData {
  const disp = displays(d);
  const ref = (id: string): StatRef => ({ id, stat: d.stats[id], display: disp[id] ?? d.stats[id].display });
  // key_stats keep each section's facts in priority order (need one before need two, the top candidate first)
  const ordered = [...Object.values(d.key_stats ?? {}).flat().map((k) => k.stat), ...Object.keys(d.stats)];
  const find = (metric: string, pred: (e: string) => boolean = () => true) => {
    const id = ordered.find((i) => d.stats[i] && d.stats[i].metric === metric && pred(d.stats[i].entity_id));
    return id ? ref(id) : undefined;
  };
  const formation = find("predicted_formation");
  const slots = FORMATION_SLOTS[String(formation?.stat.value ?? "4-3-3")] ?? FORMATION_SLOTS["4-3-3"];
  const need = find("need");
  const needGroup = need ? String(need.stat.value) : undefined;
  const candidateSlot = needGroup ? slots.findIndex((s) => (GAP_SLOTS[needGroup] ?? []).includes(s)) : -1;
  const home = slotPositions(slots);

  // the top-ranked candidate the Scout section cited
  const cand = find("expected_minutes_share") ?? find("realism");
  const candId = cand?.stat.entity_id;
  const candStat = (metric: string) => (candId ? find(metric, (e) => e === candId) : undefined);
  const scout = section(d, "scout");
  const candLine = scout?.claims.map(claimText).find((t) => cand && t.includes(cand.stat.entity_name) && t.includes("("));
  const candClub = candLine?.match(/\(([^)]+)\)/)?.[1];

  const match = find("p_home_win") ?? find("p_away_win");
  const [homeName, awayName] = (match?.stat.entity_name ?? " v ").split(" v ");
  const matchId = match?.stat.entity_id;
  // six numbers with different metrics, cross-checked ones first, then re-checked single-source and model outputs
  const rank: Record<string, number> = { verified: 0, single_source: 1, model_output: 2 };
  const verifiedSamples = ordered
    .filter((id, i) => d.stats[id] && ordered.indexOf(id) === i && d.stats[id].status in rank)
    .sort((a, b) => rank[d.stats[a].status] - rank[d.stats[b].status])
    .filter((id, i, all) => all.findIndex((j) => d.stats[j].metric === d.stats[id].metric) === i)
    .slice(0, 6)
    .map(ref);

  return {
    club: d.club.name,
    slug: d.club.slug,
    manager: find("appointed")?.stat.entity_name ?? find("pl_matches")?.stat.entity_name,
    position: find("league_position", (e) => e === d.club.slug),
    formation,
    threat: find("threat_share"),
    defActions: find("def_actions"),
    need,
    needGroup,
    signings: (scout?.claims ?? [])
      .filter((c) => c.type === "attributed")
      .map((c) => ({ title: claimText(c).replace(/^According to [^,]+, /, ""), url: c.sources[0]?.url ?? null })),
    candidate: cand
      ? {
          name: cand.stat.entity_name,
          club: candClub,
          age: candStat("age"),
          value: candStat("market_value"),
          fairFee: candStat("fair_fee"),
          minutes: candStat("expected_minutes_share"),
          realism: candStat("realism"),
        }
      : undefined,
    verifiedSamples,
    numbersTotal: d.verification.stat_auditor.numbers_total,
    untraceable: d.verification.stat_auditor.numbers_untraceable,
    generatedAt: d.generated_at,
    prediction: match
      ? {
          home: homeName,
          away: awayName,
          kickoff: find("kickoff_utc", (e) => e === matchId),
          pHome: find("p_home_win", (e) => e === matchId),
          pDraw: find("p_draw", (e) => e === matchId),
          pAway: find("p_away_win", (e) => e === matchId),
        }
      : undefined,
    scene: {
      scatter: scatter(22),
      home,
      away: opposition(),
      candidateSlot,
      gap: GAP_ZONES[needGroup ?? ""] ?? [0, 0],
    },
  };
}

export default function Home() {
  return <Story data={storyData(dossier(SHOWCASE))} />;
}
