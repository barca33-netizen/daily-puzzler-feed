# Daily Puzzler colouring feed

This public feed prepares five new colour-by-number pictures each day for the DailyPuzzler Android app.

- Source discovery: Openverse API
- Accepted licences: CC0 and Public Domain Mark only
- Output: completed preview, blank line art, region mask, shuffled palette and licence metadata
- Schedule: shortly after midnight UTC, plus manual runs
- Retention: fourteen dated sets

Every picture retains its source page, creator, provider and licence details in `meta.json` and the daily manifest. If generation fails, the last successful feed remains available and the Android app uses its bundled offline pictures.
