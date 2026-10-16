// Pitch coordinates (metres, origin at the centre spot; x along the length, the club attacks towards +x).
export type XY = [number, number];

// Slot codes come from the lineup optimiser (packages/models/src/dugout_models/lineup.py).
const LINES: Record<string, number> = {
  GK: -48, CB: -36, RB: -33, LB: -33, RWB: -22, LWB: -22, DM: -22, CM: -12, AM: 2, RM: -6, LM: -6, RW: 14, LW: 14, CF: 22,
};
const SIDE: Record<string, number> = { RB: -26, RWB: -28, RM: -26, RW: -24, LB: 26, LWB: 28, LM: 26, LW: 24 };

/** Positions for an XI given its slot codes (duplicates such as CB, CB, CB spread across the width). */
export function slotPositions(slots: string[]): XY[] {
  const groups: Record<string, number[]> = {};
  slots.forEach((s, i) => (groups[s] ??= []).push(i));
  const out: XY[] = new Array(slots.length);
  for (const [slot, idx] of Object.entries(groups)) {
    const x = LINES[slot] ?? 0;
    if (slot in SIDE) {
      idx.forEach((i) => (out[i] = [x, SIDE[slot]]));
      continue;
    }
    const spread = slot === "CB" ? 11 : slot === "CF" ? 10 : slot === "GK" ? 0 : 13;
    idx.forEach((i, k) => (out[i] = [x, idx.length === 1 ? 0 : -spread / 2 + (spread * k) / (idx.length - 1)]));
  }
  return out;
}

export const FORMATION_SLOTS: Record<string, string[]> = {
  "4-3-3": ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "CF", "LW"],
  "4-2-3-1": ["GK", "RB", "CB", "CB", "LB", "DM", "DM", "RW", "AM", "LW", "CF"],
  "3-4-2-1": ["GK", "CB", "CB", "CB", "RWB", "CM", "CM", "LWB", "AM", "AM", "CF"],
  "4-4-2": ["GK", "RB", "CB", "CB", "LB", "RM", "CM", "CM", "LM", "CF", "CF"],
};

/** The opposition: a generic 4-4-2 mirrored into the other half. */
export function opposition(): XY[] {
  return slotPositions(FORMATION_SLOTS["4-4-2"]).map(([x, y]) => [-x, -y]);
}

/** A loose "warm-up" scatter used before the formation is read (chapter one starts from it). */
export function scatter(n: number, seed = 7): XY[] {
  let s = seed;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  return Array.from({ length: n }, () => [(rnd() - 0.5) * 90, (rnd() - 0.5) * 56] as XY);
}

/** Where a position group's gap sits on the pitch (the red zone in chapter two). */
export const GAP_ZONES: Record<string, XY> = {
  goalkeeper: [-48, 0],
  "centre-back": [-36, 0],
  "full-back": [-30, -24],
  "defensive midfield": [-20, 0],
  "central midfield": [-10, 0],
  winger: [12, -22],
  "centre-forward": [22, 0],
};
