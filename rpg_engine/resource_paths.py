from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


RESOURCE_PACKAGE = "rpg_engine.resources"


@dataclass(frozen=True)
class ResourceFile:
    id: str
    path: str
    text: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def resource_file(*parts: str) -> Traversable:
    node = files(RESOURCE_PACKAGE)
    for part in parts:
        node = node.joinpath(part)
    return node


def read_resource_text(*parts: str) -> str:
    return resource_file(*parts).read_text(encoding="utf-8")


def migration_resource_files() -> list[ResourceFile]:
    root = resource_file("migrations")
    items: list[ResourceFile] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.name.endswith(".sql"):
            items.append(
                ResourceFile(
                    id=child.name[:-4],
                    path=f"resources/migrations/{child.name}",
                    text=child.read_text(encoding="utf-8"),
                )
            )
    return items


def schema_resource_text(name: str) -> str:
    return read_resource_text("schemas", name)


def copy_resource_tree(source: Traversable, target: str | Path) -> Path:
    target_path = Path(target)
    if source.is_file():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source.read_bytes())
        return target_path
    if not source.is_dir():
        raise FileNotFoundError(str(source))

    target_path.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        copy_resource_tree(child, target_path / child.name)
    return target_path


def copy_packaged_example(name: str, target: str | Path, *, force: bool = False) -> Path:
    source = resource_file("examples", name)
    if not source.is_dir():
        raise FileNotFoundError(f"packaged example not found: {name}")

    target_path = Path(target)
    if target_path.exists():
        if not target_path.is_dir():
            if not force:
                raise FileExistsError(f"target path already exists and is not a directory: {target_path}")
            target_path.unlink()
        elif any(target_path.iterdir()):
            if not force:
                raise FileExistsError(f"target directory is not empty: {target_path}")
            shutil.rmtree(target_path)

    return copy_resource_tree(source, target_path)
