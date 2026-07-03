from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def write_text_atomic(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    target = Path(path)
    with atomic_output_path(target) as tmp:
        tmp.write_text(text, encoding=encoding)
    return target


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    with atomic_output_path(target) as tmp:
        tmp.write_bytes(data)
    return target


@contextmanager
def atomic_output_path(path: str | Path) -> Iterator[Path]:
    target = Path(path)
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"atomic target is a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        _fsync_file(tmp)
        _copy_existing_mode(target, tmp)
        os.replace(tmp, target)
        fsync_directory(target.parent)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def fsync_directory(path: str | Path) -> None:
    directory = Path(path)
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_existing_mode(target: Path, tmp: Path) -> None:
    try:
        mode = target.stat().st_mode
    except FileNotFoundError:
        return
    os.chmod(tmp, mode & 0o777)
