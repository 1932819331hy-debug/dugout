# Agent evaluation (qwen2.5:3b)

Generated 2026-10-16T01:18:27+00:00; 20 hand-labelled questions (`packages/agents/src/dugout_agents/eval/questions.yaml`); runtime 1545 s.

| Metric | Value |
|---|---|
| questions | 20 |
| routing accuracy | 0.941 |
| answer recall | 0.933 |
| claim recall | 1.0 |
| refusal accuracy | 1.0 |
| citation rate | 1.0 |
| numbers published | 186 |
| untraceable number rate | 0.0 |
| llm sections | 7 |
| template sections | 36 |
| llm attempts with stray numbers | 4 |
| llm attempts | 49 |
| sentences withheld | 0 |

## Per question

| id | route | answered | refusal | numbers | withheld | writer |
|---|---|---|---|---|---|---|
| h01 | club | 1/1 |  | 10 | 0 | template |
| h02 | club | 1/1 |  | 9 | 0 | llm:qwen2.5:3b, template |
| h03 | club | 1/1 |  | 5 | 0 | llm:qwen2.5:3b, template |
| h04 | match | 1/1 |  | 8 | 0 | template |
| h05 | club ✗ | 0/1 |  | 6 | 0 | llm:qwen2.5:3b, template |
| h06 | lineup | 1/1 |  | 13 | 0 | template |
| h07 | news | 1/1 |  | 1 | 0 | template |
| h08 | news | 1/1 |  | 1 | 0 | template |
| h09 | transfer | 1/1 |  | 3 | 0 | template |
| h10 | transfer | 1/1 |  | 2 | 0 | llm:qwen2.5:3b, template |
| h11 | club, scout | 1/1 |  | 28 | 0 | llm:qwen2.5:3b, template |
| h12 | scout | 1/1 |  | 12 | 0 | template |
| h13 | potential | 1/1 |  | 10 | 0 | template |
| h14 | potential | 1/1 |  | 10 | 0 | template |
| h15 | fit | 1/1 |  | 5 | 0 | template |
| h16 | fit | 1/1 |  | 5 | 0 | llm:qwen2.5:3b, template |
| h17 | club, scout | 1/1 |  | 24 | 0 | llm:qwen2.5:3b, template |
| h18 | club | 0/0 | True | 10 | 0 | template |
| h19 | club | 0/0 | True | 10 | 0 | template |
| h20 | club, news | 0/0 | True | 14 | 0 | template |
