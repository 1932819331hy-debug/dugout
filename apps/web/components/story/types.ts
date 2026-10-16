import type { Stat } from "@/lib/data";
import type { XY } from "@/lib/formations";

export interface StatRef {
  id: string;
  stat: Stat;
  display: string;
}

export interface StoryData {
  club: string;
  slug: string;
  manager?: string;
  position?: StatRef;
  formation?: StatRef;
  threat?: StatRef;
  defActions?: StatRef;
  need?: StatRef;
  needGroup?: string;
  signings: { title: string; url: string | null }[];
  candidate?: {
    name: string;
    club?: string;
    age?: StatRef;
    value?: StatRef;
    fairFee?: StatRef;
    minutes?: StatRef;
    realism?: StatRef;
  };
  verifiedSamples: StatRef[];
  numbersTotal: number;
  untraceable: number;
  generatedAt: string;
  prediction?: { home: string; away: string; kickoff?: StatRef; pHome?: StatRef; pDraw?: StatRef; pAway?: StatRef };
  scene: { scatter: XY[]; home: XY[]; away: XY[]; candidateSlot: number; gap: XY };
}
