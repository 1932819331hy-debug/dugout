# Writer benchmark: which LLM writes notes that pass the publish gate

Generated 2026-10-16T06:03:48+00:00. Sections: the six club specialists' dossier questions for liverpool, arsenal. A draft counts only if it passes every gate check; otherwise the section falls back to deterministic templates (numbers are never affected either way).

| Model | Accepted | First try | Drafts with stray numbers | LLM errors | s / section | API calls |
|---|---|---|---|---|---|---|
| openrouter:poolside/laguna-s-2.1:free | 58% | 33% | 0 | 0 | 42.0 | 24 |
| openrouter:google/gemma-4-31b-it:free | 0% | 0% | 0 | 12 | 37.4 | 48 |
| local:qwen2.5:3b | 17% | 17% | 2 | 0 | 56.1 | 22 |

## Sample accepted notes

**openrouter:poolside/laguna-s-2.1:free** (liverpool, club, placeholders unrendered):

> Liverpool are {{stat:ev_d502a8bcaad692e0|ord}} in the Premier League table with {{stat:ev_10e9e4e3480aaf18}} points, having scored {{stat:ev_87e91471026ac201}} goals and conceded {{stat:ev_8d3e72466be9f644}} league goals, with their most recent league results reading {{stat:ev_748af597b924ffb6}}. Andoni Iraola has been Liverpool's head coach since {{stat:ev_c7b9e8c24fdb34a3|date}}, and his style profile covers {{stat:ev_aa025fcc98fbdaa0|int}} Premier League matches. Teams under Iraola average {{stat:ev_070c26120807547a|.0f}} defensive actions per match, more active without the ball than almost any Premier League manager's side, while creating {{stat:ev_5606ed69b29a4687|.2f}} expected goals per match, more dangerous than average. We recommend continuing to support Iraola's high-pressing, defensively active approach, as teams under him take {{stat:ev_5ac1bc669c7aaf92|pct}} of the threat in their matches and concede {{stat:ev_9ddf130886408e2d|.2f}} expected goals per match, both close to the league average.

**local:qwen2.5:3b** (liverpool, scout, placeholders unrendered):

> We recommend Liverpool strengthen with Jurriën Timber, as he fits the squad need, priority one and has a fair fee of {{stat:ev_4adbaebdc6bbfb25|eur_m}}. His expected minutes share at Liverpool is {{stat:ev_d2c60f57a90f494e|pct}}, making him a strong candidate for integration.

