# Agent evaluation (qwen2.5:3b)

Generated 2026-10-16T00:40:38+00:00; 56 hand-labelled questions (`packages/agents/src/dugout_agents/eval/questions.yaml`); runtime 4744 s.

| Metric | Value |
|---|---|
| questions | 56 |
| routing accuracy | 1.0 |
| answer recall | 0.962 |
| claim recall | 1.0 |
| refusal accuracy | 1.0 |
| citation rate | 1.0 |
| numbers published | 546 |
| untraceable number rate | 0.0 |
| llm sections | 26 |
| template sections | 103 |
| llm attempts with stray numbers | 11 |
| llm attempts | 162 |
| sentences withheld | 0 |

## Per question

| id | route | answered | refusal | numbers | withheld | writer |
|---|---|---|---|---|---|---|
| q01 | club | 1/1 |  | 10 | 0 | template |
| q02 | club | 1/1 |  | 2 | 0 | llm:qwen2.5:3b, template |
| q03 | club | 1/1 |  | 10 | 0 | template |
| q04 | club | 1/1 |  | 10 | 0 | template |
| q05 | club | 1/1 |  | 10 | 0 | template |
| q06 | club | 1/1 |  | 10 | 0 | template |
| q07 | club | 1/1 |  | 2 | 0 | llm:qwen2.5:3b, template |
| q08 | club | 1/1 |  | 10 | 0 | template |
| q09 | club | 1/1 |  | 8 | 0 | llm:qwen2.5:3b, template |
| q10 | club | 1/1 |  | 6 | 0 | llm:qwen2.5:3b, template |
| q11 | club | 1/1 |  | 4 | 0 | llm:qwen2.5:3b, template |
| q12 | club, news | 1/1 |  | 14 | 0 | template |
| q13 | match | 1/1 |  | 8 | 0 | template |
| q14 | match | 2/2 |  | 8 | 0 | template |
| q15 | club, match | 1/1 |  | 21 | 0 | llm:qwen2.5:3b, template |
| q16 | club, match | 1/1 |  | 16 | 0 | llm:qwen2.5:3b, template |
| q17 | match, lineup | 2/2 |  | 21 | 0 | llm:qwen2.5:3b, template |
| q18 | club, lineup | 1/1 |  | 25 | 0 | llm:qwen2.5:3b, template |
| q19 | club, lineup | 1/1 |  | 27 | 0 | llm:qwen2.5:3b, template |
| q20 | lineup, news | 1/1 |  | 17 | 0 | template |
| q21 | news | 1/1 |  | 1 | 0 | template |
| q22 | club, news | 1/1 |  | 14 | 0 | template |
| q23 | match, news | 1/1 |  | 8 | 0 | llm:qwen2.5:3b, template |
| q24 | news | 1/1 |  | 1 | 0 | template |
| q25 | news | 1/1 |  | 1 | 0 | template |
| q26 | news | 1/1 |  | 1 | 0 | template |
| q27 | transfer | 1/1 |  | 3 | 0 | template |
| q28 | transfer | 1/1 |  | 3 | 0 | llm:qwen2.5:3b, template |
| q29 | transfer | 1/1 |  | 12 | 0 | template |
| q30 | transfer | 1/1 |  | 12 | 0 | template |
| q31 | transfer | 1/1 |  | 4 | 0 | template |
| q32 | transfer | 1/1 |  | 3 | 0 | llm:qwen2.5:3b, template |
| q33 | scout | 1/1 |  | 12 | 0 | template |
| q34 | scout | 1/1 |  | 12 | 0 | template |
| q35 | scout | 1/2 |  | 6 | 0 | llm:qwen2.5:3b, template |
| q36 | scout, fit | 1/1 |  | 14 | 0 | llm:qwen2.5:3b, template |
| q37 | club | 1/1 |  | 10 | 0 | template |
| q38 | club | 1/1 |  | 9 | 0 | llm:qwen2.5:3b, template |
| q39 | match | 1/1 |  | 6 | 0 | llm:qwen2.5:3b, template |
| q40 | news | 1/1 |  | 0 | 0 | llm:qwen2.5:3b, template |
| q41 | transfer | 1/1 |  | 3 | 0 | template |
| q42 | club | 1/1 |  | 10 | 0 | template |
| q43 | match, lineup | 2/2 |  | 25 | 0 | llm:qwen2.5:3b, template |
| q44 | news, scout | 1/1 |  | 8 | 0 | llm:qwen2.5:3b, template |
| q45 | club | 1/1 |  | 10 | 0 | template |
| q46 | club, news | 0/0 | True | 14 | 0 | template |
| q47 | club, news | 0/0 | True | 14 | 0 | template |
| q48 | club, news | 0/0 | True | 8 | 0 | llm:qwen2.5:3b, template |
| q49 | club, news | 0/0 | True | 14 | 0 | template |
| q50 | club | 0/0 | True | 10 | 0 | template |
| q51 | potential | 2/2 |  | 10 | 0 | template |
| q52 | potential | 1/1 |  | 10 | 0 | llm:qwen2.5:3b, template |
| q53 | potential | 1/1 |  | 11 | 0 | template |
| q54 | fit | 2/2 |  | 5 | 0 | llm:qwen2.5:3b, template |
| q55 | fit | 1/1 |  | 5 | 0 | template |
| q56 | potential, fit | 1/2 |  | 18 | 0 | llm:qwen2.5:3b, template |
