# Changelog · 更新记录

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). It has no tagged release yet, so everything below is unreleased developer-preview work.

## [Unreleased]

### Added
- Library home with a prompt composer, a wall of works and cached thumbnails.
- Left navigation rail, full-bleed shot stage and drag-and-drop shot reordering.
- Prepared image and video generation through fal, with list-price estimates before each call.
- OpenAI direct connection for speech and single-shot proposals.
- Picture-basis rule: a selected picture goes stale when its shot content changes, and must be confirmed or replaced before export.
- `POST /api/upload/discard` removes an uploaded file that no project, version or job references.
- `pyproject.toml` with package metadata, an optional `realtime` extra and lint settings. CI now runs `ruff` for errors.
- Community files: code of conduct, feature request template, `.editorconfig` and Dependabot updates for GitHub Actions and pip.

### Changed
- The library directory variable is now `LUMA_DATA`. `AUTEUR_DATA` still works.
- `.env.example` lists the current services first and moves the legacy Dify stage keys into comments.
- The Python modules moved into the `luma/` package. Start the server with `python3 -m luma`.
- The browser workspace was rebuilt as vanilla JavaScript modules sharing one `L` namespace. Pure logic lives in `web/js/logic.js` and is tested in Node.
- When an upload fails `ffprobe` validation, the original error is now kept as the cause of the reported one.
- Disabled navigation items are more visible on the library home page.

### Fixed
- Concurrent thumbnail requests no longer start parallel FFmpeg runs for the same file.
- Discarding an upload matches whole file names, so `a.mp4` is no longer blocked by a job that mentions `final-a.mp4`.
- Import previews list shot and asset names instead of raw JSON.
- A single-shot revision from a plain project may return `creative_spec: null`; previewing and applying it no longer fails.
- `workflows/production/shot-revision.yml` is regenerated so its output schema matches the generator. Re-import it into Dify and republish the app to use it.
