# Photo-diagnosis evaluation

*2026-10-01 · 11 labelled images from PlantVillage (CC0) · crop known, as in the app · `eval/diagnosis_set.json`*

**Partial run: 11 of 60 images scored.** The rest went unanswered (quota) and are not counted either way.

| Metric | Result |
|---|---|
| Disease named first | **5/11 (45%)** |
| Disease among the candidates | **10/11 (90%)** |

Not measured on this run: healthy leaves (none of the 15 was answered), the unusable-photograph refusal (it ran after quota was gone, so the service's own error was counted as a refusal), and time per photograph (the recorded median of 0.0 s timed instant error returns, not diagnoses).

Failures among the scored images (1):
  - 21a4dee8-257f-48ea-90d2-0d2402b1a88a___UF.GRC_YLCV_Lab 01524.JPG: wanted “yellow leaf curl virus”, got “magnesium deficiency”

Laboratory images on plain backgrounds. A field photograph has soil, shadow, overlapping leaves and camera shake; treat these as an upper bound, not an estimate of field performance.
