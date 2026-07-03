from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _normalize_text(text: str) -> str:
    return text.rstrip("\r\n")


def read_text_file_arg(path: str) -> str:
    try:
        return _normalize_text(Path(path).expanduser().read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise argparse.ArgumentTypeError(f"cannot read UTF-8 text file {path}: {exc}") from exc
    except OSError as exc:
        raise argparse.ArgumentTypeError(f"cannot read text file {path}: {exc}") from exc


def add_user_text_source_args(
    parser: argparse.ArgumentParser,
    *,
    required: bool,
    help_text: str = "current player request",
) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--user-text", dest="user_text", help=help_text)
    group.add_argument(
        "--user-text-file",
        dest="user_text_file",
        type=read_text_file_arg,
        help="read the player request from a UTF-8 text file",
    )
    group.add_argument(
        "--user-text-stdin",
        dest="user_text_stdin",
        action="store_true",
        help="read the player request from stdin",
    )


def add_user_text_external_source_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--user-text-file",
        dest="user_text_file",
        type=read_text_file_arg,
        help="read the player request from a UTF-8 text file",
    )
    group.add_argument(
        "--user-text-stdin",
        dest="user_text_stdin",
        action="store_true",
        help="read the player request from stdin",
    )


def resolve_user_text_arg(
    args: argparse.Namespace,
    *,
    required: bool = True,
    default: str | None = None,
) -> str | None:
    inline_text = getattr(args, "user_text", None)
    file_text = getattr(args, "user_text_file", None)
    stdin_requested = bool(getattr(args, "user_text_stdin", False))
    provided = [inline_text is not None, file_text is not None, stdin_requested]
    if sum(provided) > 1:
        raise ValueError("use only one of user text, --user-text-file, or --user-text-stdin")
    if file_text is not None:
        return str(file_text)
    if stdin_requested:
        return _normalize_text(sys.stdin.read())
    if inline_text is not None:
        return str(inline_text)
    if default is not None:
        return default
    if required:
        raise ValueError("user text is required")
    return None
