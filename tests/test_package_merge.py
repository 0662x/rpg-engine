from __future__ import annotations

import unittest

from rpg_engine.content_types import ContentTypeSpec, MergePolicy
from rpg_engine.packages.merge import (
    dry_run_package_upgrade,
    merge_package_record,
    record_effective_action,
    record_mutating_diffs,
    render_package_dry_run,
)


class PackageMergeTests(unittest.TestCase):
    def test_record_merge_respects_field_ownership(self) -> None:
        spec = ContentTypeSpec(
            name="entity",
            record_id=lambda record: str(record["id"]),
            merge_policy=MergePolicy(
                author_owned={"name", "summary"},
                runtime_owned={"location_id", "item"},
                mergeable={"aliases"},
                conflict_only={"type"},
            ),
        )
        current = {
            "id": "item:test",
            "type": "item",
            "name": "旧名",
            "summary": "旧摘要",
            "location_id": "loc:runtime",
            "item": {"quantity": 5},
            "aliases": ["旧别名"],
        }
        incoming = {
            "id": "item:test",
            "type": "equipment",
            "name": "新名",
            "summary": "新摘要",
            "location_id": "loc:package",
            "item": {"quantity": 99},
            "aliases": ["旧别名", "新别名"],
            "details": {"unknown": True},
        }
        result = merge_package_record(spec, current, incoming)
        self.assertFalse(result.ok)
        self.assertEqual(result.merged["name"], "新名")
        self.assertEqual(result.merged["summary"], "新摘要")
        self.assertEqual(result.merged["location_id"], "loc:runtime")
        self.assertEqual(result.merged["item"], {"quantity": 5})
        self.assertEqual(result.merged["aliases"], ["旧别名", "新别名"])
        conflict_fields = {conflict.field for conflict in result.conflicts}
        self.assertEqual(conflict_fields, {"details", "type"})

    def test_dry_run_reports_create_update_and_delete_conflicts(self) -> None:
        spec = ContentTypeSpec(
            name="rule",
            record_id=lambda record: str(record["id"]),
            merge_policy=MergePolicy(
                author_owned={"statement"},
                mergeable={"aliases"},
                conflict_only={"id"},
            ),
        )
        result = dry_run_package_upgrade(
            spec,
            current_records=[
                {"id": "rule:one", "statement": "old", "aliases": ["old"]},
                {"id": "rule:deleted", "statement": "gone"},
            ],
            incoming_records=[
                {"id": "rule:one", "statement": "new", "aliases": ["new"]},
                {"id": "rule:new", "statement": "created"},
            ],
        )
        self.assertFalse(result.ok)
        by_id = {record.record_id: record for record in result.records}
        self.assertEqual(by_id["rule:new"].action, "create")
        self.assertEqual(by_id["rule:one"].merged["statement"], "new")
        self.assertEqual(by_id["rule:one"].merged["aliases"], ["old", "new"])
        self.assertEqual(by_id["rule:deleted"].action, "delete")
        self.assertEqual(by_id["rule:deleted"].conflicts[0].message, "record deletion requires explicit migration")
        rendered = render_package_dry_run(result)
        self.assertIn("# Package Dry Run: rule", rendered)
        self.assertIn("record deletion requires explicit migration", rendered)

    def test_omitted_and_runtime_package_fields_are_non_mutating_noops(self) -> None:
        spec = ContentTypeSpec(
            name="entity",
            record_id=lambda record: str(record["id"]),
            merge_policy=MergePolicy(
                author_owned={"name", "summary"},
                runtime_owned={"status", "location_id"},
                mergeable={"aliases"},
                conflict_only={"type"},
            ),
        )
        result = merge_package_record(
            spec,
            current={
                "id": "loc:test",
                "type": "location",
                "name": "Name",
                "summary": "Current summary",
                "status": "active",
                "location_id": "loc:runtime",
                "aliases": ["current"],
            },
            incoming={
                "id": "loc:test",
                "type": "location",
                "name": "Name",
                "location_id": "loc:package",
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.merged["summary"], "Current summary")
        self.assertEqual(result.merged["status"], "active")
        self.assertEqual(result.merged["location_id"], "loc:runtime")
        self.assertEqual(result.merged["aliases"], ["current"])
        self.assertEqual(record_mutating_diffs(result), ())
        self.assertEqual(record_effective_action(result), "unchanged")


if __name__ == "__main__":
    unittest.main()
