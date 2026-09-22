# Local soil map of India

`india_soilgrids_1km.tif` belongs here. It is not in git (about 190 MB, and
`*.tif` is ignored), so build it once:

```bash
docker exec -i agrin python - < scripts/build_india_soil.py
docker cp agrin:/app/.cache/india_soilgrids_1km.tif data/soil/
```

then rebuild the image, which copies this directory to `/app/soil`.

Without it the app still works everywhere, asking ISRIC's live service for
each new location. With it, every point in India answers from disk. See
`scripts/build_india_soil.py` for what the 1 km resolution trades away.
