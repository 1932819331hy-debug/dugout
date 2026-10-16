"use client";

import { createContext } from "react";

/** Chapter on screen in the animated story, or -1 in the static story (everything shown). */
export const ActiveChapter = createContext(-1);
