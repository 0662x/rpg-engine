from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable

from .campaign import Campaign
from .db import rebuild_fts, utc_now
from .projections import (
    PROJECTION_VERSIONS,
    current_turn_id,
    ensure_projection_rows,
    mark_projection_clean,
    mark_projection_failed,
    process_outbox,
    projection_effective_status,
    projection_tables_exist,
    rewrite_events_jsonl,
)


REFRESHABLE_STATUSES = {"dirty", "failed", "refreshing", "stale"}
COMMIT_POLICIES = {"service_managed", "caller_committed_required"}


@dataclass(frozen=True)
class ProjectionItemReport:
    name: str
    status: str
    previous_status: str | None = None
    artifacts: tuple[str, ...] = ()
    error: str | None = None
    turn_id: str | None = None
    version: int | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status != "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "previous_status": self.previous_status,
            "artifacts": list(self.artifacts),
            "error": self.error,
            "turn_id": self.turn_id,
            "version": self.version,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ProjectionReport:
    profile: str
    requested: tuple[str, ...] = ()
    dirty: tuple[str, ...] = ()
    refreshed: tuple[str, ...] = ()
    clean: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    requested_dirty: tuple[str, ...] = ()
    requested_failed: tuple[str, ...] = ()
    requested_clean: tuple[str, ...] = ()
    requested_stale: tuple[str, ...] = ()
    global_dirty: tuple[str, ...] = ()
    global_failed: tuple[str, ...] = ()
    global_clean: tuple[str, ...] = ()
    global_stale: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    items: tuple[ProjectionItemReport, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float | None = None

    @property
    def ok(self) -> bool:
        return not self.requested_failed and not self.errors

    @property
    def status(self) -> str:
        if self.requested_failed:
            return "failed" if not self.refreshed else "partial_failure"
        if self.requested_stale:
            return "stale"
        if self.requested_dirty:
            return "dirty"
        return "clean"

    @property
    def global_status(self) -> str:
        if self.global_failed:
            return "failed"
        if self.global_stale:
            return "stale"
        if self.global_dirty:
            return "dirty"
        return "clean"

    def item(self, name: str) -> ProjectionItemReport | None:
        for item in self.items:
            if item.name == name:
                return item
        return None

    def artifacts_for(self, name: str) -> tuple[str, ...]:
        item = self.item(name)
        return item.artifacts if item else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "status": self.status,
            "ok": self.ok,
            "requested": list(self.requested),
            "dirty": list(self.dirty),
            "refreshed": list(self.refreshed),
            "clean": list(self.clean),
            "failed": list(self.failed),
            "requested_dirty": list(self.requested_dirty),
            "requested_failed": list(self.requested_failed),
            "requested_clean": list(self.requested_clean),
            "requested_stale": list(self.requested_stale),
            "global_dirty": list(self.global_dirty),
            "global_failed": list(self.global_failed),
            "global_clean": list(self.global_clean),
            "global_stale": list(self.global_stale),
            "global_status": self.global_status,
            "skipped": list(self.skipped),
            "artifacts": list(self.artifacts),
            "errors": list(self.errors),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "items": [item.to_dict() for item in self.items],
        }

    def render(self) -> str:
        lines = [
            "# Projection Report",
            "",
            f"- profile: `{self.profile}`",
            f"- status: `{self.status}`",
            f"- ok: `{'yes' if self.ok else 'no'}`",
        ]
        if self.refreshed:
            lines.append(f"- refreshed: `{', '.join(self.refreshed)}`")
        if self.requested_dirty:
            lines.append(f"- requested_dirty: `{', '.join(self.requested_dirty)}`")
        if self.requested_failed:
            lines.append(f"- requested_failed: `{', '.join(self.requested_failed)}`")
        if self.global_dirty:
            lines.append(f"- global_dirty: `{', '.join(self.global_dirty)}`")
        if self.global_failed:
            lines.append(f"- global_failed: `{', '.join(self.global_failed)}`")
        if self.skipped:
            lines.append(f"- skipped: `{', '.join(self.skipped)}`")
        if self.errors:
            lines.extend(["", "## Errors", ""])
            lines.extend(f"- {error}" for error in self.errors)
        if self.items:
            lines.extend(["", "## Items", ""])
            for item in self.items:
                lines.append(f"- `{item.name}`: `{item.status}`")
                for artifact in item.artifacts:
                    lines.append(f"  - artifact: `{artifact}`")
                if item.duration_ms is not None:
                    lines.append(f"  - duration_ms: `{item.duration_ms:.3f}`")
                if item.error:
                    lines.append(f"  - error: {item.error}")
        return "\n".join(lines).rstrip() + "\n"


