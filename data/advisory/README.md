# Advisory corpus

The passages the assistant quotes when a question is answered by published
guidance rather than by a model — varieties, seed rates, spacing, seed
treatment, pest and disease practice, scheme paperwork.

Three files belong here, all built by one script:

| file | what it is |
|---|---|
| `chunks.jsonl` | one passage per line, with the page, section and revision date it came from |
| `vectors.npy` | one `float16` row per passage, L2-normalised, 768 dimensions |
| `manifest.json` | source, licence note, model, passage count, build date |

Build them with:

```bash
python scripts/build_advisory_index.py --languages en
```

It crawls the agriculture domain of [Vikaspedia](https://agriculture.vikaspedia.in/),
published by C-DAC under the Ministry of Electronics and IT, and embeds each
passage with `gemini-embedding-001`. The crawl takes a few minutes and is
cached in `data/advisory_cache/`; the embedding is the slow part, because the
free tier allows 90 texts a minute per key — roughly an hour and a half for
the English corpus on two keys. It is resumable, so an interrupted run picks
up where it stopped.

Rebuilding the image copies this directory to `/app/advisory`.

Without these files the app works exactly as before and the assistant loses
one tool: it will say it has no published source rather than answering such
questions from the model's own memory. That is the intended behaviour, not a
degraded one — see `packages/rag/rag/index.py` for why the score floor makes
returning nothing a normal outcome.

## Attribution

Vikaspedia content is published by the Government of India. Passages are
quoted with attribution and a link back to the page they came from, and the
interface shows those links beside the answer so a farmer or an extension
officer can open the original.
