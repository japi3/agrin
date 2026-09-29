# Retrieval evaluation

*2026-09-29 · 3968 passages · 35 on-topic and 8 off-topic questions in English, Hindi, Punjabi and Hinglish (`eval/retrieval_set.json`) · floor 0.62 · dense only*

| Metric | Result |
|---|---|
| Right subject ranked 1st | **29/35 (82%)** |
| Right subject in top 3 | **33/35 (94%)** |
| Off-topic questions abstained | **8/8** |
| Search time (median) | 0.1 ms |
| Embedding round trip (mean) | 822 ms |

| Language | 1st | Top 3 |
|---|---|---|
| en | 19/23 | 21/23 |
| hi | 4/5 | 5/5 |
| hinglish | 3/3 | 3/3 |
| pa | 3/4 | 4/4 |

Scores: on-topic 0.646–0.808, off-topic 0.515–0.602
Margin at the floor: **+0.043** (weakest on-topic 0.646 − strongest off-topic 0.602); floor is 0.62

Retrieval misses (2):
  - Can farmers earn money from carbon credits? → wanted “carbon credit”, got “Soil Organic Carbon: Importance, Measurement” at 0.683
  - What help is available for buying farm machinery? → wanted “mechanization”, got “Financial Assistance for Procurement of Agri” at 0.725

Typed token actually present in the top passage: **5/6**

