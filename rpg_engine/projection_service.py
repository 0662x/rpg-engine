from __future__ import annotations

import hashlib
import errno
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic, perf_counter, sleep
from typing import Any, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback retains process-local serialization.
    fcntl = None

from .campaign import Campaign
from .db import rebuild_fts, utc_now
from .projections import (
    PROJECTION_STATE_SCHEMA_COLUMNS,
    PROJECTION_VERSIONS,
    STORED_PROJECTION_STATUSES,
    _inspect_outbox_health,
    _outbox_issue_message,
    current_turn_id,
    ensure_projection_rows,
    mark_projection_clean_if_unchanged,
    mark_projection_failed_if_unchanged,
    next_projection_generation,
    process_outbox,
    projection_effective_status,
    projection_state_table_exists,
    rewrite_events_jsonl,
)


REFRESHABLE_STATUSES = {"dirty", "failed", "refreshing", "stale"}
COMMIT_POLICIES = {"service_managed", "caller_committed_required"}
REFRESH_LOCK_TIMEOUT_SECONDS = 30.0
REFRESH_LOCK_POLL_SECONDS = 0.05
_REFRESH_LOCKS: dict[str, threading.RLock] = {}
_REFRESH_LOCKS_GUARD = threading.Lock()


@contextmanager
def _projection_refresh_lock(campaign: Campaign, name: str) -> Any:
    key = f"{campaign.database_path.resolve()}::{name}"
    with _REFRESH_LOCKS_GUARD:
        local_lock = _REFRESH_LOCKS.setdefault(key, threading.RLock())
    local_acquired = local_lock.acquire(timeout=REFRESH_LOCK_TIMEOUT_SECONDS)
    if not local_acquired:
        raise TimeoutError(f"projection publication lock timed out: {name}")
    try:
        if fcntl is None:
            yield
            return
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        lock_path = Path(tempfile.gettempdir()) / f"rpg-engine-projection-{digest}.lock"
        with lock_path.open("a+b") as handle:
            deadline = monotonic() + REFRESH_LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if monotonic() >= deadline:
                        raise TimeoutError(
                            f"projection publication lock timed out: {name}"
                        ) from exc
                    sleep(REFRESH_LOCK_POLL_SECONDS)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        local_lock.release()


def _format_outbox_report_row(row: dict[str, Any], *, markdown: bool = False) -> str:
    values = {
        "status": _report_value(row.get("status")),
        "topic": _report_value(row.get("topic")),
        "attempts": _report_value(row.get("attempts")),
        "created_at": _report_value(row.get("created_at")),
        "processed_at": _report_value(row.get("processed_at")),
        "last_error": _report_value(row.get("last_error")),
    }
    if markdown:
        detail = " ".join(f"{key}=`{value}`" for key, value in values.items())
        return f"- `{_report_value(row.get('id'))}`: {detail}"
    detail = " ".join(f"{key}={value}" for key, value in values.items())
    return f"outbox: {_report_value(row.get('id'))} {detail}"