class ProjectionService:
    def __init__(self, campaign: Campaign, conn: sqlite3.Connection) -> None:
        self.campaign = campaign
        self.conn = conn

    def refresh(
        self,
        *,
        names: Iterable[str] | None = None,
        dirty_only: bool = True,
        profile: str = "projection_refresh",
        include_outbox: bool = True,
        options: dict[str, dict[str, Any]] | None = None,
        commit_policy: str = "service_managed",
    ) -> ProjectionReport:
        if commit_policy not in COMMIT_POLICIES:
            raise ValueError(f"unsupported projection commit policy: {commit_policy}")
        if commit_policy == "caller_committed_required" and self.conn.in_transaction:
            raise RuntimeError("ProjectionService requires caller changes to be committed before refresh")

        started_at = utc_now()
        started = perf_counter()
        if projection_tables_exist(self.conn):
            ensure_projection_rows(self.conn, turn_id=current_turn_id(self.conn))
            self.conn.commit()

        outbox_errors: list[str] = []
        outbox_artifacts: list[str] = []
        outbox_refreshed: list[str] = []
        original_requested = tuple(names) if names is not None else tuple(PROJECTION_VERSIONS)
        if include_outbox and (names is None or "events_jsonl" in original_requested):
            outbox_result = process_outbox(self.campaign, self.conn)
            outbox_errors.extend(outbox_result.errors)
            outbox_artifacts.extend(outbox_result.artifacts)
            if outbox_result.refreshed:
                outbox_refreshed.append("events_jsonl")

        requested = list(original_requested)
        skipped: list[str] = []
        if dirty_only and projection_tables_exist(self.conn):
            refreshable = self._names_with_status(REFRESHABLE_STATUSES)
            requested = [name for name in requested if name in refreshable]
            skipped = [name for name in original_requested if name not in requested]

        item_options = options or {}
        items = tuple(self._refresh_one(name, options=item_options.get(name, {})) for name in requested)
        return self._build_report(
            profile=profile,
            requested=tuple(requested),
            skipped=tuple(skipped),
            items=items,
            outbox_errors=tuple(outbox_errors),
            outbox_artifacts=tuple(outbox_artifacts),
            outbox_refreshed=tuple(dict.fromkeys(outbox_refreshed)),
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=(perf_counter() - started) * 1000,
        )

    def _refresh_one(self, name: str, *, options: dict[str, Any]) -> ProjectionItemReport:
        previous = self._state_for(name)
        if name not in PROJECTION_VERSIONS:
            return ProjectionItemReport(
                name=name,
                status="failed",
                previous_status=previous.get("status"),
                error=f"unknown projection: {name}",
                turn_id=previous.get("last_turn_id"),
                version=previous.get("version"),
            )

        turn_id = current_turn_id(self.conn)
        self._mark_refreshing(name, turn_id=turn_id)
        started = perf_counter()
        try:
            artifacts, metadata = self._write_projection(name, options=options)
            mark_projection_clean(self.conn, name, turn_id=turn_id)
            self.conn.commit()
            return ProjectionItemReport(
                name=name,
                status="clean",
                previous_status=previous.get("status"),
                artifacts=tuple(artifacts),
                turn_id=turn_id,
                version=PROJECTION_VERSIONS[name],
                duration_ms=(perf_counter() - started) * 1000,
                metadata=metadata,
            )
        except Exception as exc:
            message = str(exc)
            mark_projection_failed(self.conn, name, message)
            self.conn.commit()
            return ProjectionItemReport(
                name=name,
                status="failed",
                previous_status=previous.get("status"),
                error=message,
                turn_id=turn_id,
                version=PROJECTION_VERSIONS[name],
                duration_ms=(perf_counter() - started) * 1000,
            )

    def _write_projection(self, name: str, *, options: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        if name == "events_jsonl":
            rewrite_events_jsonl(self.campaign, self.conn)
            return [str(self.campaign.events_path)], {}
        if name == "search":
            rebuild_fts(self.conn)
            return [], {}
        if name == "snapshots":
            from .render import write_current_snapshot, write_current_snapshot_json

            return [
                str(write_current_snapshot(self.campaign, self.conn)),
                str(write_current_snapshot_json(self.campaign, self.conn)),
            ], {}
        if name == "cards":
            from .cards import write_cards

            paths = write_cards(
                self.campaign,
                self.conn,
                clean=bool(options.get("clean", True)),
                index_view=str(options.get("index_view", "player")),
            )
            return [str(path) for path in paths], {"count": len(paths)}
        if name == "memory":
            from .memory import rebuild_memory_summaries

            result = rebuild_memory_summaries(self.campaign, self.conn)
            return [str(result.report_path)], {"summaries": result.total, "by_kind": result.by_kind}
        if name == "reports":
            from .audit import write_audit_report

            return [str(write_audit_report(self.campaign, self.conn, options.get("report_path")))], {}
        if name == "package_lock":
            from .packages.lock import write_package_lock_from_meta

            path = write_package_lock_from_meta(self.campaign, self.conn)
            if path is None:
                raise ValueError("package lock metadata is missing from SQLite meta")
            return [str(path)], {}
        raise ValueError(f"unknown projection: {name}")

    def _mark_refreshing(self, name: str, *, turn_id: str | None) -> None:
        if not projection_tables_exist(self.conn):
            return
        self.conn.execute(
            """
            insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'refreshing', ?, null)
            on conflict(name) do update set
              version=excluded.version,
              last_turn_id=excluded.last_turn_id,
              status='refreshing',
              updated_at=excluded.updated_at,
              last_error=null
            """,
            (name, PROJECTION_VERSIONS[name], turn_id, utc_now()),
        )
        self.conn.commit()

    def _state_for(self, name: str) -> dict[str, Any]:
        if not projection_tables_exist(self.conn):
            return {}
        row = self.conn.execute("select * from projection_state where name=?", (name,)).fetchone()
        return dict(row) if row else {}

    def _names_with_status(self, statuses: set[str]) -> set[str]:
        rows = self.conn.execute("select name, version, status from projection_state").fetchall()
        return {str(row["name"]) for row in rows if projection_effective_status(row) in statuses}

    def _build_report(
        self,
        *,
        profile: str,
        requested: tuple[str, ...],
        skipped: tuple[str, ...],
        items: tuple[ProjectionItemReport, ...],
        outbox_errors: tuple[str, ...],
        outbox_artifacts: tuple[str, ...],
        outbox_refreshed: tuple[str, ...],
        started_at: str,
        finished_at: str,
        duration_ms: float,
    ) -> ProjectionReport:
        states = self._all_states()
        requested_set = set(requested)
        global_dirty = tuple(sorted(name for name, status in states.items() if status in {"dirty", "refreshing"}))
        global_failed = tuple(sorted(name for name, status in states.items() if status == "failed"))
        global_clean = tuple(sorted(name for name, status in states.items() if status == "clean"))
        global_stale = tuple(sorted(name for name, status in states.items() if status == "stale"))
        item_failed = {item.name for item in items if item.status == "failed"}
        requested_failed = tuple(sorted((set(global_failed) | item_failed) & requested_set))
        requested_dirty = tuple(sorted(set(global_dirty) & requested_set))
        requested_clean = tuple(sorted(set(global_clean) & requested_set))
        requested_stale = tuple(sorted(set(global_stale) & requested_set))
        errors = list(outbox_errors)
        errors.extend(f"{item.name}: {item.error}" for item in items if item.error)
        artifacts = list(outbox_artifacts)
        for item in items:
            artifacts.extend(item.artifacts)
        refreshed = tuple(dict.fromkeys((*outbox_refreshed, *(item.name for item in items if item.status == "clean"))))
        return ProjectionReport(
            profile=profile,
            requested=requested,
            dirty=requested_dirty,
            refreshed=refreshed,
            clean=requested_clean,
            failed=requested_failed,
            requested_dirty=requested_dirty,
            requested_failed=requested_failed,
            requested_clean=requested_clean,
            requested_stale=requested_stale,
            global_dirty=global_dirty,
            global_failed=global_failed,
            global_clean=global_clean,
            global_stale=global_stale,
            skipped=skipped,
            artifacts=tuple(artifacts),
            errors=tuple(errors),
            items=items,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    def _all_states(self) -> dict[str, str]:
        if not projection_tables_exist(self.conn):
            return {}
        rows = self.conn.execute("select name, version, status from projection_state").fetchall()
        return {str(row["name"]): projection_effective_status(row) for row in rows}
