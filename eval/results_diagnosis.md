# Photo-diagnosis evaluation

*2026-10-01 · 5 labelled images from PlantVillage (CC0) · crop known, as in the app · `eval/diagnosis_set.json`*

| Metric | Result |
|---|---|
| Disease named first | **3/4 (75%)** |
| Disease among the candidates | **4/4 (100%)** |
| Healthy leaves left alone | **0/1** |
| Unusable photograph refused | 1/1 |
| Time per photograph (median) | 30.5 s |

Failures (2):
  - 2c22b17b-e914-453a-a379-15b29fe294b0___RS_HL 9720.JPG: healthy leaf diagnosed as “spider mites”
  - cbea79a3-7a68-4d16-b509-c84f333f9a38___R.S_HL 8137 copy 2.jpg: called a clean image unusable

Laboratory images on plain backgrounds. A field photograph has soil, shadow, overlapping leaves and camera shake; treat these as an upper bound, not an estimate of field performance.
