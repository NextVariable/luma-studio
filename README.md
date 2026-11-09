# Luma Studio · 流幕

A local-first workspace for episodic comics and short-film production. Organize scripts, character looks, shots, and dialogue, then cut and export an episode from selected media.

[中文指南](README.zh-CN.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

**Status: developer preview.** The local import-to-export path is available. Dify workflows for shot planning, shot revision, and voice are optional integrations that require your own Dify apps. Image and video generation require a supported provider integration. The local app starts with external generation paused.

## Quick start

Install Python 3.11+ and FFmpeg with `ffprobe` and the `libx264` encoder. No Python packages are needed.

```sh
python3 studio.py check
python3 studio.py
```

Open [the local workspace](http://127.0.0.1:7820/). Create a work, enter a script, and add shots. Import and select a picture or clip for each shot, then review the shots and open **Delivery (成片)** to export the episode. You can attach dialogue audio or export with captions and the selected clip’s audio.

## How it works

- The browser workspace edits projects served from `studio.py`, which stores project versions and job state in SQLite.
- Production preparation separates narrative shots from generation segments. Shot dependencies track changes that need review before delivery.
- FFmpeg composes selected media, dialogue tracks, and an optional MP4 subtitle track.
- The optional Dify adapter handles workflow runs and review handoffs. Import templates from [workflows/production](workflows/production/), configure the corresponding published app through Settings, and use the read-only connection check before authorizing calls.

The server binds to loopback for single-user use. On macOS and Linux, stop the corresponding studio process before backing up. Use new destination directories:

```sh
python3 studio.py backup ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py restore ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py
```

Backups include the database, media, and exported films. Restoration pauses external generation and interrupts unfinished remote jobs. Configure provider credentials separately on a new installation.

## Development

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.js
```

Use Node.js 22+ for the JavaScript tests. The tests use local fixtures and do not require model credentials. See [third-party notices](THIRD_PARTY_NOTICES.md) for bundled assets and external dependencies.
