#!/usr/bin/env python3
"""Check local Markdown links under one or more paths."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data"}


def iter_markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
            continue
        if path.is_dir():
            for candidate in path.rglob("*.md"):
                if any(part in SKIP_DIRS for part in candidate.parts):
                    continue
                files.append(candidate)
    return sorted(set(files))


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if " " in target:
        before_title, _, possible_title = target.partition(" ")
        if possible_title.startswith(("\"", "'")):
            target = before_title
    return unquote(target)


def is_external_or_anchor(target: str) -> bool:
    if not target or target.startswith("#"):
        return True
    parsed = urlparse(target)
    return parsed.scheme in EXTERNAL_SCHEMES


def local_path_for(source_file: Path, target: str) -> Path | None:
    if is_external_or_anchor(target):
        return None
    path_part = target.split("#", 1)[0]
    if not path_part:
        return None
    parsed = urlparse(path_part)
    if parsed.scheme:
        return None
    target_path = Path(path_part)
    if target_path.is_absolute():
        return target_path
    return (source_file.parent / target_path).resolve()


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for match in LINK_RE.finditer(text):
        target = normalize_target(match.group(1))
        target_path = local_path_for(path, target)
        if target_path is None:
            continue
        if not target_path.exists():
            errors.append(f"{path}: missing local link -> {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown files or directories to check")
    args = parser.parse_args()

    files = iter_markdown_files(args.paths)
    errors: list[str] = []
    for path in files:
        errors.extend(check_file(path))

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(f"checked {len(files)} markdown files; local links ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
