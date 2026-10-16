// Scroll and cursor state shared between the DOM story and the WebGL scene without React re-renders.
export const story = {
  progress: 0, // 0..1 across the six chapters
  mouse: [0, 0] as [number, number], // -1..1, for the parallax offset
};

export const CHAPTERS = 6;

/** Chapter index and progress within it for a global progress value. */
export function chapterAt(p: number): { index: number; local: number } {
  const x = Math.min(Math.max(p, 0), 0.9999) * CHAPTERS;
  return { index: Math.floor(x), local: x - Math.floor(x) };
}

export const smooth = (t: number) => t * t * (3 - 2 * t);
export const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
