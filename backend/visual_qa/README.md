# Visual QA

Headless browser preview QA for generated website builds.

- `runner.py` coordinates preview rendering and result assembly.
- `browser.py` resolves configured and known browser commands.
- `rendering.py` executes headless browser screenshots and scans runtime errors.
- `results.py` formats skipped/failed QA payloads.
- `png.py` reads screenshot dimensions.
- `constants.py` keeps browser QA limits and runtime error markers.
- `artifacts.py` creates safe project/session/test-run storage paths and hashes screenshots.
- `impact.py` maps changed files through imports to affected routes and test scope.
- `baseline.py` captures current-project screenshots before the first update.
- `persistence.py` records before/after artifacts and visual comparisons.

The automated flow captures or retrieves a baseline, builds candidate files in
a staged preview, selects full or affected routes, captures mobile/tablet/desktop
screenshots, persists their project/session mapping, and allows commit only after
the staged build and visual QA pass.

Import public helpers from `backend.visual_qa`; the previous module import surface is preserved.
