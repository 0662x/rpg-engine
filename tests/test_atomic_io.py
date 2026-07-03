from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from rpg_engine.atomic_io import write_text_atomic
from rpg_engine.campaign import load_campaign
from rpg_engine.save_archive import MANIFEST_NAME, export_save, import_save_archive
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


class AtomicIOTests(unittest.TestCase):
    def test_write_text_atomic_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("old\n", encoding="utf-8")

            with self.assertRaisesRegex(OSError, "injected replace failure"):
                with mock.patch("rpg_engine.atomic_io.os.replace", side_effect=OSError("injected replace failure")):
                    write_text_atomic(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(Path(tmp).glob(".state.json.*.tmp")), [])


class SaveArchiveAtomicImportTests(unittest.TestCase):
    def test_import_rejects_unsafe_archive_path_without_creating_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "unsafe.aigmsave"
            data = b"unsafe"
            manifest = {
                "archive_schema_version": 1,
                "files": [
                    {
                        "path": "../evil.txt",
                        "bytes": len(data),
                        "sha256": "0" * 64,
                    }
                ],
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest))
                archive.writestr("../evil.txt", data)

            target = root / "target"
            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                import_save_archive(archive_path, target)

            self.assertFalse(target.exists())
            self.assertFalse((root / "evil.txt").exists())

    def test_import_failure_keeps_existing_target_directory_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir)
            archive_path = export_save(load_campaign(save_dir), root / "good.aigmsave").archive_path
            bad_archive_path = root / "bad.aigmsave"
            with zipfile.ZipFile(archive_path, "r") as source, zipfile.ZipFile(bad_archive_path, "w") as target_zip:
                manifest = json.loads(source.read(MANIFEST_NAME).decode("utf-8"))
                manifest["files"][0]["sha256"] = "0" * 64
                for name in source.namelist():
                    if name == MANIFEST_NAME:
                        target_zip.writestr(
                            MANIFEST_NAME,
                            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        )
                    else:
                        target_zip.writestr(name, source.read(name))

            target = root / "existing"
            target.mkdir()
            keep = target / "keep.txt"
            keep.write_text("keep\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                import_save_archive(bad_archive_path, target, force=True)

            self.assertEqual(keep.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((target / "campaign.yaml").exists())

    def test_import_force_replaces_existing_target_after_full_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir)
            archive_path = export_save(load_campaign(save_dir), root / "good.aigmsave").archive_path

            target = root / "existing"
            target.mkdir()
            (target / "keep.txt").write_text("replace me\n", encoding="utf-8")

            result = import_save_archive(archive_path, target, force=True)

            self.assertEqual(result.archive_path, target.resolve())
            self.assertTrue((target / "campaign.yaml").exists())
            self.assertTrue((target / MANIFEST_NAME).exists())
            self.assertFalse((target / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
