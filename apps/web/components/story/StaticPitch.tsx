import type { StoryData } from "./types";

/** The no-WebGL / reduced-motion pitch: the same formation, gap and candidate, drawn once in SVG. */
export default function StaticPitch({ data }: { data: StoryData }) {
  const { home, away, gap, candidateSlot } = data.scene;
  const X = (x: number) => x + 52.5;
  const Y = (y: number) => 34 - y;
  return (
    <svg viewBox="-2 -2 109 72" role="img" aria-label={`${data.club} in their formation, with the gap marked in red`} className="w-full">
      <defs>
        <radialGradient id="gap">
          <stop offset="0" stopColor="#D7261E" stopOpacity="0.7" />
          <stop offset="1" stopColor="#D7261E" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="0" y="0" width="105" height="68" fill="#23402F" />
      {Array.from({ length: 10 }, (_, i) => (
        <rect key={i} x={i * 10.5} y="0" width="10.5" height="68" fill={i % 2 ? "#2a4a37" : "#23402F"} />
      ))}
      <g fill="none" stroke="#F6F3EA" strokeWidth="0.25">
        <rect x="0" y="0" width="105" height="68" />
        <line x1="52.5" y1="0" x2="52.5" y2="68" />
        <circle cx="52.5" cy="34" r="9.15" />
        <rect x="0" y="13.84" width="16.5" height="40.32" />
        <rect x="88.5" y="13.84" width="16.5" height="40.32" />
        <rect x="0" y="24.84" width="5.5" height="18.32" />
        <rect x="99.5" y="24.84" width="5.5" height="18.32" />
      </g>
      <circle cx={X(gap[0])} cy={Y(gap[1])} r="12" fill="url(#gap)" />
      {away.map(([x, y], i) => (
        <circle key={`a${i}`} cx={X(x)} cy={Y(y)} r="1.3" fill="#141414" />
      ))}
      {home.map(([x, y], i) => (
        <circle key={`h${i}`} cx={X(x)} cy={Y(y)} r="1.3" fill={i === candidateSlot ? "#D7261E" : "#F6F3EA"} />
      ))}
    </svg>
  );
}
