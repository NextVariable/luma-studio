# Architecture and local data · 架构与本机数据

Luma runs a browser workspace against a Python server bound to `127.0.0.1`. SQLite stores projects, version history, provider jobs, and local authorizations. The local worker executes queued work, and FFmpeg renders delivery from the approved episode snapshot.

```text
studio.py                      Local HTTP server, SQLite, job worker, export
production.py / preparation.py Shot state, asset bindings, segment validation
creative.py / continuity.py    Creative rules and cross-shot or episode dependencies
providers.py                   Dify workflow transport
fal_media.py / openai_direct.py Image, video, speech and revision adapters
generation_quote.py            Published list-price estimates
web/                           Browser workspace, styles and bundled assets
workflows/                     Dify definitions and builders
tests/                         Local workflow, export and interaction regressions
docs/                          Setup and operating notes
```

The default library is `data/studio.sqlite` with files in `data/media/`. Set `AUTEUR_DATA` to use an independent library. In that mode the library has its own `.env`. Keep the server on loopback and run one process per library.

## Backup and restore · 备份和恢复

Stop the instance for the library before backing it up. Use new destination directories:

```sh
python3 studio.py backup ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py restore ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py
```

Backups contain the project database, media, and exported films. Restore verifies files, pauses external generation, and marks unfinished remote jobs for reconciliation. Provider credentials are configured separately.

项目数据、素材与成片保存在本机。恢复时会校验文件并暂停生成，旧任务需要核实远程状态。凭据需要在恢复后的库里单独配置。
