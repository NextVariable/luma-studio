"""Local startup, backup and restore for the studio's SQLite and media store."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def data_lock(data):
    import fcntl

    data.mkdir(parents=True, exist_ok=True)
    with (data / '.studio.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('这个数据目录正在使用，请关闭对应的流幕服务后重试') from None
        yield


def checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def check_database(db):
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite 完整性检查失败')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'projects', 'versions', 'jobs', 'spending'}.issubset(tables):
            raise ValueError('这个文件不是流幕作品数据库')


@contextmanager
def staged_directory(destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError('目标路径已存在，请选择一个新目录')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.luma-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'data'
        staged.mkdir(mode=0o700)
        yield staged
        # Reserve the name before publishing so an existing library is never replaced.
        destination.mkdir(mode=0o700)
        try:
            staged.rename(destination)
        except OSError:
            destination.rmdir()
            raise


def backup(data, destination):
    source_db = data / 'studio.sqlite'
    if not source_db.is_file():
        raise ValueError('未找到流幕作品数据库')
    if destination.resolve().is_relative_to(data.resolve()):
        raise ValueError('请把备份放在作品数据目录之外')
    with data_lock(data), staged_directory(destination) as staged:
        target_db = staged / source_db.name
        with closing(sqlite3.connect(source_db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target_db)) as target:
                source.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
        check_database(target_db)
        (staged / 'media').mkdir()
        files = {source_db.name: checksum(target_db)}
        for file in sorted((data / 'media').iterdir()):
            if file.is_symlink():
                raise ValueError('素材目录含有符号链接，无法安全备份')
            if file.is_file():
                copy = staged / 'media' / file.name
                shutil.copyfile(file, copy)
                files['media/' + file.name] = checksum(copy)
        (staged / 'backup.json').write_text(json.dumps({'version': 1, 'sha256': files}, ensure_ascii=False, indent=2), encoding='utf-8')


def restore(source, destination):
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('请将作品恢复到备份目录之外')
    manifest = json.loads((source / 'backup.json').read_text(encoding='utf-8'))
    files = manifest.get('sha256')
    if manifest.get('version') != 1 or not isinstance(files, dict) or 'studio.sqlite' not in files:
        raise ValueError('备份清单格式无效')
    with staged_directory(destination) as staged:
        (staged / 'media').mkdir()
        for name, expected in files.items():
            parts = Path(name).parts
            if name != 'studio.sqlite' and (len(parts) != 2 or parts[0] != 'media' or parts[1] == '..'):
                raise ValueError('备份含有无效素材路径')
            file = source / name
            if not file.is_file() or file.resolve().parent != (source.resolve() / Path(name).parent):
                raise ValueError(f'备份缺少文件或文件路径无效：{name}')
            copy = staged / name
            shutil.copyfile(file, copy)
            if checksum(copy) != expected:
                raise ValueError(f'备份文件校验失败：{name}')
        db = staged / 'studio.sqlite'
        check_database(db)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('UPDATE spending SET remaining=0')
            conn.execute("UPDATE jobs SET state='interrupted',error=?,updated=? WHERE kind NOT IN ('export','assemble') AND state IN ('queued','running','submitting','waiting_review')",
                         ('从备份恢复，需核实远程状态，避免重复提交', time.time()))
