# Architecture and local data · 架构与本机数据

Luma runs a browser workspace against a Python server bound to `127.0.0.1`. SQLite stores projects, version history, provider jobs, and local authorizations. The local worker executes queued work, and FFmpeg renders delivery from the approved episode snapshot.

```text
luma/
  studio.py                  Local HTTP server, SQLite, job worker, export
  production.py              Shot state, asset bindings, segment validation
  preparation.py             Prepared generation segments and reference plans
  creative.py, continuity.py Creative rules and cross-shot or episode dependencies
  providers.py               Dify workflow transport
  fal_media.py               fal image and video adapter
  openai_direct.py           Speech and single-shot proposal adapter
  generation_quote.py        Published list-price estimates
  assembly.py, episodes.py   Clip assembly and episode boundaries
  drama_import.py            Frozen short-drama bundle import
  local_storage.py           Backup, restore and the single-process data lock
web/                         Browser workspace, styles and bundled assets
workflows/                   Dify definitions and the generators that build them
tests/                       Python and JavaScript regression suites
docs/                        Setup and operating notes
```

The default library is `data/studio.sqlite` with files in `data/media/`. Set `AUTEUR_DATA` to use an independent library. In that mode the library has its own `.env`. Keep the server on loopback and run one process per library.

## Backup and restore · 备份和恢复

Stop the instance for the library before backing it up. Use new destination directories:

```sh
python3 -m luma backup ./luma-backup
AUTEUR_DATA=./luma-restored python3 -m luma restore ./luma-backup
AUTEUR_DATA=./luma-restored python3 -m luma
```

Backups contain the project database, media, and exported films. Restore verifies files, pauses external generation, and marks unfinished remote jobs for reconciliation. Provider credentials are configured separately.

项目数据、素材与成片保存在本机。恢复时会校验文件并暂停生成，旧任务需要核实远程状态。凭据需要在恢复后的库里单独配置。
