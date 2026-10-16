"use client";

import { useEffect, useState } from "react";

/** The repo's star count, fetched live from the public GitHub API (the only runtime request). */
export default function Stars() {
  const [stars, setStars] = useState<{ n: number; at: string } | null>(null);
  useEffect(() => {
    fetch("https://api.github.com/repos/delta96040/dugout")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setStars({ n: j.stargazers_count, at: new Date().toISOString() }))
      .catch(() => undefined);
  }, []);
  if (!stars) return null;
  return (
    <span data-meta title={`Source: GitHub API (api.github.com), fetched live at ${stars.at}`} className="font-mono">
      ★ {stars.n} <span className="text-pencil">live from GitHub</span>
    </span>
  );
}
