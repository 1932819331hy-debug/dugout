# Agent evaluation (qwen2.5:3b)

Generated 2026-10-15T23:18:45+00:00; 56 hand-labelled questions (`packages/agents/src/dugout_agents/eval/questions.yaml`); runtime 4091 s.

| Metric | Value |
|---|---|
| questions | 56 |
| routing accuracy | 1.0 |
| answer recall | 0.962 |
| claim recall | 0.6 |
| refusal accuracy | 1.0 |
| citation rate | 1.0 |
| numbers published | 408 |
| untraceable number rate | 0.0 |
| llm sections | 43 |
| template sections | 86 |
| llm attempts with stray numbers | 10 |
| llm attempts | 145 |
| sentences withheld | 0 |

## Per question

| id | route | answered | refusal | numbers | withheld | writer |
|---|---|---|---|---|---|---|
| q01 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q02 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q03 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q04 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q05 | club | 1/1 |  | 10 | 0 | template |
| q06 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q07 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q08 | club | 1/1 |  | 10 | 0 | template |
| q09 | club | 1/1 |  | 10 | 0 | template |
| q10 | club | 1/1 |  | 10 | 0 | template |
| q11 | club | 1/1 |  | 2 | 0 | llm:qwen2.5:3b, template |
| q12 | club, news | 0/1 |  | 1 | 0 | llm:qwen2.5:3b |
| q13 | match | 1/1 |  | 8 | 0 | template |
| q14 | match | 2/2 |  | 8 | 0 | template |
| q15 | club, match | 1/1 |  | 12 | 0 | llm:qwen2.5:3b, template |
| q16 | club, match | 1/1 |  | 12 | 0 | llm:qwen2.5:3b, template |
| q17 | match, lineup | 2/2 |  | 24 | 0 | llm:qwen2.5:3b, template |
| q18 | club, lineup | 1/1 |  | 25 | 0 | llm:qwen2.5:3b, template |
| q19 | club, lineup | 1/1 |  | 27 | 0 | template |
| q20 | lineup, news | 1/1 |  | 5 | 0 | llm:qwen2.5:3b, template |
| q21 | news | 0/1 |  | 0 | 0 | llm:qwen2.5:3b, template |
| q22 | club, news | 1/1 |  | 9 | 0 | llm:qwen2.5:3b, template |
| q23 | match, news | 1/1 |  | 6 | 0 | llm:qwen2.5:3b, template |
| q24 | news | 1/1 |  | 1 | 0 | template |
| q25 | news | 0/1 |  | 0 | 0 | llm:qwen2.5:3b, template |
| q26 | news | 1/1 |  | 1 | 0 | template |
| q27 | transfer | 1/1 |  | 2 | 0 | llm:qwen2.5:3b, template |
| q28 | transfer | 1/1 |  | 3 | 0 | llm:qwen2.5:3b, template |
| q29 | transfer | 1/1 |  | 12 | 0 | template |
| q30 | transfer | 1/1 |  | 12 | 0 | template |
| q31 | transfer | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q32 | transfer | 1/1 |  | 3 | 0 | template |
| q33 | scout | 1/1 |  | 12 | 0 | template |
| q34 | scout | 1/1 |  | 12 | 0 | template |
| q35 | scout | 1/2 |  | 6 | 0 | llm:qwen2.5:3b, template |
| q36 | scout, fit | 1/1 |  | 4 | 0 | llm:qwen2.5:3b, template |
| q37 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q38 | club | 1/1 |  | 5 | 0 | llm:qwen2.5:3b, template |
| q39 | match | 1/1 |  | 8 | 0 | template |
| q40 | news | 1/1 |  | 2 | 0 | template |
| q41 | transfer | 1/1 |  | 3 | 0 | template |
| q42 | club | 1/1 |  | 1 | 0 | llm:qwen2.5:3b, template |
| q43 | match, lineup | 2/2 |  | 25 | 0 | llm:qwen2.5:3b, template |
| q44 | news, scout | 1/1 |  | 16 | 0 | template |
| q45 | club | 1/1 |  | 10 | 0 | template |
| q46 | club, news | 0/0 | True | 3 | 0 | llm:qwen2.5:3b, template |
| q47 | club, news | 0/0 | True | 0 | 0 | llm:qwen2.5:3b |
| q48 | club, news | 0/0 | True | 6 | 0 | llm:qwen2.5:3b, template |
| q49 | club, news | 0/0 | True | 14 | 0 | template |
| q50 | club | 0/0 | True | 0 | 0 | llm:qwen2.5:3b, template |
| q51 | potential | 2/2 |  | 10 | 0 | template |
| q52 | potential | 1/1 |  | 10 | 0 | llm:qwen2.5:3b, template |
| q53 | potential | 1/1 |  | 11 | 0 | template |
| q54 | fit | 2/2 |  | 5 | 0 | template |
| q55 | fit | 1/1 |  | 5 | 0 | template |
| q56 | potential, fit | 2/2 |  | 19 | 0 | llm:qwen2.5:3b, template |