def _report_value(value: Any) -> str:
    if value is None:
        return "-"
    text = " ".join(str(value).splitlines()).strip()
    return text or "-"


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
    outbox_status: str = "clean"
    outbox_counts: dict[str, int] = field(default_factory=dict)
    outbox_non_done: tuple[dict[str, Any], ...] = ()
    outbox_errors: tuple[str, ...] = ()
    items: tuple[ProjectionItemReport, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float | None = None

    @property
    def ok(self) -> bool:
        return not self.requested_failed and not self.errors and self.outbox_status == "clean"

    @property
    def status(self) -> str:
        if self.requested_failed or self.errors or self.outbox_status in {"failed", "malformed", "missing"}:
            return "failed" if not self.refreshed else "partial_failure"
        if self.requested_stale:
            return "stale"
        if self.requested_dirty:
            return "dirty"
        if self.outbox_status == "pending":
            return "outbox_pending"
        return "clean"

    @property
    def global_status(self) -> str:
        if self.global_failed or self.errors or self.outbox_status in {"failed", "malformed", "missing"}:
            return "failed"
        if self.global_stale:
            return "stale"
        if self.global_dirty:
            return "dirty"
        if self.outbox_status == "pending":
            return "outbox_pending"
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
            "outbox_status": self.outbox_status,
            "outbox_counts": dict(self.outbox_counts),
            "outbox_non_done": [dict(row) for row in self.outbox_non_done],
            "outbox_errors": list(self.outbox_errors),
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
        lines.append(f"- outbox_status: `{self.outbox_status}`")
        if self.skipped:
            lines.append(f"- skipped: `{', '.join(self.skipped)}`")
        if self.errors:
            lines.extend(["", "## Errors", ""])
            lines.extend(f"- {error}" for error in self.errors)
        if self.outbox_counts or self.outbox_non_done:
            lines.extend(["", "## Outbox", ""])
            for status, count in self.outbox_counts.items():
                lines.append(f"- count `{status}`: `{count}`")
            for row in self.outbox_non_done:
                lines.append(_format_outbox_report_row(row, markdown=True))
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
        projection_state_errors = self._projection_state_errors()
        if not projection_state_errors and projection_state_table_exists(self.conn):
            ensure_projection_rows(self.conn, turn_id=current_turn_id(self.conn))
            self.conn.commit()

        outbox_errors: list[str] = []
        outbox_artifacts: list[str] = []
        outbox_refreshed: list[str] = []
        original_requested = tuple(names) if names is not None else tuple(PROJECTION_VERSIONS)
        if projection_state_errors:
            requested = list(original_requested)
            skipped = []
            items: tuple[ProjectionItemReport, ...] = ()
        elif include_outbox and (names is None or "events_jsonl" in original_requested):
            outbox = _inspect_outbox_health(self.conn)
            if outbox["status"] in {"missing", "malformed"}:
                outbox_errors.extend(str(error) for error in outbox.get("errors", ()))
            else:
                try:
                    with _projection_refresh_lock(self.campaign, "events_jsonl"):
                        outbox_result = process_outbox(self.campaign, self.conn)
                    outbox_errors.extend(outbox_result.errors)
                    outbox_artifacts.extend(outbox_result.artifacts)
                    if outbox_result.refreshed:
                        outbox_refreshed.append("events_jsonl")
                except Exception as exc:
                    if self.conn.in_transaction:
                        self.conn.rollback()
                    outbox_errors.append(f"events_jsonl outbox: {exc}")

            requested = list(original_requested)
            skipped: list[str] = []
            if dirty_only and projection_state_table_exists(self.conn):
                refreshable = self._names_with_status(REFRESHABLE_STATUSES)
                requested = [name for name in requested if name in refreshable]
                skipped = [name for name in original_requested if name not in requested]

            item_options = options or {}
            items = tuple(self._refresh_one(name, options=item_options.get(name, {})) for name in requested)
        else:
            requested = list(original_requested)
            skipped = []
            if dirty_only and projection_state_table_exists(self.conn):
                refreshable = self._names_with_status(REFRESHABLE_STATUSES)
                requested = [name for name in requested if name in refreshable]
                skipped = [name for name in original_requested if name not in requested]

            item_options = options or {}
            items = tuple(self._refresh_one(name, options=item_options.get(name, {})) for name in requested)
        return self._build_report(
            profile=profile,
            requested=original_requested,
            skipped=tuple(skipped),
            items=items,
            outbox_errors=tuple(outbox_errors),
            outbox_artifacts=tuple(outbox_artifacts),
            outbox_refreshed=tuple(dict.fromkeys(outbox_refreshed)),
            projection_state_errors=tuple(projection_state_errors),
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

        started = perf_counter()
        try:
            with _projection_refresh_lock(self.campaign, name):
                turn_id = current_turn_id(self.conn)
                refresh_generation = self._mark_refreshing(name, turn_id=turn_id)
                owned_generation = refresh_generation
                try:
                    artifacts, metadata = self._write_projection(name, options=options)
                    clean_generation = mark_projection_clean_if_unchanged(
                        self.conn,
                        name,
                        turn_id=turn_id,
                        expected_generation=refresh_generation,
                    )
                    if clean_generation is None:
                        self.conn.commit()
                        current = self._state_for(name)
                        status = projection_effective_status(current) if current else "stale"
                        if status == "clean":
                            status = "stale"
                        return ProjectionItemReport(
                            name=name,
                            status=status,
                            previous_status=previous.get("status"),
                            artifacts=tuple(artifacts),
                            error="projection generation changed during refresh",
                            turn_id=turn_id,
                            version=PROJECTION_VERSIONS[name],
                            duration_ms=(perf_counter() - started) * 1000,
                            metadata=metadata,
                        )
                    owned_generation = clean_generation
                    self.conn.commit()
                    if name == "memory":
                        from .memory import memory_projection_health

                        effective_status = str(memory_projection_health(self.conn)["status"])
                        if effective_status != "clean":
                            raise RuntimeError(
                                f"memory projection remains {effective_status} after refresh"
                            )
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
                    changed = not mark_projection_failed_if_unchanged(
                        self.conn,
                        name,
                        error=message,
                        expected_generation=owned_generation,
                    )
                    self.conn.commit()
                    if changed:
                        current = self._state_for(name)
                        status = projection_effective_status(current) if current else "stale"
                        if status == "clean":
                            status = "stale"
                        return ProjectionItemReport(
                            name=name,
                            status=status,
                            previous_status=previous.get("status"),
                            error=message,
                            turn_id=turn_id,
                            version=PROJECTION_VERSIONS[name],
                            duration_ms=(perf_counter() - started) * 1000,
                        )
                    return ProjectionItemReport(
                        name=name,
                        status="failed",
                        previous_status=previous.get("status"),
                        error=message,
                        turn_id=turn_id,
                        version=PROJECTION_VERSIONS[name],
                        duration_ms=(perf_counter() - started) * 1000,
                    )
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            try:
                failed_turn_id = current_turn_id(self.conn)
            except (KeyError, TypeError, ValueError, sqlite3.Error):
                failed_turn_id = None
            return ProjectionItemReport(
                name=name,
                status="failed",
                previous_status=previous.get("status"),
                error=str(exc),
                turn_id=failed_turn_id,
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

            result = rebuild_memory_summaries(
                self.campaign,
                self.conn,
                manage_projection_state=False,
            )
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

    def _mark_refreshing(
        self,
        name: str,
        *,
        turn_id: str | None,
    ) -> tuple[str, str]:
        if not projection_state_table_exists(self.conn):
            raise RuntimeError("projection_state is unavailable")
        generation = next_projection_generation(self.conn, name)
        self.conn.execute(
            """
            insert into main.projection_state(name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'refreshing', ?, null)
            on conflict(name) do update set
              version=excluded.version,
              last_turn_id=excluded.last_turn_id,
              status='refreshing',
              updated_at=excluded.updated_at,
              last_error=null
            """,
            (name, PROJECTION_VERSIONS[name], turn_id, generation),
        )
        self.conn.commit()
        return "refreshing", generation

    def _state_for(self, name: str) -> dict[str, Any]:
        if not projection_state_table_exists(self.conn):
            return {}
        row = self.conn.execute(
            "select * from main.projection_state where name = ? collate binary",
            (name,),
        ).fetchone()
        return dict(row) if row else {}

    def _names_with_status(self, statuses: set[str]) -> set[str]:
        rows = self.conn.execute("select name, version, status from main.projection_state").fetchall()
        names = {str(row["name"]) for row in rows if projection_effective_status(row) in statuses}
        if "stale" in statuses:
            from .memory import memory_projection_health

            if memory_projection_health(self.conn)["status"] == "stale":
                names.add("memory")
        return names

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
        projection_state_errors: tuple[str, ...],
        started_at: str,
        finished_at: str,
        duration_ms: float,
    ) -> ProjectionReport:
        states = self._all_states()
        items = tuple(
            replace(
                item,
                status=states.get(item.name, "stale"),
                error=item.error or "projection state changed after refresh",
            )
            if item.status == "clean" and states.get(item.name) != "clean"
            else item
            for item in items
        )
        outbox = _inspect_outbox_health(self.conn)
        outbox_non_done = tuple(dict(row) for row in outbox.get("non_done", ()))
        outbox_errors_reported = tuple(str(error) for error in outbox.get("errors", ()))
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
        errors = list(projection_state_errors)
        errors.extend(outbox_errors)
        errors.extend(outbox_errors_reported)
        errors.extend(_outbox_issue_message(row) for row in outbox_non_done if row.get("status") == "failed")
        errors.extend(f"{item.name}: {item.error}" for item in items if item.error)
        artifacts = list(outbox_artifacts)
        for item in items:
            artifacts.extend(item.artifacts)
        refreshed = tuple(
            dict.fromkeys(
                (
                    *outbox_refreshed,
                    *(
                        item.name
                        for item in items
                        if (
                            item.status == "clean"
                            and not item.error
                            and states.get(item.name) == "clean"
                        )
                    ),
                )
            )
        )
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
            outbox_status=str(outbox.get("status") or "clean"),
            outbox_counts={str(status): int(count) for status, count in dict(outbox.get("counts", {})).items()},
            outbox_non_done=outbox_non_done,
            outbox_errors=outbox_errors_reported,
            items=items,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    def _all_states(self) -> dict[str, str]:
        if not self._projection_state_table_exists():
            return {}
        columns = self._projection_state_columns()
        if set(PROJECTION_STATE_SCHEMA_COLUMNS) - columns:
            return {}
        rows = self.conn.execute("select name, version, status from main.projection_state").fetchall()
        states: dict[str, str] = {}
        for row in rows:
            states[str(row["name"])] = projection_effective_status(row)
        if "memory" in states:
            from .memory import memory_projection_health

            states["memory"] = str(memory_projection_health(self.conn)["status"])
        return states

    def _projection_state_errors(self) -> list[str]:
        if not self._projection_state_table_exists():
            return ["projection_state: missing"]
        columns = self._projection_state_columns()
        errors: list[str] = []
        missing_columns = sorted(set(PROJECTION_STATE_SCHEMA_COLUMNS) - columns)
        if missing_columns:
            errors.append(f"projection_state schema: missing columns {', '.join(missing_columns)}")
        else:
            from .memory import projection_state_readable

            if not projection_state_readable(self.conn):
                errors.append("projection_state schema: incompatible canonical identity or extension")
        if "name" in columns:
            duplicate_names = [
                str(row["name"])
                for row in self.conn.execute(
                    """
                    select name
                    from main.projection_state
                    group by name
                    having count(*) > 1
                    order by name
                    """
                ).fetchall()
                if row["name"] is not None
            ]
            if duplicate_names:
                errors.append(f"projection_state: duplicate names {', '.join(duplicate_names)}")
        if not missing_columns:
            for row in self.conn.execute(
                "select name, status from main.projection_state order by name"
            ).fetchall():
                name = "" if row["name"] is None else str(row["name"])
                canonical_name = name.casefold()
                if canonical_name in PROJECTION_VERSIONS and name != canonical_name:
                    errors.append(
                        f"projection_state.{name}: non-canonical projection alias"
                    )
                elif name not in PROJECTION_VERSIONS:
                    errors.append(f"projection_state.{name}: unknown projection name")
                raw_status = None if row["status"] is None else str(row["status"])
                if raw_status not in STORED_PROJECTION_STATUSES:
                    errors.append(f"projection_state.{row['name']}: invalid status {raw_status}")
        return errors

    def _projection_state_table_exists(self) -> bool:
        row = self.conn.execute(
            "select 1 from main.sqlite_master "
            "where type='table' and name='projection_state' collate nocase"
        ).fetchone()
        return bool(row)

    def _projection_state_columns(self) -> set[str]:
        return {
            str(row[1])
            for row in self.conn.execute(
                'pragma main.table_info("projection_state")'
            ).fetchall()
        }
