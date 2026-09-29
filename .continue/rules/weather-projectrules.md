---
name: Wetter project rules
alwaysApply: true
---
- Image `localhost/wetter_weather`. Tests:
  `podman run --rm -v "$PWD":/app:Z -w /app localhost/wetter_weather timeout -k 10 300 python -m pytest -q`
  Syntax check: the same with `python -m py_compile <file>`. Rebuild (`podman compose build`)
  only when requirements.txt changes.
- Don't run `podman compose up/down` and don't touch the `weather-data` volume: the user deploys.
- Weather services (Open-Meteo, Bright Sky): only via `meteo_get`, and only when the task asks
  for a live check. Never curl/wget/Python for this.
- Backend: timezone-aware UTC everywhere. Logic in small pure functions with tests;
  Aggregator/Store only move data. A failing source never blocks the app; bad upstream
  data becomes `SourceError`.
- Frontend: no CDN, no build step. CSP `default-src 'self'`: no inline scripts, `on*=`
  handlers or `style="…"` in HTML; API data only via `textContent` (`innerHTML` only
  `""` or constants). New UI code goes into its own file.
- Data conventions (time windows, units) are documented in `docs/ARCHITECTURE.md`
  ("Data conventions"). Read the relevant part before touching them.
- Markdown: no hard line breaks in prose (one line per paragraph or list item). Diagrams as
  ```` ```mermaid ```` blocks, every node label in double quotes.
- Tasks come as sub-steps: do one per chat, commit as `Step Nx: <summary>`, then stop.
