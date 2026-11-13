# Luma Studio · 流幕

[![CI](https://github.com/NextVariable/luma-studio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NextVariable/luma-studio/actions/workflows/ci.yml)

A local-first production workspace for episodic motion comics. Keep character looks, shots, and dialogue together, revise one shot at a time, and export the episode as an MP4.

[简体中文](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Provider setup](docs/providers.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

**Developer preview.** The local production and delivery workflow works with imported media and requires no model account. Cloud generation adapters are available with your own credentials. A full cloud-generated episode has yet to pass end-to-end acceptance.

## Quick start

Requirements are **macOS or Linux**, **Python 3.11+**, and **FFmpeg** with `ffprobe` and the `libx264` encoder.

```sh
git clone https://github.com/NextVariable/luma-studio.git
cd luma-studio
python3 -m luma check
python3 -m luma
```

Open [Luma Studio on localhost](http://127.0.0.1:7820/). The workspace currently uses a Chinese interface.

1. Create a work in **作品** and add shots in **镜头**.
2. Open **素材** on each shot to import and select a still or clip. Use **对白** to edit dialogue and attach an audio track.
3. Review each shot. Open **成片** to see what is missing, jump to the relevant controls, and export the episode.
4. After a revision, use the checklist to confirm which picture or audio can carry forward and export a new version. Previous exports remain available.

To reproduce the local revision and export flow with generated test fixtures, run `python3 -m unittest discover -s tests -p test_delivery_checklist.py -v`. This test runs FFmpeg locally and needs no API credentials.

## Production workflow

| Stage | What you can do |
| --- | --- |
| Plan | Organize scripts by episode. Plan shots manually or connect a Dify director workflow with continuity review and a human approval step. |
| Prepare | Pin character looks and reference images to each shot. Define generation segments, select candidates, and confirm what will be used. |
| Revise | Compare a single-shot proposal before applying it. See which visuals and dialogue tracks can be reused, need review, or have been deselected. |
| Deliver | Use the episode checklist to resolve blockers. Export an MP4 with the selected visuals, audio, and an optional subtitle track. |

## Optional model services

| Capability | Service |
| --- | --- |
| Director planning and approval | Dify |
| Prepared image and video generation | fal with FLUX.1 Kontext Pro and Kling 2.5 Turbo Pro |
| Dialogue synthesis and single-shot proposals | OpenAI direct connection. A previously configured Dify revision workflow remains an option for proposals. |

See [provider setup](docs/providers.md) for credentials and workflow templates. New libraries start with generation paused. The confirmation dialog shows an estimated cost or billing method and the number of local authorizations required. Providers bill their own accounts.

## Data and development

Luma serves one local library on loopback. See [architecture and data](docs/architecture.md) for backup and restore.

| Path | Contents |
| --- | --- |
| [`luma/`](luma/) | Python package: HTTP server, SQLite, job worker, provider adapters, FFmpeg export |
| [`web/`](web/) | Browser workspace in vanilla JavaScript, CSS and bundled assets |
| [`workflows/`](workflows/) | Dify workflow definitions and the generators that build them |
| [`tests/`](tests/) | Python and JavaScript regression suites |
| [`docs/`](docs/) | Architecture and provider setup |

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.js
```

The JavaScript tests use Node.js 22+. See the [MIT license](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md), [security reporting](SECURITY.md) and [code of conduct](CODE_OF_CONDUCT.md).
