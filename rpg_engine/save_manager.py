from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid
from copy import deepcopy
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    msvcrt = None

from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS
from .atomic_io import write_text_atomic
from .campaign import load_campaign
from .commit_service import reconcile_confirmed_turn
from .db import connect, utc_now
from .game_session import clean, hash_identity
from .intent_router import make_intent_ai_config, make_intent_request_meta
from .redaction import redact_hidden_entity_refs
from .runtime import GMRuntime, intent_ai_config_kwargs, intent_request_meta_kwargs
from .save_service import init_v1_save, inspect_v1_save, normalize_content_paths_for_save, validate_save_target_outside_source
from .validation_issues import issues_from_messages
from .validation_pipeline import stable_delta_digest
from .visibility import ensure_visibility_sql_functions, is_player_hidden_visibility, normalize_visibility_label
from .write_guard import find_idempotent_turn


REGISTRY_SCHEMA_VERSION = "1"
DEFAULT_REGISTRY_RELATIVE = ".aigm/save-registry.json"
DEFAULT_PENDING_ACTION_RELATIVE = ".aigm/pending-player-action.json"
DEFAULT_PENDING_CLARIFICATION_RELATIVE = ".aigm/pending-player-clarification.json"
DEFAULT_PENDING_REVISION_RELATIVE = ".aigm/pending-player-lifecycle-revision.json"
DEFAULT_CONFIRMATION_RECEIPT_RELATIVE = ".aigm/last-confirmed-player-action.json"
DEFAULT_CONFIRMATION_HISTORY_RELATIVE = ".aigm/confirmed-player-action-history.json"
DEFAULT_CONFIRMATION_LOCK_RELATIVE = ".aigm/pending-player-action.lock"
DEFAULT_PENDING_ACTION_TTL_SECONDS = 1800
MAX_PENDING_STATE_BYTES = 1024 * 1024
MAX_REGISTRY_STATE_BYTES = 1024 * 1024
MAX_PENDING_JSON_DEPTH = 64
MAX_PENDING_CONTAINER_ITEMS = 4096
MAX_PENDING_JSON_NODES = 20000
MAX_PENDING_STRING_LENGTH = 262144
MAX_CONFIRMATION_RECEIPT_BYTES = 4096
MAX_CONFIRMATION_HISTORY_BYTES = 32768
MAX_CONFIRMATION_HISTORY_ENTRIES = 8
CONFIRMATION_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "save_id",
        "save_path",
        "confirmation_session_hash",
        "command_id",
        "command_hash",
        "delta_digest",
        "proposal_digest",
        "platform_hash",
        "session_key_hash",
        "actor_id_hash",
        "turn_id",
        "event_count",
        "write_status",
        "projection_status",
        "receipt_digest",
    }
)
CONFIRMATION_RECEIPT_META_KEY = "confirmation_replay_receipt_digest"
CONFIRMATION_RECEIPT_HISTORY_META_PREFIX = "confirmation_replay_receipt_digest:"
CONFIRMATION_HISTORY_ORDER_META_KEY = "confirmation_replay_history_order_digest"
CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY = "confirmation_replay_history_order_digest:prepared"
LEGACY_CONFIRMATION_HISTORY_ORDER_META_PREFIX = "confirmation_replay_history_order_digest:"
CONFIRMATION_CLAIM_META_KEY = "confirmation_pending_claim_digest"
DEFAULT_SAVES_DIR = "saves"
INTERNAL_ONBOARDING_TERMS = ("delta", "commit", "SQLite", "save_dir", "campaign.yaml", "game.sqlite")
_CONFIRMATION_LOCK_STATE = threading.local()
_WORKSPACE_LOCK_STATE = threading.local()
_LOW_LEVEL_PUBLICATION_SIGNING_KEY = os.urandom(32)


class SaveManagerError(ValueError):
    """Raised for player-entry and save-registry validation failures."""


class SavePublicationConflict(SaveManagerError):
    """Raised when a frozen Save binding changes before pending publication."""


class RegistryPublicationUncertain(SaveManagerError):
    """Raised when registry replacement succeeded but durability could not be confirmed."""


class PendingCompareConflict(RuntimeError):
    """Internal signal that a two-phase pending publication lost its CAS."""

    def __init__(
        self,
        kind: str,
        pending: dict[str, Any] | None,
        *,
        same_identity: bool,
        save_selection_changed: bool = False,
        selected_save: dict[str, Any] | None = None,
    ) -> None:
        self.kind = kind
        self.pending = pending
        self.same_identity = same_identity
        self.save_selection_changed = save_selection_changed
        self.selected_save = selected_save
        super().__init__("pending player session changed before publication")


class PendingLifecycleTerminal(RuntimeError):
    """Internal signal that the compared pending reached a terminal owner state."""

    def __init__(self, kind: str, pending: dict[str, Any], *, state: str) -> None:
        self.kind = kind
        self.pending = pending
        self.state = state
        super().__init__(f"pending player session became {state} before publication")


class SaveManager:
    def __init__(
        self,
        root: str | Path,
        *,
        registry_path: str | Path | None = None,
        default_campaign: str | None = None,
        default_starter_save: str | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.registry_path = resolve_registry_path(self.root, registry_path)
        self.default_campaign = normalize_optional_relative(default_campaign, "default_campaign")
        self.default_starter_save = normalize_optional_relative(default_starter_save, "default_starter_save")

    def inspect_workspace(self) -> dict[str, Any]:
        registry = self.read_registry()
        return {
            "ok": True,
            "root": str(self.root),
            "registry_path": str(self.registry_path),
            "registry_exists": self.registry_path.exists(),
            "campaigns_count": len(registry.get("campaigns", [])),
            "saves_count": len(registry.get("saves", [])),
            "active_save_id": registry.get("active_save_id"),
            "errors": [],
        }

    def list_campaigns(self, *, refresh: bool = False) -> dict[str, Any]:
        with self.registry_snapshot(write=refresh) as registry:
            campaigns = [dict(item) for item in registry.get("campaigns", []) if isinstance(item, dict)]
            if refresh:
                path_errors = registry_record_path_errors(self.root, campaigns, "campaign")
                if path_errors:
                    return {
                        "ok": False,
                        "campaigns": campaigns,
                        "errors": path_errors,
                        "error_details": issues_from_messages(path_errors, default_code="SAVE_MANAGER_ERROR"),
                    }
                for record in campaigns:
                    try:
                        campaign = load_campaign(self.resolve_relative(str(record.get("path", "")), "campaign"))
                        record.update(
                            {
                                "id": campaign.campaign_id,
                                "name": campaign.name,
                                "status": "ok",
                                "last_validated_at": utc_now(),
                            }
                        )
                    except Exception as exc:
                        record["status"] = "error"
                        record["errors"] = [str(exc)]
                registry["campaigns"] = campaigns
            return {"ok": True, "campaigns": campaigns, "errors": []}

    def register_campaign(self, campaign: str, starter_save: str | None = None) -> dict[str, Any]:
        campaign_path = normalize_required_relative(campaign, "campaign")
        starter_path = normalize_optional_relative(starter_save, "starter_save")
        loaded = load_campaign(self.resolve_relative(campaign_path, "campaign"))
        record = {
            "id": loaded.campaign_id,
            "name": loaded.name,
            "path": campaign_path,
            "starter_save_path": starter_path,
            "last_validated_at": utc_now(),
            "status": "ok",
        }
        with self.registry_snapshot(write=True) as registry:
            campaigns = [dict(item) for item in registry.get("campaigns", []) if isinstance(item, dict)]
            campaigns = [item for item in campaigns if item.get("id") != loaded.campaign_id]
            campaigns.append(record)
            registry["campaigns"] = sorted(campaigns, key=lambda item: str(item.get("id", "")))
        return {"ok": True, "campaign": record, "errors": []}

    def list_saves(
        self,
        *,
        campaign_id: str | None = None,
        include_archived: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        with self.registry_snapshot(write=refresh) as registry:
            saves = [dict(item) for item in registry.get("saves", []) if isinstance(item, dict)]
            filtered = [
                item
                for item in saves
                if (include_archived or not bool(item.get("archived")))
                and (campaign_id is None or str(item.get("campaign_id", "")) == campaign_id)
            ]
            if refresh:
                path_errors = registry_record_path_errors(self.root, saves, "save")
                if path_errors:
                    return {
                        "ok": False,
                        "active_save_id": registry.get("active_save_id"),
                        "saves": [self.scrub_cached_save_record(record) for record in filtered],
                        "errors": path_errors,
                        "error_details": issues_from_messages(path_errors, default_code="SAVE_MANAGER_ERROR"),
                    }
                refreshed: list[dict[str, Any]] = []
                for record in saves:
                    if any(record.get("id") == item.get("id") for item in filtered):
                        refreshed.append(self.refresh_save_record(record))
                    else:
                        refreshed.append(record)
                registry["saves"] = refreshed
                filtered_ids = {str(item.get("id")) for item in filtered}
                filtered = [dict(item) for item in refreshed if str(item.get("id")) in filtered_ids]
            filtered = [self.scrub_cached_save_record(record) for record in filtered]
            return {
                "ok": True,
                "active_save_id": registry.get("active_save_id"),
                "saves": filtered,
                "errors": [],
            }

    def current_save(self, *, refresh: bool = False) -> dict[str, Any]:
        with self.registry_snapshot(write=refresh) as registry:
            active_save_id = registry.get("active_save_id")
            if not active_save_id:
                return {
                    "ok": False,
                    "active_save_id": None,
                    "save": None,
                    "errors": ["no active save is configured"],
                    "error_details": issues_from_messages(
                        ["no active save is configured"],
                        default_code="SAVE_MANAGER_ERROR",
                    ),
                }
            record = find_record(registry.get("saves", []), str(active_save_id))
            if record is None:
                message = f"active save not found: {active_save_id}"
                return {
                    "ok": False,
                    "active_save_id": active_save_id,
                    "save": None,
                    "errors": [message],
                    "error_details": issues_from_messages([message], default_code="SAVE_MANAGER_ERROR"),
                }
            path_errors = registry_record_path_errors(self.root, registry.get("saves", []), "save")
            if path_errors:
                return {
                    "ok": False,
                    "active_save_id": active_save_id,
                    "save": None,
                    "errors": path_errors,
                    "error_details": issues_from_messages(path_errors, default_code="SAVE_MANAGER_ERROR"),
                }
            if refresh:
                record = self.refresh_save_record(dict(record))
                registry["saves"] = replace_record(registry.get("saves", []), record)
            return {
                "ok": True,
                "active_save_id": active_save_id,
                "save": self.scrub_cached_save_record(dict(record)),
                "current_save_authority": current_save_authority(refresh=refresh),
                "errors": [],
            }

    def switch_save(self, save_id: str, *, refresh: bool = True) -> dict[str, Any]:
        def switch_with_pending_owner() -> dict[str, Any]:
            kind, pending, _ = self.read_canonical_pending_locked(migrate=False)
            if pending is not None:
                orphan_state = self.pending_orphan_classification(kind, pending)
                if orphan_state:
                    raise SaveManagerError("pending player session has unresolved save evidence")
            lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
            with registry_lock(lock_path, root=self.root):
                registry = self.read_registry()
                record = find_record(registry.get("saves", []), save_id)
                if record is None:
                    raise SaveManagerError(f"save not found: {save_id}")
                if bool(record.get("archived")):
                    raise SaveManagerError(f"save is archived: {save_id}")
                record = dict(record)
                path_errors = registry_record_path_errors(self.root, registry.get("saves", []), "save")
                if path_errors:
                    raise SaveManagerError("; ".join(path_errors))
                if refresh:
                    record = self.refresh_save_record(record)
                    registry["saves"] = replace_record(registry.get("saves", []), record)
                active_selection_changed = registry.get("active_save_id") != save_id
                if active_selection_changed:
                    self.bump_pending_lifecycle_revision()
                registry["active_save_id"] = save_id
                self.write_registry_unlocked(registry)
            result: dict[str, Any] = {"ok": True, "active_save_id": save_id, "save": record, "errors": []}
            if pending is not None:
                result["lifecycle"] = pending_lifecycle_projection(
                    kind,
                    pending,
                    state="preserved",
                    include_pending_id=False,
                )
            return result

        if confirmation_lock_held_by_current_thread(self.confirmation_lock_path()):
            return switch_with_pending_owner()
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            return switch_with_pending_owner()

    def create_save(
        self,
        *,
        campaign: str | None = None,
        label: str | None = None,
        starter_save: str | None = None,
        kind: str = "normal",
        activate: bool = True,
    ) -> dict[str, Any]:
        campaign_path = self.resolve_campaign_path(campaign)
        campaign_obj = load_campaign(self.resolve_relative(campaign_path, "campaign"))
        starter_path = self.resolve_starter_path(campaign_obj.campaign_id, starter_save)
        save_id = make_save_id()
        target_relative = make_save_target_relative(campaign_obj.campaign_id, save_id)
        target = self.resolve_relative(target_relative, "save target")
        validate_save_target_outside_source(campaign_obj.root, target)
        ensure_empty_target(target)
        target.mkdir()
        created_target_identity = directory_entry_identity(target)
        try:
            source = "save_init"
            if starter_path:
                starter = self.resolve_relative(starter_path, "starter_save")
                if not starter.exists():
                    raise SaveManagerError(f"starter save does not exist: {starter_path}")
                shutil.copytree(starter, target, dirs_exist_ok=True)
                rewrite_save_manifests(target, campaign_obj)
                source = "starter_copy"
            else:
                init_v1_save(campaign_obj.root, target)

            record = self.build_save_record(
                save_id=save_id,
                campaign_path=campaign_path,
                save_path=target_relative,
                label=label or "",
                kind=kind,
                source=source,
            )
            if not record.get("label"):
                record["label"] = self.default_save_label(record)
            with self.registry_snapshot(write=True) as registry:
                registry["campaigns"] = upsert_campaign_record(
                    registry.get("campaigns", []),
                    campaign_obj,
                    campaign_path,
                    starter_path,
                )
                registry["saves"] = replace_record(registry.get("saves", []), record)
                active_save_id = registry.get("active_save_id")
        except RegistryPublicationUncertain:
            raise
        except Exception:
            remove_created_directory_if_unchanged(
                self.root,
                target,
                created_target_identity,
            )
            raise
        result = {
            "ok": not save_blocks_player_entry(record),
            "mode": "created",
            "active_save_id": active_save_id,
            "save": record,
            "errors": [] if not save_blocks_player_entry(record) else list(record.get("errors", [])),
        }
        if activate:
            switched = self.switch_save(save_id, refresh=False)
            result["active_save_id"] = switched["active_save_id"]
            if "lifecycle" in switched:
                result["lifecycle"] = switched["lifecycle"]
        return result

    def duplicate_save(self, save_id: str, *, label: str | None = None, activate: bool = True) -> dict[str, Any]:
        registry = self.read_registry()
        source_record = find_record(registry.get("saves", []), save_id)
        if source_record is None:
            raise SaveManagerError(f"save not found: {save_id}")
        source_path = self.resolve_relative(str(source_record.get("path", "")), "save")
        new_save_id = make_save_id()
        target_relative = make_save_target_relative(str(source_record.get("campaign_id", "campaign")), new_save_id)
        target_path = self.resolve_relative(target_relative, "save target")
        ensure_empty_target(target_path)
        target_path.mkdir()
        created_target_identity = directory_entry_identity(target_path)
        try:
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            record = self.build_save_record(
                save_id=new_save_id,
                campaign_path=str(source_record.get("campaign_path", "")),
                save_path=target_relative,
                label=label or f"{source_record.get('label', '存档')} · 副本",
                kind=str(source_record.get("kind", "normal")),
                source="duplicate",
            )
            with self.registry_snapshot(write=True) as latest_registry:
                latest_registry["saves"] = replace_record(latest_registry.get("saves", []), record)
                active_save_id = latest_registry.get("active_save_id")
        except RegistryPublicationUncertain:
            raise
        except Exception:
            remove_created_directory_if_unchanged(
                self.root,
                target_path,
                created_target_identity,
            )
            raise
        result = {
            "ok": not save_blocks_player_entry(record),
            "mode": "created",
            "active_save_id": active_save_id,
            "save": record,
            "errors": [] if not save_blocks_player_entry(record) else list(record.get("errors", [])),
        }
        if activate:
            switched = self.switch_save(new_save_id, refresh=False)
            result["active_save_id"] = switched["active_save_id"]
            if "lifecycle" in switched:
                result["lifecycle"] = switched["lifecycle"]
        return result

    def start_or_continue(
        self,
        *,
        campaign: str | None = None,
        user_text: str | None = None,
        create_if_missing: bool = True,
        starter_save: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        campaign_path = normalize_optional_relative(campaign, "campaign")
        starter_path = normalize_optional_relative(starter_save, "starter_save")
        current = self.current_save(refresh=True)
        mode = "continued"
        if not current["ok"]:
            if current.get("active_save_id"):
                return {
                    "ok": False,
                    "mode": "blocked",
                    "save": None,
                    "scene": None,
                    "onboarding_text": "",
                    "errors": current["errors"],
                    "error_details": current.get("error_details", []),
                }
            if not create_if_missing:
                return {
                    "ok": False,
                    "mode": "needs_save_choice",
                    "save": None,
                    "scene": None,
                    "onboarding_text": "",
                    "errors": current["errors"],
                    "error_details": current.get("error_details", []),
                }
            created = self.create_save(
                campaign=campaign_path,
                label=label,
                starter_save=starter_path,
                activate=True,
            )
            current = {"ok": created["ok"], "save": created["save"], "errors": created.get("errors", [])}
            mode = "created"
        save = current["save"]
        if not save:
            return {
                "ok": False,
                "mode": "blocked",
                "save": None,
                "scene": None,
                "onboarding_text": "",
                "errors": ["no save available"],
                "error_details": issues_from_messages(["no save available"], default_code="SAVE_MANAGER_ERROR"),
            }
        if save_blocks_player_entry(save):
            message = f"active save is not healthy: {save.get('label') or save.get('id')}"
            return {
                "ok": False,
                "mode": "blocked",
                "save": save,
                "scene": None,
                "onboarding_text": "",
                "errors": [message, *list(save.get("errors", []))],
                "error_details": issues_from_messages([message], default_code="SAVE_MANAGER_ERROR"),
            }

        scene = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save")).query("scene", view="player").to_dict()
        onboarding_text = render_onboarding_text(save, scene, mode=mode, user_text=user_text)
        self.mark_played(str(save["id"]))
        return {
            "ok": True,
            "mode": mode,
            "active_save_id": save["id"],
            "save": save,
            "scene": scene,
            "onboarding_text": onboarding_text,
            "errors": [],
        }

    def resolve_save_path_for_runtime(self, save: str | None = None, *, default_save: str | None = None) -> Path:
        if save:
            return self.resolve_relative(normalize_required_relative(save, "save"), "save")
        current = self.current_save(refresh=True)
        if current["ok"] and current.get("save"):
            record = dict(current["save"])
            if save_blocks_player_entry(record):
                raise SaveManagerError(
                    "; ".join([f"active save is not healthy: {record.get('label') or record.get('id')}", *record.get("errors", [])])
                )
            return self.resolve_relative(str(record["path"]), "save")
        if default_save:
            return self.resolve_relative(normalize_required_relative(default_save, "default_save"), "default_save")
        raise SaveManagerError("save is required because no active or default save is configured")

    def player_query(
        self,
        *,
        kind: str = "scene",
        query_text: str | None = None,
        budget: int | None = None,
    ) -> dict[str, Any]:
        save = self.require_active_save(refresh=True)
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        result = runtime.query(kind, query_text, view="player", budget=budget).to_dict()
        self.mark_played(str(save["id"]))
        return {
            "ok": True,
            "active_save_id": save["id"],
            "kind": result.get("kind", kind),
            "text": result.get("text", ""),
            "saved": False,
            "errors": [],
        }

    def player_turn(
        self,
        *,
        user_text: str,
        save_path: str = "",
        external_intent_candidate: dict[str, Any] | None = None,
        intent_ai: str = "off",
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
        expected_pending_id: str = "",
        clarification_id: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        if not player_identity_inputs_are_valid(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        ):
            return {
                "ok": False,
                "status": "invalid_state",
                "ready_to_confirm": False,
                "session_id": None,
                "pending_clarification_id": None,
                "saved": False,
                "lifecycle": {"state": "invalid_state", "kind": "unknown"},
                "warnings": [],
                "errors": ["platform and session_key must be provided together"],
            }
        try:
            save = self.require_save(refresh=True, save_path=save_path)
        except SaveManagerError as save_error:
            if save_path:
                raise
            with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
                try:
                    _unavailable_kind, unavailable_pending, _ = (
                        self.read_canonical_pending_locked(migrate=False)
                    )
                except SaveManagerError:
                    return pending_conflict_result(
                        save={},
                        kind="unknown",
                        pending=None,
                        same_identity=False,
                        message="pending owner state is unavailable",
                        state="invalid_state",
                    )
                if unavailable_pending is None:
                    raise save_error
                return pending_conflict_result(
                    save={},
                    kind="unknown",
                    pending=None,
                    same_identity=False,
                    message="pending Save binding is unavailable",
                    state="invalid_state",
                )
        require_active_save_match = not bool(save_path)
        expected_token_invalid = not pending_token_is_canonical_or_empty(expected_pending_id)
        correction_token_invalid = not pending_token_is_canonical_or_empty(clarification_id)
        expected_id = expected_pending_id if isinstance(expected_pending_id, str) and not expected_token_invalid else ""
        correction_id = clarification_id if isinstance(clarification_id, str) and not correction_token_invalid else ""
        initial_pending: dict[str, Any] | None = None
        initial_kind = ""
        initial_generation = ""
        initial_revision = 0
        initial_incarnation = ""
        same_identity = False
        explicit_clarification_resolution = False
        candidate_correction_attempt = False
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            if require_active_save_match:
                selected_save = self.selected_active_save()
                if selected_save is None or not exact_save_record_matches(save, selected_save):
                    return pending_conflict_result(
                        save=selected_save or save,
                        kind="unknown",
                        pending=None,
                        same_identity=False,
                        message="active save selection changed before player turn validation",
                    )
            initial_kind, initial_pending, _ = self.read_canonical_pending_locked(migrate=False)
            if initial_pending is not None:
                same_identity = pending_session_identity_matches(
                    initial_pending,
                    platform=platform,
                    session_key=session_key,
                    actor_id=actor_id,
                )
                if not same_identity:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=False,
                        message="pending player session belongs to a different identity",
                    )
                if not pending_matches_save(initial_pending, save):
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=None,
                        same_identity=False,
                        message="pending player session belongs to a different save",
                    )
                binding_state = self.pending_orphan_classification(
                    initial_kind,
                    initial_pending,
                )
                if binding_state:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="pending player session has unresolved save evidence",
                        state="invalid_state",
                    )
                if expected_token_invalid or correction_token_invalid:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="pending compare token is not canonical",
                    )
                initial_revision = self.ensure_pending_lifecycle_revision()
                initial_evidence = self.read_pending_lifecycle_evidence(require_existing=True)
                assert initial_evidence is not None
                initial_incarnation = initial_evidence[0]
                try:
                    with self.frozen_save_publication_registry(
                        save,
                        require_active_save_match=require_active_save_match,
                    ):
                        initial_kind, initial_pending, migrated = (
                            self.read_canonical_pending_locked(
                                migrate=True,
                                live_binding_verified=True,
                            )
                        )
                        assert initial_pending is not None
                        if initial_kind == "action" and self.pending_action_requires_recovery(
                            initial_pending
                        ):
                            return pending_conflict_result(
                                save=save,
                                kind=initial_kind,
                                pending=initial_pending,
                                same_identity=True,
                                message=(
                                    "pending action requires confirmation recovery before "
                                    "another player turn"
                                ),
                                state="invalid_state",
                            )
                        if pending_action_is_expired(initial_pending):
                            self.clear_pending_kind(initial_kind)
                            return pending_terminal_result(
                                save=save,
                                kind=initial_kind,
                                pending=initial_pending,
                                state="expired",
                            )
                except SavePublicationConflict:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="pending Save binding is unavailable",
                        state="invalid_state",
                    )
                current_id = pending_session_id(initial_kind, initial_pending)
                if expected_id and expected_id != current_id:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="expected pending id does not match the current session",
                    )
                if correction_id and (initial_kind != "clarification" or correction_id != current_id):
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="clarification id does not match the current session",
                    )
                if initial_kind == "clarification" and correction_id and expected_id != correction_id:
                    return pending_conflict_result(
                        save=save,
                        kind=initial_kind,
                        pending=initial_pending,
                        same_identity=True,
                        message="clarification compare tokens do not match",
                    )
                if initial_kind == "clarification":
                    original_user_text = str(initial_pending.get("original_user_text") or "")
                    exact_original = user_text == original_user_text
                    equivalent_original = normalize_player_text(user_text) == normalize_player_text(original_user_text)
                    candidate_correction_attempt = exact_original and clarification_correction_is_allowed(
                        initial_pending,
                        expected_pending_id=expected_id,
                        clarification_id=correction_id,
                        external_intent_candidate=external_intent_candidate,
                    )
                    if equivalent_original and (
                        not exact_original
                        or not candidate_correction_attempt
                    ):
                        return pending_clarification_waiting_result(save=save, pending=initial_pending)
                    explicit_clarification_resolution = (
                        expected_id == current_id and correction_id == current_id
                    )
                initial_generation = pending_generation_digest(initial_kind, initial_pending)
                if migrated:
                    initial_generation = pending_generation_digest(initial_kind, initial_pending)
                    initial_evidence = self.read_pending_lifecycle_evidence(require_existing=True)
                    assert initial_evidence is not None
                    initial_incarnation, initial_revision = initial_evidence
            elif expected_pending_id != "" or clarification_id != "":
                requested_kind = "clarification" if correction_id or expected_id.startswith("clarification:") else "action"
                return pending_conflict_result(
                    save=save,
                    kind=requested_kind,
                    pending=None,
                    same_identity=True,
                    message="expected pending session no longer exists",
                    state="not_found",
                )
            else:
                initial_revision = self.ensure_pending_lifecycle_revision()
                initial_evidence = self.read_pending_lifecycle_evidence(require_existing=True)
                assert initial_evidence is not None
                initial_incarnation = initial_evidence[0]
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        intent_kwargs = {
            "intent_ai": intent_ai,
            "intent_backend": intent_backend,
            "intent_model": intent_model,
            "intent_provider": intent_provider,
            "intent_timeout": intent_timeout,
            "intent_base_url": intent_base_url,
            "intent_api_key_env": intent_api_key_env,
            "intent_fallback_backend": intent_fallback_backend,
        }
        if isinstance(user_text, str) and user_text.strip():
            intent_config = make_intent_ai_config(
                intent_ai=intent_ai,
                intent_backend=intent_backend,
                intent_model=intent_model,
                intent_provider=intent_provider,
                intent_timeout=intent_timeout,
                intent_base_url=intent_base_url,
                intent_api_key_env=intent_api_key_env,
                intent_fallback_backend=intent_fallback_backend,
            )
            intent_kwargs = intent_ai_config_kwargs(intent_config)
        request_meta = make_intent_request_meta(
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )
        result = runtime.act(
            user_text,
            view="player",
            **intent_kwargs,
            external_intent_candidate=external_intent_candidate,
            **intent_request_meta_kwargs(request_meta),
        ).to_dict()
        ready = bool(result.get("ready_to_save") and result.get("delta_draft") and result.get("turn_proposal"))
        clarification = extract_result_clarification(result)
        if player_turn_error_preserves_clarification(result):
            ready = False
            clarification = None
        if clarification is not None:
            validate_clarification_payload_privacy(
                clarification,
                session_key=session_key,
                actor_id=actor_id,
            )
        session_id: str | None = None
        lifecycle: dict[str, Any] | None = None
        if ready:
            session_id = f"player_action:{uuid.uuid4().hex}"
            created_at = utc_now()
            pending_session = {
                "schema_version": "1",
                "session_id": session_id,
                "save_id": save["id"],
                "save_path": save["path"],
                "created_at": created_at,
                "expires_at": pending_action_expires_at_from_created(created_at),
                "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
                "user_text": user_text,
                "action": result.get("action"),
                "delta": result.get("delta_draft"),
                "turn_proposal": result.get("turn_proposal"),
                **platform_session_metadata(platform=platform, session_key=session_key, actor_id=actor_id),
            }
            try:
                lifecycle = self.publish_pending_after_compare(
                    kind="action",
                    session=pending_session,
                    initial_kind=initial_kind,
                    initial_pending=initial_pending,
                    initial_generation=initial_generation,
                    initial_revision=initial_revision,
                    initial_incarnation=initial_incarnation,
                    expected_pending_id=expected_id,
                    clarification_id=correction_id,
                    save=save,
                    require_active_save_match=require_active_save_match,
                )
            except PendingLifecycleTerminal as exc:
                if exc.state == "expired":
                    return pending_terminal_result(
                        save=save,
                        kind=exc.kind,
                        pending=exc.pending,
                        state="expired",
                    )
                return pending_conflict_result(
                    save=save,
                    kind=exc.kind,
                    pending=exc.pending,
                    same_identity=True,
                    message="pending action requires confirmation recovery",
                    state="invalid_state",
                )
            except PendingCompareConflict as exc:
                return pending_conflict_result(
                    save=exc.selected_save or save,
                    kind=exc.kind,
                    pending=None if exc.save_selection_changed else exc.pending,
                    same_identity=False if exc.save_selection_changed else exc.same_identity,
                    message="pending player session changed before publication",
                )
        elif clarification:
            clarification_id = f"clarification:{uuid.uuid4().hex}"
            clarification = {**clarification, "clarification_id": clarification_id}
            created_at = utc_now()
            external_digest = (
                stable_payload_digest(external_intent_candidate)
                if isinstance(external_intent_candidate, dict)
                else ""
            )
            pending_session = {
                "schema_version": "1",
                "clarification_id": clarification_id,
                "save_id": save["id"],
                "save_path": save["path"],
                "created_at": created_at,
                "expires_at": pending_action_expires_at_from_created(created_at),
                "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
                "clarification_origin": clarification_origin_for_result(
                    result,
                    external_intent_candidate=external_intent_candidate,
                ),
                "original_user_text": user_text,
                "external_candidate_digest": external_digest,
                "clarification": clarification,
                **platform_session_metadata(platform=platform, session_key=session_key, actor_id=actor_id),
            }
            try:
                lifecycle = self.publish_pending_after_compare(
                    kind="clarification",
                    session=pending_session,
                    initial_kind=initial_kind,
                    initial_pending=initial_pending,
                    initial_generation=initial_generation,
                    initial_revision=initial_revision,
                    initial_incarnation=initial_incarnation,
                    expected_pending_id=expected_id,
                    clarification_id=correction_id,
                    save=save,
                    require_active_save_match=require_active_save_match,
                )
            except PendingLifecycleTerminal as exc:
                if exc.state == "expired":
                    return pending_terminal_result(
                        save=save,
                        kind=exc.kind,
                        pending=exc.pending,
                        state="expired",
                    )
                return pending_conflict_result(
                    save=save,
                    kind=exc.kind,
                    pending=exc.pending,
                    same_identity=True,
                    message="pending action requires confirmation recovery",
                    state="invalid_state",
                )
            except PendingCompareConflict as exc:
                return pending_conflict_result(
                    save=exc.selected_save or save,
                    kind=exc.kind,
                    pending=None if exc.save_selection_changed else exc.pending,
                    same_identity=False if exc.save_selection_changed else exc.same_identity,
                    message="pending player session changed before publication",
                )
        else:
            if (
                initial_pending is not None
                and explicit_clarification_resolution
                and (not candidate_correction_attempt or bool(result.get("ok")))
                and not player_turn_error_preserves_clarification(result)
            ):
                try:
                    lifecycle = self.resolve_clarification_after_compare(
                        initial_pending=initial_pending,
                        initial_generation=initial_generation,
                        initial_revision=initial_revision,
                        initial_incarnation=initial_incarnation,
                        expected_pending_id=expected_id,
                        clarification_id=correction_id,
                        save=save,
                        platform=platform,
                        session_key=session_key,
                        actor_id=actor_id,
                        require_active_save_match=require_active_save_match,
                    )
                except PendingLifecycleTerminal as exc:
                    if exc.state == "expired":
                        return pending_terminal_result(
                            save=save,
                            kind=exc.kind,
                            pending=exc.pending,
                            state="expired",
                        )
                    return pending_conflict_result(
                        save=save,
                        kind=exc.kind,
                        pending=exc.pending,
                        same_identity=True,
                        message="pending action requires confirmation recovery",
                        state="invalid_state",
                    )
                except PendingCompareConflict as exc:
                    return pending_conflict_result(
                        save=exc.selected_save or save,
                        kind=exc.kind,
                        pending=None if exc.save_selection_changed else exc.pending,
                        same_identity=False if exc.save_selection_changed else exc.same_identity,
                        message="pending player session changed before resolution",
                    )
            elif initial_pending is not None:
                lifecycle = pending_lifecycle_projection(
                    initial_kind,
                    initial_pending,
                    state="preserved",
                    include_pending_id=True,
                )
        self.mark_played(str(save["id"]))
        return {
            "ok": bool(result.get("ok")),
            "active_save_id": save["id"],
            "save": save,
            "status": result.get("status"),
            "action": result.get("action"),
            "message": player_action_message(result, ready=ready),
            "ready_to_confirm": ready,
            "session_id": session_id,
            "clarification": clarification,
            "pending_clarification_id": clarification.get("clarification_id") if clarification else None,
            "saved": False,
            "warnings": result.get("warnings", []),
            "errors": result.get("errors", []),
            "repair_options": result.get("repair_options", []),
            **({"lifecycle": lifecycle} if lifecycle is not None else {}),
        }

    def player_act(
        self,
        *,
        user_text: str,
        save_path: str = "",
        intent_ai: str = "off",
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
        expected_pending_id: str = "",
        clarification_id: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        return self.player_turn(
            user_text=user_text,
            save_path=save_path,
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_model=intent_model,
            intent_provider=intent_provider,
            intent_timeout=intent_timeout,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
            expected_pending_id=expected_pending_id,
            clarification_id=clarification_id,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )

    def player_confirm(
        self,
        session_id: str | None = None,
        *,
        save_path: str = "",
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
    ) -> dict[str, Any]:
        if not pending_token_is_canonical(session_id):
            raise SaveManagerError(
                "player_confirm requires the pending action session_id returned by player_turn as an exact canonical string"
            )
        validate_platform_session_pair(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        )
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            return self._player_confirm_locked(
                session_id=session_id,
                save_path=save_path,
                platform=platform,
                session_key=session_key,
                actor_id=actor_id,
            )

    def _player_confirm_locked(
        self,
        *,
        session_id: str | None,
        save_path: str,
        platform: str,
        session_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        pending_kind, canonical_pending, _ = self.read_canonical_pending_locked(migrate=False)
        session = canonical_pending if pending_kind == "action" else None
        provided_session_id = session_id if isinstance(session_id, str) else ""
        if session is not None and provided_session_id:
            current_session_id = clean(session.get("session_id"))
            if current_session_id and provided_session_id != current_session_id:
                historical_receipt = self.find_confirmation_receipt(provided_session_id)
                if historical_receipt is None:
                    raise SaveManagerError("player_confirm session_id does not match the pending player action")
                historical_save = self.require_save(refresh=False, save_path=save_path)
                replay = self.validate_confirmation_receipt(
                    historical_receipt,
                    save=historical_save,
                    session_id=provided_session_id,
                    platform=platform,
                    session_key=session_key,
                    actor_id=actor_id,
                )
                return self.player_confirm_result(
                    save=historical_save,
                    result=replay,
                    refresh_registry=confirmation_registry_needs_repair(historical_save, replay),
                    confirmation_session_hash=hash_identity(provided_session_id),
                )
        if not session:
            save = self.require_save(refresh=False, save_path=save_path)
            receipt = self.find_confirmation_receipt(provided_session_id)
            if receipt is None:
                receipt = self.read_confirmation_receipt()
                if receipt is None:
                    history = self.read_confirmation_history()
                    receipt = history[-1] if history else None
            if receipt is None:
                raise SaveManagerError("no pending player action to confirm")
            result = self.validate_confirmation_receipt(
                receipt,
                save=save,
                session_id=provided_session_id,
                platform=platform,
                session_key=session_key,
                actor_id=actor_id,
            )
            return self.player_confirm_result(
                save=save,
                result=result,
                refresh_registry=confirmation_registry_needs_repair(save, result),
                confirmation_session_hash=hash_identity(provided_session_id),
            )
        save = self.require_save(refresh=False, save_path=save_path)
        if str(session.get("save_id")) != str(save["id"]):
            raise SaveManagerError("pending player action belongs to a different active save")
        pending_save_path = clean(session.get("save_path"))
        if not pending_save_path or normalize_required_relative(pending_save_path, "pending save") != str(save["path"]):
            raise SaveManagerError("pending player action save path does not match the selected save")
        bound_save_id = str(save["id"])
        bound_save_path = str(save["path"])
        validate_pending_platform_session(session, platform=platform, session_key=session_key, actor_id=actor_id)
        expected_session_id = str(session.get("session_id") or "")
        if not expected_session_id:
            raise SaveManagerError("pending player action is missing confirmation session_id")
        if not provided_session_id:
            raise SaveManagerError("player_confirm requires the pending action session_id returned by player_turn")
        if provided_session_id != expected_session_id:
            raise SaveManagerError("player_confirm session_id does not match the pending player action")
        delta = session.get("delta")
        proposal = session.get("turn_proposal")
        if not isinstance(delta, dict) or not isinstance(proposal, dict):
            raise SaveManagerError("pending player action is incomplete")
        if (
            pending_action_is_expired(session)
            and "confirmation_claim" not in session
            and not self.pending_action_requires_recovery(session)
        ):
            self.clear_pending_action()
            raise SaveManagerError("pending player action expired; ask the player to run player_turn again")
        original_session = deepcopy(session)
        claim_was_existing = "confirmation_claim" in session
        session = self.prepare_pending_confirmation_claim(session, save=save)
        delta = deepcopy(session["delta"])
        proposal = deepcopy(session["turn_proposal"])
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
            durable_turn_id = find_idempotent_turn(conn, delta)
        if pending_action_is_expired(session) and durable_turn_id is None:
            raise SaveManagerError("expired pending action requires confirmation recovery")
        existing_receipt = self.read_confirmation_receipt()
        if existing_receipt is not None:
            self.validate_confirmation_receipt(
                existing_receipt,
                save=save,
                session_id=provided_session_id,
                platform=platform,
                session_key=session_key,
                actor_id=actor_id,
                pending_session=session,
            )
        if durable_turn_id is None:
            save = self.require_save(refresh=True, save_path=bound_save_path)
            if str(save["id"]) != bound_save_id or str(save["path"]) != bound_save_path:
                raise SaveManagerError("pending player action save binding changed during confirmation")
            runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        proposal = dict(proposal)
        provenance = proposal.get("provenance") if isinstance(proposal.get("provenance"), dict) else {}
        proposal["provenance"] = {
            **dict(provenance),
            "confirmed_via": "player_confirm",
            "confirmation_session_id": expected_session_id,
            "confirmed_at": utc_now(),
        }
        proposal["human_confirmed"] = True
        try:
            if durable_turn_id is None:
                result = runtime.commit_turn(delta, turn_proposal=proposal).to_dict()
            else:
                result = self.reconcile_durable_confirmation(
                    save=save,
                    delta=delta,
                    expected_turn_id=durable_turn_id,
                )
        except Exception as exc:
            durable_turn_after_error: str | None = None
            durable_evidence_checked = False
            try:
                with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
                    durable_turn_after_error = find_idempotent_turn(conn, delta)
                durable_evidence_checked = True
            except Exception as evidence_exc:
                exc.add_note(f"durable confirmation evidence check failed: {evidence_exc!r}")
            if not claim_was_existing and durable_evidence_checked and durable_turn_after_error is None:
                try:
                    self.rollback_new_confirmation_claim(
                        save=save,
                        original_session=original_session,
                        claim_digest=clean(session["confirmation_claim"].get("claim_digest")),
                    )
                except Exception as cleanup_exc:
                    exc.add_note(f"confirmation claim rollback failed: {cleanup_exc!r}")
            raise
        validate_confirmation_result_contract(result)
        receipt = self.build_confirmation_receipt(session=session, save=save, result=result)
        self.write_confirmation_receipt_anchor(save=save, receipt=receipt)
        self.write_confirmation_receipt(receipt)
        self.clear_pending_action()
        return self.player_confirm_result(
            save=save,
            result=result,
            refresh_registry=confirmation_registry_needs_repair(save, result),
            confirmation_session_hash=hash_identity(expected_session_id),
        )

    def player_confirm_result(
        self,
        *,
        save: dict[str, Any],
        result: dict[str, Any],
        refresh_registry: bool,
        confirmation_session_hash: str = "",
    ) -> dict[str, Any]:
        validate_confirmation_result_contract(result)
        if refresh_registry:
            public_save = self.merge_registry_save_record(dict(save))
        else:
            public_save = self.scrub_cached_save_record(dict(save))
        replay = bool(result.get("idempotent_replay"))
        write_status = clean(result.get("write_status"))
        ok = bool(result.get("ok"))
        public_result = {
            "ok": ok,
            "active_save_id": save["id"],
            "save": public_save,
            "saved": bool(ok and write_status == "committed" and not replay),
            "message": player_confirm_message(result),
            "write_status": write_status,
            "idempotent_replay": replay,
            "projection_status": result.get("projection_status"),
            "warnings": result.get("warnings", []),
            "errors": result.get("errors", []),
        }
        if confirmation_session_hash:
            public_result["confirmation_session_hash"] = clean(confirmation_session_hash)
        return public_result

    def reconcile_durable_confirmation(
        self,
        *,
        save: dict[str, Any],
        delta: dict[str, Any],
        expected_turn_id: str,
    ) -> dict[str, Any]:
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect(runtime.campaign) as conn:
            try:
                result = reconcile_confirmed_turn(
                    runtime.campaign,
                    conn,
                    delta=delta,
                    expected_turn_id=expected_turn_id,
                )
            except ValueError as exc:
                raise SaveManagerError(str(exc)) from exc
        return result.to_dict()

    def require_active_save(self, *, refresh: bool) -> dict[str, Any]:
        return self.require_save(refresh=refresh)

    def require_save(self, *, refresh: bool, save_path: str = "") -> dict[str, Any]:
        if save_path:
            relative_path = normalize_required_relative(save_path, "save")
            registry = self.read_registry()
            path_errors = registry_record_path_errors(self.root, registry.get("saves", []), "save")
            if path_errors:
                raise SaveManagerError("; ".join(path_errors))
            record = find_save_record_by_path(registry.get("saves", []), relative_path)
            if record is None:
                raise SaveManagerError(f"save not found for path: {relative_path}")
            record = dict(record)
            if bool(record.get("archived")):
                raise SaveManagerError(f"save is archived: {record.get('id') or relative_path}")
            if refresh:
                record = self.merge_registry_save_record(record)
            if save_blocks_player_entry(record):
                raise SaveManagerError(
                    "; ".join([f"save is not healthy: {record.get('label') or record.get('id')}", *record.get("errors", [])])
                )
            return record
        current = self.current_save(refresh=refresh)
        if not current["ok"] or not current.get("save"):
            raise SaveManagerError("; ".join(current.get("errors", [])) or "no active save is configured")
        save = dict(current["save"])
        if save_blocks_player_entry(save):
            raise SaveManagerError(
                "; ".join([f"active save is not healthy: {save.get('label') or save.get('id')}", *save.get("errors", [])])
            )
        return save

    def selected_active_save(self) -> dict[str, Any] | None:
        current = self.current_save(refresh=False)
        selected = current.get("save")
        if current.get("ok") is not True or not isinstance(selected, dict):
            return None
        return dict(selected)

    def low_level_publication_owner_scope_hash(self) -> str:
        return stable_payload_digest(
            {
                "root": str(self.root),
                "registry_path": str(self.registry_path),
            }
        )

    @contextmanager
    def frozen_save_publication_registry(
        self,
        save: dict[str, Any],
        *,
        require_active_save_match: bool,
    ) -> Iterator[None]:
        expected_id = save.get("id")
        expected_path = save.get("path")
        if not isinstance(expected_id, str) or not expected_id or not isinstance(expected_path, str):
            raise SavePublicationConflict("pending publication requires a registered Save binding")
        lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
        with ExitStack() as stack:
            try:
                stack.enter_context(registry_lock(lock_path, root=self.root))
                registry = self.read_registry()
                records = registry.get("saves", [])
                path_errors = registry_record_path_errors(self.root, records, "save")
                if path_errors:
                    raise SavePublicationConflict("pending publication Save registry evidence is invalid")
                id_records = [
                    record
                    for record in records
                    if isinstance(record, dict) and record.get("id") == expected_id
                ]
                path_records = [
                    record
                    for record in records
                    if isinstance(record, dict) and record.get("path") == expected_path
                ]
                if len(id_records) != 1 or len(path_records) != 1 or id_records[0] is not path_records[0]:
                    raise SavePublicationConflict("pending publication Save binding changed")
                record = id_records[0]
                if bool(record.get("archived")) or save_blocks_player_entry(record):
                    raise SavePublicationConflict("pending publication Save is no longer available")
                if require_active_save_match and registry.get("active_save_id") != expected_id:
                    raise SavePublicationConflict("active Save selection changed before pending publication")
                resolved_save = self.resolve_relative(expected_path, "save")
                if not resolved_save.is_dir():
                    raise SaveManagerError("registered Save package is missing")
                inspection = inspect_v1_save(resolved_save)
                if inspection.get("ok") is not True:
                    raise SaveManagerError("registered Save package is invalid")
                campaign = load_campaign(resolved_save)
                with connect_existing_campaign_database(campaign, read_only=True) as conn:
                    conn.execute("select 1").fetchone()
            except SavePublicationConflict:
                raise
            except Exception:
                raise SavePublicationConflict(
                    "pending publication Save is no longer healthy"
                ) from None
            yield

    def pending_action_path(self) -> Path:
        return self.root / DEFAULT_PENDING_ACTION_RELATIVE

    def confirmation_receipt_path(self) -> Path:
        return self.root / DEFAULT_CONFIRMATION_RECEIPT_RELATIVE

    def confirmation_history_path(self) -> Path:
        return self.root / DEFAULT_CONFIRMATION_HISTORY_RELATIVE

    def confirmation_lock_path(self) -> Path:
        return self.root / DEFAULT_CONFIRMATION_LOCK_RELATIVE

    def pending_clarification_path(self) -> Path:
        return self.root / DEFAULT_PENDING_CLARIFICATION_RELATIVE

    def pending_lifecycle_revision_path(self) -> Path:
        return self.root / DEFAULT_PENDING_REVISION_RELATIVE

    def read_pending_lifecycle_evidence(
        self,
        *,
        require_existing: bool = False,
    ) -> tuple[str, int] | None:
        data = read_bounded_json_object(
            root=self.root,
            path=self.pending_lifecycle_revision_path(),
            label="pending player lifecycle revision",
            max_bytes=1024,
        )
        if data is None:
            if require_existing:
                raise SaveManagerError("pending player lifecycle revision is missing")
            return None
        if (
            set(data) != {"schema_version", "incarnation", "revision"}
            or data.get("schema_version") != "1"
            or not isinstance(data.get("incarnation"), str)
            or re.fullmatch(r"[0-9a-f]{32}", data["incarnation"]) is None
            or type(data.get("revision")) is not int
            or data["revision"] < 1
        ):
            raise SaveManagerError("pending player lifecycle revision is invalid")
        return str(data["incarnation"]), int(data["revision"])

    def read_pending_lifecycle_revision(self, *, require_existing: bool = False) -> int:
        evidence = self.read_pending_lifecycle_evidence(require_existing=require_existing)
        return evidence[1] if evidence is not None else 0

    def ensure_pending_lifecycle_revision(self) -> int:
        evidence = self.read_pending_lifecycle_evidence()
        if evidence is not None:
            return evidence[1]
        path = self.pending_lifecycle_revision_path()
        ensure_under_root(self.root, path, "pending player lifecycle revision")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_anchored_text(
            self.root,
            path,
            json.dumps(
                {
                    "schema_version": "1",
                    "incarnation": uuid.uuid4().hex,
                    "revision": 1,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            label="pending player lifecycle revision",
        )
        return 1

    def bump_pending_lifecycle_revision(self) -> int:
        evidence = self.read_pending_lifecycle_evidence()
        incarnation = evidence[0] if evidence is not None else uuid.uuid4().hex
        revision = evidence[1] + 1 if evidence is not None else 1
        path = self.pending_lifecycle_revision_path()
        ensure_under_root(self.root, path, "pending player lifecycle revision")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_anchored_text(
            self.root,
            path,
            json.dumps(
                {
                    "schema_version": "1",
                    "incarnation": incarnation,
                    "revision": revision,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            label="pending player lifecycle revision",
        )
        return revision

    def pending_lifecycle_revision_matches(
        self,
        expected_revision: int,
        expected_incarnation: str,
    ) -> bool:
        try:
            evidence = self.read_pending_lifecycle_evidence(require_existing=True)
            return evidence == (expected_incarnation, expected_revision)
        except SaveManagerError:
            return False

    def inspect_pending(
        self,
        *,
        save_path: str = "",
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
    ) -> dict[str, Any]:
        if not player_identity_inputs_are_valid(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        ):
            return {
                "ok": False,
                "status": "invalid_state",
                "lifecycle": {"state": "invalid_state", "kind": "unknown"},
                "errors": ["pending player identity is invalid"],
            }
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            selected: dict[str, Any] | None = None
            if not save_path:
                try:
                    current = self.current_save(refresh=False)
                except SaveManagerError:
                    return {
                        "ok": False,
                        "status": "invalid_state",
                        "lifecycle": {"state": "invalid_state", "kind": "unknown"},
                        "errors": ["pending player session has no verifiable selected save"],
                    }
                if not current.get("ok") or not isinstance(current.get("save"), dict):
                    return {
                        "ok": False,
                        "status": "invalid_state",
                        "lifecycle": {"state": "invalid_state", "kind": "unknown"},
                        "errors": ["pending player session has no verifiable selected save"],
                    }
                selected = dict(current["save"])
            kind, pending, _ = self.read_canonical_pending_locked(migrate=False)
            try:
                self.ensure_pending_lifecycle_revision()
            except SaveManagerError:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "lifecycle": {"state": "invalid_state", "kind": kind or "unknown"},
                    "errors": ["pending player lifecycle revision is invalid"],
                }
            if pending is None:
                return {
                    "ok": True,
                    "status": "not_found",
                    "lifecycle": pending_lifecycle_projection("unknown", None, state="not_found"),
                    "errors": [],
                }
            same_identity = pending_session_identity_matches(
                pending,
                platform=platform,
                session_key=session_key,
                actor_id=actor_id,
            )
            if not same_identity:
                return {
                    "ok": False,
                    "status": "conflict",
                    "lifecycle": {"state": "conflict", "kind": kind},
                    "errors": ["pending player session belongs to a different identity"],
                }
            if save_path:
                try:
                    supplied_save_path = normalize_required_relative(save_path, "save")
                except SaveManagerError:
                    return {
                        "ok": False,
                        "status": "invalid_state",
                        "lifecycle": {"state": "invalid_state", "kind": kind},
                        "errors": ["pending player session has no verifiable selected save"],
                    }
                if supplied_save_path != pending.get("save_path"):
                    return {
                        "ok": False,
                        "status": "conflict",
                        "lifecycle": {"state": "conflict", "kind": kind},
                        "errors": ["pending player session belongs to a different save"],
                    }
            binding_state = self.pending_orphan_classification(kind, pending)
            if binding_state == "invalid_state":
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "lifecycle": pending_lifecycle_projection(kind, pending, state="invalid_state"),
                    "errors": ["pending player session has unresolved save evidence"],
                }
            if binding_state == "orphaned":
                if not self.clear_pending_if_still_orphaned(kind, pending):
                    return {
                        "ok": False,
                        "status": "invalid_state",
                        "lifecycle": pending_lifecycle_projection(
                            kind,
                            pending,
                            state="invalid_state",
                        ),
                        "errors": ["pending player session binding changed during orphan cleanup"],
                    }
                return {
                    "ok": True,
                    "status": "orphaned",
                    "lifecycle": pending_lifecycle_projection(kind, pending, state="orphaned"),
                    "errors": [],
                }
            if save_path:
                try:
                    selected = self.require_save(refresh=False, save_path=save_path)
                except SaveManagerError:
                    return {
                        "ok": False,
                        "status": "invalid_state",
                        "lifecycle": {"state": "invalid_state", "kind": kind},
                        "errors": ["pending player session has no verifiable selected save"],
                    }
            if selected is not None and not pending_matches_save(pending, selected):
                return {
                    "ok": False,
                    "status": "conflict",
                    "lifecycle": {"state": "conflict", "kind": kind},
                    "errors": ["pending player session belongs to a different save"],
                }
            assert selected is not None
            try:
                with self.frozen_save_publication_registry(
                    selected,
                    require_active_save_match=not bool(save_path),
                ):
                    kind, pending, migrated = self.read_canonical_pending_locked(
                        migrate=True,
                        live_binding_verified=True,
                    )
                    assert pending is not None
                    if pending_action_is_expired(pending):
                        if kind == "action" and self.pending_action_requires_recovery(pending):
                            return {
                                "ok": False,
                                "status": "invalid_state",
                                "lifecycle": pending_lifecycle_projection(
                                    kind,
                                    pending,
                                    state="invalid_state",
                                ),
                                "errors": ["pending action requires confirmation recovery"],
                            }
                        self.clear_pending_kind(kind)
                        return {
                            "ok": True,
                            "status": "expired",
                            "lifecycle": pending_lifecycle_projection(
                                kind,
                                pending,
                                state="expired",
                            ),
                            "errors": [],
                        }
                    state = "migrated" if migrated else "active"
                    return {
                        "ok": True,
                        "status": state,
                        "lifecycle": pending_lifecycle_projection(
                            kind,
                            pending,
                            state=state,
                            include_pending_id=True,
                        ),
                        "errors": [],
                    }
            except SavePublicationConflict:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "lifecycle": pending_lifecycle_projection(
                        kind,
                        pending,
                        state="invalid_state",
                    ),
                    "errors": ["pending player session has unresolved save evidence"],
                }

    def player_cancel(
        self,
        expected_pending_id: str,
        *,
        save_path: str = "",
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
    ) -> dict[str, Any]:
        if not player_identity_inputs_are_valid(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        ):
            return {
                "ok": False,
                "status": "invalid_state",
                "saved": False,
                "lifecycle": {"state": "invalid_state", "kind": "unknown"},
                "errors": ["pending player identity is invalid"],
            }
        expected_token_valid = pending_token_is_canonical_or_empty(expected_pending_id)
        expected_id = expected_pending_id if isinstance(expected_pending_id, str) and expected_token_valid else ""
        inferred_kind = (
            "clarification"
            if expected_id.startswith(("clarification:", "clarify:"))
            else "action"
        )
        if not expected_id or not expected_token_valid:
            return {
                "ok": False,
                "status": "invalid_state",
                "lifecycle": pending_lifecycle_projection(inferred_kind, None, state="invalid_state"),
                "errors": ["expected_pending_id is required"],
            }
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            try:
                kind, pending, _ = self.read_canonical_pending_locked(migrate=False)
                self.ensure_pending_lifecycle_revision()
            except SaveManagerError:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "saved": False,
                    "lifecycle": {"state": "invalid_state", "kind": inferred_kind},
                    "errors": ["pending player session evidence is invalid"],
                }
            if pending is None:
                return {
                    "ok": True,
                    "status": "not_found",
                    "lifecycle": pending_lifecycle_projection(inferred_kind, None, state="not_found"),
                    "errors": [],
                }
            try:
                selected = self.require_save(refresh=False, save_path=save_path)
            except SaveManagerError:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "saved": False,
                    "lifecycle": {"state": "invalid_state", "kind": kind},
                    "errors": ["pending player session has no verifiable selected save"],
                }
            if not pending_matches_save(pending, selected):
                return pending_cancel_conflict(kind, pending, "pending player session belongs to a different save")
            if not pending_session_identity_matches(
                pending,
                platform=platform,
                session_key=session_key,
                actor_id=actor_id,
            ):
                return pending_cancel_conflict(kind, pending, "pending player session belongs to a different identity")
            if pending_session_id(kind, pending) != expected_id:
                return pending_cancel_conflict(kind, pending, "expected pending id does not match the current session")
            try:
                with self.frozen_save_publication_registry(
                    selected,
                    require_active_save_match=not bool(save_path),
                ):
                    kind, pending, _ = self.read_canonical_pending_locked(
                        migrate=True,
                        live_binding_verified=True,
                    )
                    assert pending is not None
                    if pending_action_is_expired(pending):
                        if kind == "action" and self.pending_action_requires_recovery(pending):
                            return {
                                "ok": False,
                                "status": "invalid_state",
                                "lifecycle": pending_lifecycle_projection(
                                    kind,
                                    pending,
                                    state="invalid_state",
                                ),
                                "errors": ["pending action requires confirmation recovery"],
                            }
                        self.clear_pending_kind(kind)
                        return {
                            "ok": True,
                            "status": "expired",
                            "lifecycle": pending_lifecycle_projection(
                                kind,
                                pending,
                                state="expired",
                            ),
                            "errors": [],
                        }
                    if kind == "action" and self.pending_action_requires_recovery(pending):
                        return {
                            "ok": False,
                            "status": "invalid_state",
                            "lifecycle": pending_lifecycle_projection(
                                kind,
                                pending,
                                state="invalid_state",
                            ),
                            "errors": ["pending action requires confirmation recovery"],
                        }
                    self.clear_pending_kind(kind)
                    return {
                        "ok": True,
                        "status": "canceled",
                        "saved": False,
                        "lifecycle": pending_lifecycle_projection(
                            kind,
                            pending,
                            state="canceled",
                        ),
                        "errors": [],
                    }
            except SavePublicationConflict:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "saved": False,
                    "lifecycle": {"state": "invalid_state", "kind": kind},
                    "errors": ["pending player session has unresolved save evidence"],
                }
            except SaveManagerError:
                return {
                    "ok": False,
                    "status": "invalid_state",
                    "saved": False,
                    "lifecycle": {"state": "invalid_state", "kind": kind},
                    "errors": ["pending player session evidence is invalid"],
                }

    def begin_low_level_clarification_publication(
        self,
        *,
        save_path: str,
        require_active_save_match: bool = False,
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
    ) -> dict[str, Any]:
        """Freeze owner evidence before a low-level Runtime may propose clarification."""
        validate_platform_session_pair(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        )
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            normalized_save_path = normalize_required_relative(save_path, "save")
            canonical_publication = True
            try:
                save = self.require_save(refresh=False, save_path=normalized_save_path)
            except SaveManagerError:
                if require_active_save_match:
                    raise
                registry = self.read_registry()
                records = registry.get("saves", [])
                path_errors = registry_record_path_errors(self.root, records, "save")
                if path_errors or find_save_record_by_path(records, normalized_save_path) is not None:
                    raise
                resolved_save = self.resolve_relative(normalized_save_path, "save")
                if not resolved_save.is_dir():
                    raise
                save = {"id": "", "path": normalized_save_path}
                canonical_publication = False
            if require_active_save_match:
                selected_save = self.selected_active_save()
                if selected_save is None or not exact_save_record_matches(save, selected_save):
                    raise SaveManagerError("active save selection changed before low-level preview")
            kind = ""
            pending: dict[str, Any] | None = None
            if canonical_publication:
                kind, pending, _ = self.read_canonical_pending_locked(migrate=False)
                if pending is not None and (
                    not pending_matches_save(pending, save)
                    or not pending_session_identity_matches(
                        pending,
                        platform=platform,
                        session_key=session_key,
                        actor_id=actor_id,
                    )
                ):
                    raise SaveManagerError("low-level preview conflicts with another pending player session")
                if kind == "clarification" and pending is not None:
                    raise SaveManagerError(
                        "low-level preview cannot run while a clarification is pending; "
                        "use player_turn with matching lifecycle tokens or player_cancel"
                    )
            platform_value = clean(platform)
            session_hash = hash_identity(clean(session_key)) if clean(session_key) else ""
            actor_hash = hash_identity(clean(actor_id)) if clean(actor_id) else ""
            owner_incarnation = ""
            owner_revision = 0
            if canonical_publication:
                self.ensure_pending_lifecycle_revision()
                owner_evidence = self.read_pending_lifecycle_evidence(require_existing=True)
                assert owner_evidence is not None
                owner_incarnation, owner_revision = owner_evidence
            publication = {
                "schema_version": "1",
                "save_id": str(save["id"]),
                "save_path": str(save["path"]),
                "pending_kind": kind,
                "pending_generation": pending_generation_digest(kind, pending),
                "owner_incarnation": owner_incarnation,
                "owner_revision": owner_revision,
                "owner_scope_hash": self.low_level_publication_owner_scope_hash(),
                "require_active_save_match": require_active_save_match,
                "canonical_publication": canonical_publication,
                "platform": platform_value,
                "session_key_hash": session_hash,
                "actor_id_hash": actor_hash,
            }
            publication["publication_token"] = low_level_publication_token(publication)
            return publication

    def low_level_publication_is_canonical(
        self,
        expected_publication: dict[str, Any] | None,
    ) -> bool:
        publication = validate_low_level_publication_integrity(expected_publication)
        canonical_publication = publication.get("canonical_publication")
        if type(canonical_publication) is not bool:
            raise SaveManagerError("low-level clarification publication evidence is invalid")
        return canonical_publication

    def low_level_clarification_publication_allowed(self, result: dict[str, Any]) -> bool:
        return not player_turn_error_preserves_clarification(result)

    def record_low_level_clarification(
        self,
        *,
        user_text: str,
        clarification: dict[str, Any],
        save_path: str = "",
        external_intent_candidate: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        platform: str = "",
        session_key: str = "",
        actor_id: str = "",
        expected_publication: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a developer low-level clarification through the canonical owner."""
        validate_platform_session_pair(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        )
        if result is not None and not self.low_level_clarification_publication_allowed(result):
            raise SaveManagerError("typed external intent errors cannot publish clarification")
        if expected_publication is None:
            raise SaveManagerError("low-level clarification publication requires an owner snapshot")
        save = self.require_save(refresh=False, save_path=save_path)
        created_at = utc_now()
        clarification_id = f"clarification:{uuid.uuid4().hex}"
        validate_clarification_payload_privacy(
            clarification,
            session_key=session_key,
            actor_id=actor_id,
        )
        public_clarification = {**clarification, "clarification_id": clarification_id}
        session = {
            "schema_version": "1",
            "clarification_id": clarification_id,
            "save_id": save["id"],
            "save_path": save["path"],
            "created_at": created_at,
            "expires_at": pending_action_expires_at_from_created(created_at),
            "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
            "clarification_origin": clarification_origin_for_result(
                result or {},
                external_intent_candidate=external_intent_candidate,
            ),
            "original_user_text": user_text,
            "external_candidate_digest": (
                stable_payload_digest(external_intent_candidate)
                if isinstance(external_intent_candidate, dict)
                else ""
            ),
            "clarification": public_clarification,
            **platform_session_metadata(platform=platform, session_key=session_key, actor_id=actor_id),
        }
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            current_kind, current, _ = self.read_canonical_pending_locked(migrate=False)
            publication = validate_low_level_publication_integrity(expected_publication)
            if (
                publication.get("schema_version") != "1"
                or publication.get("save_id") != save.get("id")
                or publication.get("save_path") != save.get("path")
                or publication.get("pending_kind") not in {"", "action"}
                or not isinstance(publication.get("owner_incarnation"), str)
                or re.fullmatch(r"[0-9a-f]{32}", publication["owner_incarnation"])
                is None
                or type(publication.get("owner_revision")) is not int
                or publication["owner_revision"] < 1
                or publication.get("owner_scope_hash")
                != self.low_level_publication_owner_scope_hash()
                or type(publication.get("require_active_save_match")) is not bool
                or publication.get("canonical_publication") is not True
                or publication.get("platform") != clean(platform)
                or publication.get("session_key_hash")
                != (hash_identity(clean(session_key)) if clean(session_key) else "")
                or publication.get("actor_id_hash")
                != (hash_identity(clean(actor_id)) if clean(actor_id) else "")
            ):
                raise SaveManagerError("low-level clarification publication evidence is invalid")
            expected_generation = publication.get("pending_generation")
            expected_kind = publication.get("pending_kind")
            if (
                not isinstance(expected_generation, str)
                or (expected_kind == "" and expected_generation != "")
                or (
                    expected_kind == "action"
                    and re.fullmatch(r"[0-9a-f]{64}", expected_generation) is None
                )
            ):
                raise SaveManagerError("low-level clarification publication evidence is invalid")
            current_generation = pending_generation_digest(current_kind, current)
            if (
                not self.pending_lifecycle_revision_matches(
                    int(publication["owner_revision"]),
                    str(publication["owner_incarnation"]),
                )
                or publication.get("pending_kind") != current_kind
                or publication.get("pending_generation") != current_generation
            ):
                return pending_conflict_result(
                    save=save,
                    kind=current_kind or str(publication.get("pending_kind") or "clarification"),
                    pending=current,
                    same_identity=(
                        current is not None
                        and pending_matches_save(current, save)
                        and pending_session_identity_matches(
                            current,
                            platform=platform,
                            session_key=session_key,
                            actor_id=actor_id,
                        )
                    ),
                    message="pending player session changed before low-level clarification publication",
                )
            if current is not None:
                return pending_conflict_result(
                    save=save,
                    kind=current_kind,
                    pending=current,
                    same_identity=(
                        pending_matches_save(current, save)
                        and pending_session_identity_matches(
                            current,
                            platform=platform,
                            session_key=session_key,
                            actor_id=actor_id,
                        )
                    ),
                    message="pending player session already exists",
                )
            try:
                with self.frozen_save_publication_registry(
                    save,
                    require_active_save_match=bool(publication["require_active_save_match"]),
                ):
                    self.write_pending_clarification(session)
            except SavePublicationConflict:
                return pending_conflict_result(
                    save=save,
                    kind=current_kind or "clarification",
                    pending=None,
                    same_identity=False,
                    message="Save binding changed before low-level clarification publication",
                )
        return {
            "ok": True,
            "status": "needs_clarification",
            "clarification": public_clarification,
            "pending_clarification_id": clarification_id,
            "saved": False,
            "lifecycle": pending_lifecycle_projection(
                "clarification",
                session,
                state="active",
                include_pending_id=True,
            ),
            "errors": [],
        }

    def read_canonical_pending_locked(
        self,
        *,
        migrate: bool,
        live_binding_verified: bool = False,
    ) -> tuple[str, dict[str, Any] | None, bool]:
        action = self.read_pending_action()
        clarification = self.read_pending_clarification()
        if action is not None and clarification is not None:
            raise SaveManagerError("pending player state contains multiple active sessions")
        if action is not None:
            validate_pending_envelope("action", action)
            return "action", action, False
        if clarification is None:
            return "", None, False
        validate_pending_envelope("clarification", clarification, allow_legacy=True)
        needs_migration = any(
            key not in clarification
            for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest")
        )
        if migrate and needs_migration:
            migrated_clarification = migrate_legacy_clarification(clarification)
            validate_pending_envelope("clarification", migrated_clarification)
            if (
                not live_binding_verified
                and self.pending_orphan_classification(
                    "clarification",
                    migrated_clarification,
                )
            ):
                return "clarification", clarification, False
            self.write_pending_clarification(migrated_clarification)
            return "clarification", migrated_clarification, True
        if needs_migration:
            return "clarification", clarification, False
        validate_pending_envelope("clarification", clarification)
        return "clarification", clarification, False

    def pending_action_requires_recovery(self, pending: dict[str, Any]) -> bool:
        if "confirmation_claim" in pending:
            return True
        delta = pending.get("delta")
        save_path = clean(pending.get("save_path"))
        if not isinstance(delta, dict) or not save_path:
            return False
        try:
            campaign = load_campaign(self.resolve_relative(save_path, "pending save"))
            with connect_existing_campaign_database(campaign, read_only=True) as conn:
                durable_turn = find_idempotent_turn(conn, delta)
                claim_anchor = conn.execute(
                    "select value from meta where key = ?",
                    (CONFIRMATION_CLAIM_META_KEY,),
                ).fetchone()
            expected_claim = self.expected_confirmation_claim(
                pending,
                save={"id": clean(pending.get("save_id")), "path": save_path},
            )
            expected_digest = stable_payload_digest(expected_claim)
            return durable_turn is not None or (
                claim_anchor is not None and clean(claim_anchor["value"]) == expected_digest
            )
        except Exception:
            return True

    def pending_has_receipt_evidence(
        self,
        kind: str,
        pending: dict[str, Any],
    ) -> bool:
        pending_id = pending_session_id(kind, pending)
        if not pending_id:
            return True
        try:
            receipts: list[dict[str, Any]] = []
            latest = self.read_confirmation_receipt()
            if latest is not None:
                receipts.append(latest)
            receipts.extend(self.read_confirmation_history())
            pending_hash = hash_identity(pending_id)
            for receipt in receipts:
                validate_confirmation_receipt_envelope(receipt)
                if receipt.get("confirmation_session_hash") == pending_hash:
                    return True
        except (OSError, SaveManagerError, UnicodeError):
            return True
        return False

    def pending_orphan_classification(self, kind: str, pending: dict[str, Any]) -> str:
        save_path = clean(pending.get("save_path"))
        save_id = clean(pending.get("save_id"))
        if not save_path or not save_id:
            return "invalid_state"
        try:
            registry = self.read_registry()
            records = registry.get("saves", [])
            id_records = [
                record
                for record in records
                if isinstance(record, dict) and clean(record.get("id")) == save_id
            ]
            path_records = [
                record
                for record in records
                if isinstance(record, dict)
                and normalize_optional_relative(record.get("path"), "save") == save_path
            ]
            path = self.resolve_relative(save_path, "pending save")
        except Exception:
            return "invalid_state"
        if len(id_records) > 1 or len(path_records) > 1:
            return "invalid_state"
        id_record = id_records[0] if id_records else None
        record = path_records[0] if path_records else None
        if id_record is not None and clean(id_record.get("path")) != save_path:
            return "invalid_state"
        if record is not None and (clean(record.get("id")) != save_id or bool(record.get("archived"))):
            return "invalid_state"
        record_matches = record is not None and clean(record.get("id")) == save_id
        if record_matches:
            try:
                with self.frozen_save_publication_registry(
                    {"id": save_id, "path": save_path},
                    require_active_save_match=False,
                ):
                    pass
            except SavePublicationConflict:
                return "invalid_state"
            return ""
        if path.is_dir():
            return "invalid_state"
        if kind == "action" and "confirmation_claim" in pending:
            return "invalid_state"
        if self.pending_has_receipt_evidence(kind, pending):
            return "invalid_state"
        return "orphaned"

    def clear_pending_if_still_orphaned(
        self,
        kind: str,
        pending: dict[str, Any],
    ) -> bool:
        save_path = clean(pending.get("save_path"))
        save_id = clean(pending.get("save_id"))
        if not save_path or not save_id:
            return False
        lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
        try:
            with registry_lock(lock_path, root=self.root):
                registry = self.read_registry()
                records = registry.get("saves", [])
                if any(
                    isinstance(record, dict)
                    and (
                        clean(record.get("id")) == save_id
                        or clean(record.get("path")) == save_path
                    )
                    for record in records
                ):
                    return False
                save = self.resolve_relative(save_path, "pending save")
                if save.is_dir():
                    return False
                if kind == "action" and "confirmation_claim" in pending:
                    return False
                if self.pending_has_receipt_evidence(kind, pending):
                    return False
                self.clear_pending_kind(kind)
                return True
        except (OSError, SaveManagerError):
            return False

    def clear_pending_kind(self, kind: str) -> None:
        if kind == "action":
            self.clear_pending_action()
        elif kind == "clarification":
            self.clear_pending_clarification()

    def require_live_pending_for_compare(self, kind: str, pending: dict[str, Any]) -> None:
        if not pending_action_is_expired(pending):
            return
        if kind == "action" and self.pending_action_requires_recovery(pending):
            raise PendingLifecycleTerminal(kind, pending, state="invalid_state")
        self.clear_pending_kind(kind)
        raise PendingLifecycleTerminal(kind, pending, state="expired")

    def publish_pending_after_compare(
        self,
        *,
        kind: str,
        session: dict[str, Any],
        initial_kind: str,
        initial_pending: dict[str, Any] | None,
        initial_generation: str,
        initial_revision: int,
        initial_incarnation: str,
        expected_pending_id: str,
        clarification_id: str,
        save: dict[str, Any],
        require_active_save_match: bool,
    ) -> dict[str, Any]:
        validate_pending_envelope(kind, session)
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            current_kind, current, _ = self.read_canonical_pending_locked(migrate=False)
            if require_active_save_match:
                selected_save = self.selected_active_save()
                if selected_save is None or not exact_save_record_matches(save, selected_save):
                    raise PendingCompareConflict(
                        current_kind or kind,
                        current,
                        same_identity=False,
                        save_selection_changed=True,
                        selected_save=selected_save,
                    )
            if not self.pending_lifecycle_revision_matches(
                initial_revision,
                initial_incarnation,
            ):
                raise PendingCompareConflict(current_kind or kind, current, same_identity=False)
            current_same_identity = (
                current is not None
                and pending_matches_save(current, save)
                and pending_session_identity_matches(
                    current,
                    platform=clean(session.get("platform")),
                    session_key="",
                    actor_id="",
                    supplied_hashes=True,
                    session_key_hash=clean(session.get("session_key_hash")),
                    actor_id_hash=clean(session.get("actor_id_hash")),
                )
            )
            if initial_pending is None:
                if current is not None:
                    raise PendingCompareConflict(current_kind, current, same_identity=current_same_identity)
            else:
                current_generation = pending_generation_digest(current_kind, current) if current is not None else ""
                current_id = pending_session_id(current_kind, current) if current is not None else ""
                clarification_tokens_match = (
                    initial_kind != "clarification"
                    or (
                        expected_pending_id == current_id
                        and clarification_id == current_id
                    )
                )
                if (
                    current is None
                    or current_kind != initial_kind
                    or current_generation != initial_generation
                    or not expected_pending_id
                    or expected_pending_id != current_id
                    or not clarification_tokens_match
                ):
                    raise PendingCompareConflict(
                        current_kind or initial_kind,
                        current,
                        same_identity=current_same_identity,
                    )
            if not pending_matches_save(session, save):
                raise SaveManagerError("new pending player session save binding is invalid")
            try:
                with self.frozen_save_publication_registry(
                    save,
                    require_active_save_match=require_active_save_match,
                ):
                    if initial_pending is not None:
                        assert current is not None
                        self.require_live_pending_for_compare(current_kind, current)
                    previous_action = self.read_pending_action()
                    previous_clarification = self.read_pending_clarification()
                    previous_receipt = self.read_confirmation_receipt()
                    previous_history = self.read_confirmation_history()
                    try:
                        if previous_receipt is not None:
                            self.archive_confirmation_receipt(previous_receipt, history=previous_history)
                            self.clear_confirmation_receipt()
                        if kind == "action":
                            self.write_pending_action(session)
                            self.clear_pending_clarification()
                        else:
                            self.write_pending_clarification(session)
                            self.clear_pending_action()
                    except Exception as exc:
                        try:
                            self.restore_pending_publication(
                                action=previous_action,
                                clarification=previous_clarification,
                                receipt=previous_receipt,
                                history=previous_history,
                            )
                        except Exception as restore_exc:
                            exc.add_note(f"pending publication restore failed: {restore_exc!r}")
                        raise
            except SavePublicationConflict:
                raise PendingCompareConflict(
                    current_kind or kind,
                    current,
                    same_identity=False,
                ) from None
        return pending_lifecycle_projection(
            kind,
            session,
            state="superseded" if initial_pending is not None else "active",
            include_pending_id=True,
        )

    def resolve_clarification_after_compare(
        self,
        *,
        initial_pending: dict[str, Any],
        initial_generation: str,
        initial_revision: int,
        initial_incarnation: str,
        expected_pending_id: str,
        clarification_id: str,
        save: dict[str, Any],
        platform: str,
        session_key: str,
        actor_id: str,
        require_active_save_match: bool,
    ) -> dict[str, Any]:
        with confirmation_claim_lock(self.confirmation_lock_path(), root=self.root):
            current_kind, current, _ = self.read_canonical_pending_locked(migrate=False)
            if require_active_save_match:
                selected_save = self.selected_active_save()
                if selected_save is None or not exact_save_record_matches(save, selected_save):
                    raise PendingCompareConflict(
                        current_kind or "clarification",
                        current,
                        same_identity=False,
                        save_selection_changed=True,
                        selected_save=selected_save,
                    )
            if not self.pending_lifecycle_revision_matches(
                initial_revision,
                initial_incarnation,
            ):
                raise PendingCompareConflict(
                    current_kind or "clarification",
                    current,
                    same_identity=False,
                )
            current_generation = pending_generation_digest(current_kind, current) if current is not None else ""
            current_id = pending_session_id(current_kind, current) if current is not None else ""
            current_same_identity = (
                current is not None
                and pending_matches_save(current, save)
                and pending_session_identity_matches(
                    current,
                    platform=platform,
                    session_key=session_key,
                    actor_id=actor_id,
                )
            )
            if (
                current is None
                or current_kind != "clarification"
                or current_generation != initial_generation
                or expected_pending_id != current_id
                or clarification_id != current_id
                or not pending_matches_save(current, save)
                or not current_same_identity
            ):
                raise PendingCompareConflict(
                    current_kind or "clarification",
                    current,
                    same_identity=current_same_identity,
                )
            try:
                with self.frozen_save_publication_registry(
                    save,
                    require_active_save_match=require_active_save_match,
                ):
                    assert current is not None
                    self.require_live_pending_for_compare(current_kind, current)
                    self.clear_pending_clarification()
            except SavePublicationConflict:
                raise PendingCompareConflict(
                    current_kind,
                    current,
                    same_identity=False,
                ) from None
        return pending_lifecycle_projection(
            "clarification",
            initial_pending,
            state="superseded",
            include_pending_id=True,
        )

    def restore_pending_publication(
        self,
        *,
        action: dict[str, Any] | None,
        clarification: dict[str, Any] | None,
        receipt: dict[str, Any] | None,
        history: list[dict[str, Any]],
    ) -> None:
        if action is None:
            self.clear_pending_action()
        else:
            self.write_pending_action(action)
        if clarification is None:
            self.clear_pending_clarification()
        else:
            self.write_pending_clarification(clarification)
        if receipt is None:
            self.clear_confirmation_receipt()
        else:
            self.write_confirmation_receipt(receipt)
        self.write_confirmation_history(history, allow_restore=True)
        for historical_receipt in history:
            self.restore_confirmation_receipt_anchor(historical_receipt)

    def read_pending_action(self) -> dict[str, Any] | None:
        path = self.pending_action_path()
        return read_bounded_json_object(
            root=self.root,
            path=path,
            label="pending player action",
            max_bytes=MAX_PENDING_STATE_BYTES,
        )

    def write_pending_action(self, session: dict[str, Any]) -> None:
        path = self.pending_action_path()
        ensure_under_root(self.root, path, "pending action")
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_pending_json_shape(session)
        try:
            text = json.dumps(
                session,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n"
            encoded = text.encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise SaveManagerError("pending player action is not safely serializable") from exc
        if len(encoded) > MAX_PENDING_STATE_BYTES:
            raise SaveManagerError("pending player action exceeds the bounded size limit")
        self.bump_pending_lifecycle_revision()
        write_anchored_text(self.root, path, text, label="pending player action")

    def clear_pending_action(self) -> None:
        path = self.pending_action_path()
        ensure_under_root(self.root, path, "pending action")
        if not anchored_file_exists(self.root, path):
            return
        self.bump_pending_lifecycle_revision()
        unlink_anchored_file(self.root, path, label="pending player action")

    def read_confirmation_receipt(self) -> dict[str, Any] | None:
        path = self.confirmation_receipt_path()
        try:
            raw = read_registry_bytes_anchored(
                self.root,
                path,
                max_bytes=MAX_CONFIRMATION_RECEIPT_BYTES,
            )
            if raw is None:
                return None
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys)
        except SaveManagerError as exc:
            if "duplicate JSON keys" in str(exc) or "escapes workspace root" in str(exc):
                raise
            if "exceeds the bounded size limit" in str(exc):
                raise SaveManagerError(
                    "confirmation replay receipt exceeds the bounded size limit"
                ) from exc
            raise SaveManagerError("confirmation replay receipt is invalid") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SaveManagerError("confirmation replay receipt is invalid") from exc
        if not isinstance(data, dict):
            raise SaveManagerError("confirmation replay receipt must be a JSON object")
        validate_confirmation_receipt_envelope(data)
        return data

    def read_confirmation_history(self) -> list[dict[str, Any]]:
        path = self.confirmation_history_path()
        data = read_bounded_json_object(
            root=self.root,
            path=path,
            label="confirmation replay history",
            max_bytes=MAX_CONFIRMATION_HISTORY_BYTES,
        )
        if data is None:
            self.assert_confirmation_history_order_authority_absent()
            return []
        if set(data) != {"schema_version", "receipts", "order_digest"} or data.get("schema_version") != "1":
            raise SaveManagerError("confirmation replay history has an invalid schema")
        receipts = validate_confirmation_history_entries(data.get("receipts"))
        order_digest = data.get("order_digest")
        if (
            not isinstance(order_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", order_digest) is None
            or order_digest != confirmation_history_order_digest(receipts)
        ):
            raise SaveManagerError("confirmation replay history failed order integrity validation")
        self.validate_confirmation_history_order_anchor(receipts, order_digest)
        return receipts

    def assert_confirmation_history_order_authority_absent(self) -> None:
        registry = self.read_registry()
        visited: set[str] = set()
        for record in registry.get("saves", []):
            if not isinstance(record, dict):
                continue
            save_path = normalize_required_relative(record.get("path"), "receipt save")
            if save_path in visited:
                continue
            visited.add(save_path)
            resolved = self.resolve_relative(save_path, "receipt save")
            if not resolved.is_dir():
                continue
            try:
                campaign = load_campaign(resolved)
                with connect_existing_campaign_database(campaign, read_only=True) as conn:
                    anchor = conn.execute(
                        """
                        select key from meta
                        where key = ? or key = ? or key glob ?
                        limit 1
                        """,
                        (
                            CONFIRMATION_HISTORY_ORDER_META_KEY,
                            CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,
                            f"{LEGACY_CONFIRMATION_HISTORY_ORDER_META_PREFIX}*",
                        ),
                    ).fetchone()
            except Exception as exc:
                raise SaveManagerError(
                    "confirmation replay history order authority cannot be verified"
                ) from exc
            if anchor is not None:
                raise SaveManagerError(
                    "confirmation replay history is missing while SQLite order authority remains"
                )

    def write_confirmation_history(
        self,
        receipts: list[dict[str, Any]],
        *,
        allow_restore: bool = False,
    ) -> None:
        validated_receipts = validate_confirmation_history_entries(receipts)
        path = self.confirmation_history_path()
        ensure_under_root(self.root, path, "confirmation replay history")
        if not validated_receipts:
            unlink_anchored_file(self.root, path, label="confirmation replay history")
            self.cleanup_confirmation_history_order_anchors()
            return
        if path.exists() and not allow_restore:
            validate_confirmation_history_transition(
                self.read_confirmation_history(),
                validated_receipts,
            )
        order_digest = confirmation_history_order_digest(validated_receipts)
        envelope = {
            "schema_version": "1",
            "receipts": validated_receipts,
            "order_digest": order_digest,
        }
        text = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if len(text.encode("utf-8")) > MAX_CONFIRMATION_HISTORY_BYTES:
            raise SaveManagerError("confirmation replay history exceeds the bounded size limit")
        self.write_confirmation_history_order_anchor(validated_receipts[-1], order_digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_anchored_text(self.root, path, text, label="confirmation replay history")
        self.promote_confirmation_history_order_anchor(validated_receipts[-1], order_digest)

    def write_confirmation_history_order_anchor(
        self,
        receipt: dict[str, Any],
        order_digest: str,
    ) -> None:
        save = self.require_save(refresh=False, save_path=clean(receipt.get("save_path")))
        if not pending_matches_save(receipt, save):
            raise SaveManagerError("confirmation replay history has an invalid save binding")
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "receipt save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY, order_digest),
            )
            conn.commit()

    def promote_confirmation_history_order_anchor(
        self,
        receipt: dict[str, Any],
        order_digest: str,
    ) -> None:
        save_path = normalize_required_relative(receipt.get("save_path"), "receipt save")
        save = self.require_save(refresh=False, save_path=save_path)
        if not pending_matches_save(receipt, save):
            raise SaveManagerError("confirmation replay history has an invalid save binding")
        runtime = GMRuntime.from_path(self.resolve_relative(save_path, "receipt save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (CONFIRMATION_HISTORY_ORDER_META_KEY, order_digest),
            )
            conn.execute(
                "delete from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,),
            )
            legacy_keys = [
                clean(row["key"])
                for row in conn.execute("select key from meta").fetchall()
                if clean(row["key"]).startswith(LEGACY_CONFIRMATION_HISTORY_ORDER_META_PREFIX)
                and clean(row["key"]) != CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY
            ]
            for key in legacy_keys:
                conn.execute("delete from meta where key = ?", (key,))
            conn.commit()
        self.cleanup_confirmation_history_order_anchors(keep_save_path=save_path)

    def cleanup_confirmation_history_order_anchors(self, *, keep_save_path: str = "") -> None:
        keep_path = normalize_optional_relative(keep_save_path, "receipt save") or ""
        registry = self.read_registry()
        visited: set[str] = set()
        for record in registry.get("saves", []):
            if not isinstance(record, dict):
                continue
            try:
                save_path = normalize_required_relative(record.get("path"), "receipt save")
                resolved = self.resolve_relative(save_path, "receipt save")
            except SaveManagerError:
                continue
            if save_path in visited or not resolved.is_dir():
                continue
            visited.add(save_path)
            try:
                campaign = load_campaign(resolved)
                with connect_existing_campaign_database(campaign, read_only=False) as conn:
                    keys = [clean(row["key"]) for row in conn.execute("select key from meta").fetchall()]
                    for key in keys:
                        is_order_key = key in {
                            CONFIRMATION_HISTORY_ORDER_META_KEY,
                            CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,
                        } or key.startswith(LEGACY_CONFIRMATION_HISTORY_ORDER_META_PREFIX)
                        if not is_order_key:
                            continue
                        if save_path == keep_path and key == CONFIRMATION_HISTORY_ORDER_META_KEY:
                            continue
                        conn.execute("delete from meta where key = ?", (key,))
                    conn.commit()
            except Exception as exc:
                raise SaveManagerError("confirmation replay history order anchors cannot be cleaned safely") from exc

    def validate_confirmation_history_order_anchor(
        self,
        receipts: list[dict[str, Any]],
        order_digest: str,
    ) -> None:
        if not receipts:
            raise SaveManagerError("confirmation replay history has no order authority")
        last = receipts[-1]
        save = self.require_save(refresh=False, save_path=clean(last.get("save_path")))
        if not pending_matches_save(last, save):
            raise SaveManagerError("confirmation replay history has an invalid save binding")
        campaign = load_campaign(self.resolve_relative(str(save["path"]), "receipt save"))
        with connect_existing_campaign_database(campaign, read_only=True) as conn:
            committed = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_META_KEY,),
            ).fetchone()
            prepared = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,),
            ).fetchone()
        committed_digest = committed["value"] if committed is not None else None
        prepared_digest = prepared["value"] if prepared is not None else None
        if (
            isinstance(committed_digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", committed_digest) is not None
            and committed_digest == order_digest
        ):
            self.cleanup_confirmation_history_order_anchors(
                keep_save_path=clean(last.get("save_path")),
            )
            return
        if (
            isinstance(prepared_digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", prepared_digest) is not None
            and prepared_digest == order_digest
        ):
            self.promote_confirmation_history_order_anchor(last, order_digest)
            return
        raise SaveManagerError("confirmation replay history does not match its SQLite order anchor")

    def archive_confirmation_receipt(
        self,
        receipt: dict[str, Any],
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.validate_confirmation_receipt_authority(receipt)
        receipts = list(history if history is not None else self.read_confirmation_history())
        previous_receipts = list(receipts)
        session_hash = str(receipt["confirmation_session_hash"])
        receipts = [item for item in receipts if item.get("confirmation_session_hash") != session_hash]
        receipts.append(dict(receipt))
        retained = receipts[-MAX_CONFIRMATION_HISTORY_ENTRIES:]
        retained_hashes = {str(item["confirmation_session_hash"]) for item in retained}
        for evicted in previous_receipts:
            if evicted.get("confirmation_session_hash") not in retained_hashes:
                self.delete_confirmation_receipt_anchor(evicted)
        self.write_confirmation_history(retained)

    def delete_confirmation_receipt_anchor(self, receipt: dict[str, Any]) -> None:
        session_hash = str(receipt.get("confirmation_session_hash") or "")
        receipt_digest = clean(receipt.get("receipt_digest"))
        save_path = clean(receipt.get("save_path"))
        if not session_hash or not receipt_digest or not save_path:
            raise SaveManagerError("confirmation replay receipt cannot be evicted safely")
        resolved_save = self.resolve_relative(save_path, "receipt save")
        if not resolved_save.exists():
            return
        runtime = GMRuntime.from_path(resolved_save)
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                "delete from meta where key = ? and value = ?",
                (f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{session_hash}", receipt_digest),
            )
            conn.execute(
                "delete from meta where key = ? and value = ?",
                (CONFIRMATION_RECEIPT_META_KEY, receipt_digest),
            )
            conn.commit()

    def restore_confirmation_receipt_anchor(self, receipt: dict[str, Any]) -> None:
        session_hash = str(receipt.get("confirmation_session_hash") or "")
        receipt_digest = clean(receipt.get("receipt_digest"))
        save_path = clean(receipt.get("save_path"))
        if not session_hash or not receipt_digest or not save_path:
            raise SaveManagerError("confirmation replay receipt cannot be restored safely")
        resolved_save = self.resolve_relative(save_path, "receipt save")
        if not resolved_save.exists():
            return
        runtime = GMRuntime.from_path(resolved_save)
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{session_hash}", receipt_digest),
            )
            conn.commit()

    def find_confirmation_receipt(self, session_id: str | None) -> dict[str, Any] | None:
        if session_id is not None and not pending_token_is_canonical(session_id):
            raise SaveManagerError("confirmation replay requires an exact canonical session_id")
        provided_id = session_id or ""
        if not provided_id:
            return self.read_confirmation_receipt()
        expected_hash = hash_identity(provided_id)
        history = self.read_confirmation_history()
        latest = self.read_confirmation_receipt()
        if latest is not None and latest.get("confirmation_session_hash") == expected_hash:
            return latest
        for receipt in reversed(history):
            if receipt.get("confirmation_session_hash") == expected_hash:
                return receipt
        return None

    def write_confirmation_receipt(self, receipt: dict[str, Any]) -> None:
        path = self.confirmation_receipt_path()
        ensure_under_root(self.root, path, "confirmation replay receipt")
        text = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if len(text.encode("utf-8")) > MAX_CONFIRMATION_RECEIPT_BYTES:
            raise SaveManagerError("confirmation replay receipt exceeds the bounded size limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_anchored_text(self.root, path, text, label="confirmation replay receipt")

    def clear_confirmation_receipt(self) -> None:
        path = self.confirmation_receipt_path()
        unlink_anchored_file(self.root, path, label="confirmation replay receipt")

    def write_confirmation_receipt_anchor(
        self,
        *,
        save: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        receipt_digest = clean(receipt.get("receipt_digest"))
        session_hash = str(receipt.get("confirmation_session_hash") or "")
        if not receipt_digest:
            raise SaveManagerError("confirmation replay receipt is missing its digest")
        if not session_hash:
            raise SaveManagerError("confirmation replay receipt is missing its session identity")
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (CONFIRMATION_RECEIPT_META_KEY, receipt_digest),
            )
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{session_hash}", receipt_digest),
            )
            conn.commit()

    def build_confirmation_receipt(
        self,
        *,
        session: dict[str, Any],
        save: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        delta = session.get("delta")
        proposal = session.get("turn_proposal")
        if not isinstance(delta, dict) or not isinstance(proposal, dict):
            raise SaveManagerError("pending player action is incomplete")
        claim = session.get("confirmation_claim")
        if not isinstance(claim, dict):
            raise SaveManagerError("pending confirmation claim is missing")
        command_id = clean(claim.get("command_id"))
        turn_id = clean(result.get("turn_id"))
        if not command_id or not turn_id:
            raise SaveManagerError("confirmation replay evidence is incomplete")
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
            row = conn.execute(
                """
                select t.id, t.command_hash, count(e.id) as event_count
                from turns t left join events e on e.turn_id = t.id
                where t.command_id = ?
                group by t.id, t.command_hash
                """,
                (command_id,),
            ).fetchone()
        if row is None or str(row["id"]) != turn_id or not clean(row["command_hash"]):
            raise SaveManagerError("confirmation replay evidence does not match authoritative turn state")
        receipt = {
            "schema_version": "1",
            "save_id": str(save["id"]),
            "save_path": str(save["path"]),
            "confirmation_session_hash": hash_identity(clean(session.get("session_id"))),
            "command_id": command_id,
            "command_hash": str(row["command_hash"]),
            "delta_digest": clean(claim.get("delta_digest")),
            "proposal_digest": clean(claim.get("proposal_digest")),
            "platform_hash": hash_identity(clean(session.get("platform"))) if clean(session.get("platform")) else "",
            "session_key_hash": clean(session.get("session_key_hash")),
            "actor_id_hash": clean(session.get("actor_id_hash")),
            "turn_id": turn_id,
            "event_count": int(row["event_count"]),
            "write_status": "already_confirmed",
            "projection_status": clean(result.get("projection_status")),
        }
        receipt["receipt_digest"] = stable_payload_digest(receipt)
        return receipt

    def prepare_pending_confirmation_claim(
        self,
        session: dict[str, Any],
        *,
        save: dict[str, Any],
    ) -> dict[str, Any]:
        expected = self.expected_confirmation_claim(session, save=save)
        existing = session.get("confirmation_claim")
        if existing is not None:
            if not isinstance(existing, dict):
                raise SaveManagerError("pending confirmation claim must be a JSON object")
            supplied_digest = existing.get("claim_digest")
            body = {key: value for key, value in existing.items() if key != "claim_digest"}
            if (
                set(body) != set(expected)
                or not isinstance(supplied_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", supplied_digest) is None
                or supplied_digest != stable_payload_digest(body)
            ):
                raise SaveManagerError("pending confirmation claim failed integrity validation")
            if body != expected:
                raise SaveManagerError("pending confirmation claim conflicts with pending action payload")
            self.validate_confirmation_claim_anchor(save=save, claim_digest=supplied_digest)
            return session
        claim = dict(expected)
        claim["claim_digest"] = stable_payload_digest(expected)
        self.write_confirmation_claim_anchor(save=save, claim_digest=claim["claim_digest"])
        claimed = {**session, "confirmation_claim": claim}
        self.write_pending_action(claimed)
        return claimed

    def expected_confirmation_claim(
        self,
        session: dict[str, Any],
        *,
        save: dict[str, Any],
    ) -> dict[str, Any]:
        delta = session.get("delta")
        proposal = session.get("turn_proposal")
        if not isinstance(delta, dict) or not isinstance(proposal, dict):
            raise SaveManagerError("pending player action is incomplete")
        return {
            "schema_version": "1",
            "save_id": str(save["id"]),
            "save_path": str(save["path"]),
            "confirmation_session_hash": hash_identity(clean(session.get("session_id"))),
            "command_id": clean(delta.get("command_id")),
            "delta_digest": stable_delta_digest(delta),
            "proposal_digest": stable_payload_digest(proposal),
            "platform_hash": hash_identity(clean(session.get("platform"))) if clean(session.get("platform")) else "",
            "session_key_hash": clean(session.get("session_key_hash")),
            "actor_id_hash": clean(session.get("actor_id_hash")),
        }

    def write_confirmation_claim_anchor(self, *, save: dict[str, Any], claim_digest: str) -> None:
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                """
                insert into meta(key, value) values (?, ?)
                on conflict(key) do update set value=excluded.value
                """,
                (CONFIRMATION_CLAIM_META_KEY, claim_digest),
            )
            conn.commit()

    def validate_confirmation_claim_anchor(self, *, save: dict[str, Any], claim_digest: str) -> None:
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
            row = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_CLAIM_META_KEY,),
            ).fetchone()
        anchor_digest = row["value"] if row is not None else None
        if (
            not isinstance(claim_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", claim_digest) is None
            or not isinstance(anchor_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", anchor_digest) is None
            or anchor_digest != claim_digest
        ):
            raise SaveManagerError("pending confirmation claim does not match its SQLite claim anchor")

    def rollback_new_confirmation_claim(
        self,
        *,
        save: dict[str, Any],
        original_session: dict[str, Any],
        claim_digest: str,
    ) -> None:
        self.write_pending_action(original_session)
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=False) as conn:
            conn.execute(
                "delete from meta where key = ? and value = ?",
                (CONFIRMATION_CLAIM_META_KEY, claim_digest),
            )
            conn.commit()

    def validate_confirmation_receipt(
        self,
        receipt: dict[str, Any],
        *,
        save: dict[str, Any],
        session_id: str | None,
        platform: str,
        session_key: str,
        actor_id: str,
        pending_session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_confirmation_receipt_envelope(receipt)
        validate_platform_session_pair(
            platform=platform,
            session_key=session_key,
            actor_id=actor_id,
        )
        if not pending_token_is_canonical(session_id):
            raise SaveManagerError(
                "player_confirm requires the pending action session_id returned by player_turn as an exact canonical string"
            )
        provided_session_id = session_id
        if not provided_session_id:
            raise SaveManagerError("player_confirm requires the pending action session_id returned by player_turn")
        expected_identity = {
            "save_id": str(save["id"]),
            "save_path": str(save["path"]),
            "confirmation_session_hash": hash_identity(provided_session_id),
            "platform_hash": hash_identity(clean(platform)) if clean(platform) else "",
            "session_key_hash": hash_identity(clean(session_key)) if clean(session_key) else "",
            "actor_id_hash": hash_identity(clean(actor_id)) if clean(actor_id) else "",
        }
        for key, expected in expected_identity.items():
            if receipt.get(key) != expected:
                raise SaveManagerError(f"confirmation replay conflict: {key} does not match")
        if pending_session is not None:
            pending_delta = pending_session.get("delta")
            pending_proposal = pending_session.get("turn_proposal")
            if not isinstance(pending_delta, dict) or not isinstance(pending_proposal, dict):
                raise SaveManagerError("pending player action is incomplete")
            if receipt.get("delta_digest") != stable_delta_digest(pending_delta):
                raise SaveManagerError("confirmation replay conflict: delta digest does not match")
            if receipt.get("proposal_digest") != stable_payload_digest(pending_proposal):
                raise SaveManagerError("confirmation replay conflict: proposal digest does not match")
        self.validate_confirmation_receipt_sqlite_evidence(receipt, save=save)
        return {
            "ok": True,
            "turn_id": str(receipt["turn_id"]),
            "write_status": "already_confirmed",
            "idempotent_replay": True,
            "projection_status": str(receipt["projection_status"]) or None,
            "warnings": [],
            "errors": [],
        }

    def validate_confirmation_receipt_authority(self, receipt: dict[str, Any]) -> None:
        validate_confirmation_receipt_envelope(receipt)
        save_path = str(receipt["save_path"])
        if not save_path:
            raise SaveManagerError("confirmation replay receipt is missing its save binding")
        save = self.require_save(refresh=False, save_path=save_path)
        if not pending_matches_save(receipt, save):
            raise SaveManagerError("confirmation replay receipt has an invalid save binding")
        self.validate_confirmation_receipt_sqlite_evidence(receipt, save=save)

    def validate_confirmation_receipt_sqlite_evidence(
        self,
        receipt: dict[str, Any],
        *,
        save: dict[str, Any],
    ) -> None:
        supplied_digest = str(receipt["receipt_digest"])
        if receipt.get("write_status") != "already_confirmed":
            raise SaveManagerError("confirmation replay receipt has an invalid result classification")
        expected_event_count = receipt.get("event_count")
        if type(expected_event_count) is not int or expected_event_count < 0:
            raise SaveManagerError("confirmation replay receipt has an invalid event count")
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
            row = conn.execute(
                """
                select t.id, t.command_hash, count(e.id) as event_count
                from turns t left join events e on e.turn_id = t.id
                where t.command_id = ?
                group by t.id, t.command_hash
                """,
                (str(receipt["command_id"]),),
            ).fetchone()
            anchor = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_RECEIPT_META_KEY,),
            ).fetchone()
            historical_anchor = conn.execute(
                "select value from meta where key = ?",
                (
                    f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}"
                    f"{receipt['confirmation_session_hash']}",
                ),
            ).fetchone()
        if (
            row is None
            or str(row["id"]) != receipt.get("turn_id")
            or str(row["command_hash"]) != receipt.get("command_hash")
            or int(row["event_count"]) != expected_event_count
        ):
            raise SaveManagerError("confirmation replay receipt does not match authoritative turn evidence")
        anchor_digest = anchor["value"] if anchor is not None else None
        historical_digest = historical_anchor["value"] if historical_anchor is not None else None
        latest_matches = (
            isinstance(anchor_digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", anchor_digest) is not None
            and anchor_digest == supplied_digest
        )
        historical_matches = (
            isinstance(historical_digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", historical_digest) is not None
            and historical_digest == supplied_digest
        )
        if not latest_matches and not historical_matches:
            raise SaveManagerError("confirmation replay receipt does not match its SQLite receipt anchor")

    def read_pending_clarification(self) -> dict[str, Any] | None:
        path = self.pending_clarification_path()
        return read_bounded_json_object(
            root=self.root,
            path=path,
            label="pending player clarification",
            max_bytes=MAX_PENDING_STATE_BYTES,
        )

    def write_pending_clarification(self, session: dict[str, Any]) -> None:
        path = self.pending_clarification_path()
        ensure_under_root(self.root, path, "pending clarification")
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_pending_json_shape(session)
        try:
            text = json.dumps(
                session,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n"
            encoded = text.encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise SaveManagerError(
                "pending player clarification is not safely serializable"
            ) from exc
        if len(encoded) > MAX_PENDING_STATE_BYTES:
            raise SaveManagerError("pending player clarification exceeds the bounded size limit")
        self.bump_pending_lifecycle_revision()
        write_anchored_text(self.root, path, text, label="pending player clarification")

    def clear_pending_clarification(self) -> None:
        path = self.pending_clarification_path()
        ensure_under_root(self.root, path, "pending clarification")
        if not anchored_file_exists(self.root, path):
            return
        self.bump_pending_lifecycle_revision()
        unlink_anchored_file(self.root, path, label="pending player clarification")

    def mark_played(self, save_id: str) -> None:
        with self.registry_snapshot(write=True) as registry:
            record = find_record(registry.get("saves", []), save_id)
            if record is None:
                return
            record = dict(record)
            record["last_played_at"] = utc_now()
            registry["saves"] = replace_record(registry.get("saves", []), record)

    def build_save_record(
        self,
        *,
        save_id: str,
        campaign_path: str,
        save_path: str,
        label: str,
        kind: str,
        source: str,
    ) -> dict[str, Any]:
        record = {
            "id": save_id,
            "campaign_path": campaign_path,
            "path": save_path,
            "label": label,
            "kind": kind,
            "source": source,
            "created_at": utc_now(),
            "last_played_at": None,
            "last_inspected_at": None,
            "archived": False,
            "health": "unknown",
        }
        return self.refresh_save_record(record)

    def refresh_save_record(self, record: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        try:
            save_path = self.resolve_relative(str(record.get("path", "")), "save")
            inspect = inspect_v1_save(save_path)
            location_name = location_name_from_save(save_path, inspect)
            current_location_id = str(inspect.get("current_location_id") or "")
            entry_ok = bool(inspect.get("ok"))
            safe_inspect = dict(inspect)
            safe_current_location_id = inspect.get("current_location_id")
            safe_errors = list(inspect.get("errors", []))
            safe_warnings = list(inspect.get("warnings", []))
            try:
                runtime = GMRuntime.from_path(save_path)
                with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
                    if current_location_is_player_hidden_location(conn, current_location_id):
                        current_location_error = (
                            "meta.current_location_id points to missing or unreadable location: "
                            f"{current_location_id}"
                        )
                        next_errors = [error for error in safe_errors if str(error) != current_location_error]
                        if len(next_errors) != len(safe_errors):
                            safe_errors = next_errors
                            entry_ok = not safe_errors and not inspect.get("missing_files")
                            safe_warnings.append(
                                "current location rendered with a player-safe placeholder"
                            )
                    safe_current_location_id = redact_hidden_entity_refs(
                        conn,
                        safe_current_location_id,
                        drop_empty=False,
                    )
                    safe_errors = list(redact_hidden_entity_refs(conn, safe_errors, drop_empty=False))
                    safe_warnings = list(redact_hidden_entity_refs(conn, safe_warnings, drop_empty=False))
            except Exception:
                pass
            safe_inspect["current_location_id"] = safe_current_location_id
            health = "ok" if inspect.get("ok") else "error"
            record.update(
                {
                    "campaign_id": inspect.get("campaign_id") or record.get("campaign_id", ""),
                    "campaign_name": inspect.get("campaign_name") or record.get("campaign_name", ""),
                    "current_turn_id": inspect.get("current_turn_id"),
                    "current_game_day": inspect.get("current_game_day"),
                    "current_time_block": inspect.get("current_time_block"),
                    "current_location_id": safe_current_location_id,
                    "current_location_name": location_name,
                    "summary": build_save_summary(safe_inspect, location_name),
                    "health": health,
                    "entry_ok": entry_ok,
                    "last_inspected_at": now,
                    "errors": safe_errors,
                    "warnings": safe_warnings,
                }
            )
        except Exception as exc:
            record.update(
                {
                    "health": "error",
                    "last_inspected_at": now,
                    "errors": [str(exc)],
                    "warnings": [],
                }
            )
            clear_cached_save_sensitive_fields(record)
        return record

    def scrub_cached_save_record(self, record: dict[str, Any]) -> dict[str, Any]:
        safe_record = dict(record)
        save_path = safe_record.get("path")
        if not save_path:
            return safe_record
        try:
            runtime = GMRuntime.from_path(self.resolve_relative(str(save_path), "save"))
            with connect_existing_campaign_database(runtime.campaign, read_only=True) as conn:
                for key in ("current_location_id", "current_location_name", "summary", "errors", "warnings", "error_details"):
                    if key in safe_record:
                        safe_record[key] = redact_hidden_entity_refs(conn, safe_record[key], drop_empty=False)
        except Exception:
            clear_cached_save_sensitive_fields(safe_record)
        return safe_record

    def default_save_label(self, record: dict[str, Any]) -> str:
        registry = self.read_registry()
        campaign_name = str(record.get("campaign_name") or record.get("campaign_id") or "新游戏")
        existing = [
            item
            for item in registry.get("saves", [])
            if isinstance(item, dict) and item.get("campaign_id") == record.get("campaign_id")
        ]
        return f"{campaign_name} · 新游戏 {len(existing) + 1}"

    def resolve_campaign_path(self, campaign: str | None = None) -> str:
        value = normalize_optional_relative(campaign, "campaign") or self.default_campaign
        registry = self.read_registry()
        if not value and len(registry.get("campaigns", [])) == 1:
            value = str(registry["campaigns"][0].get("path", ""))
        if not value:
            raise SaveManagerError("campaign is required because no default campaign is configured")
        return normalize_required_relative(value, "campaign")

    def resolve_starter_path(self, campaign_id: str, starter_save: str | None = None) -> str | None:
        explicit = normalize_optional_relative(starter_save, "starter_save")
        if explicit:
            return explicit
        registry = self.read_registry()
        for record in registry.get("campaigns", []):
            if isinstance(record, dict) and record.get("id") == campaign_id:
                value = normalize_optional_relative(record.get("starter_save_path"), "starter_save")
                if value:
                    return value
        return self.default_starter_save

    def resolve_relative(self, value: str, label: str) -> Path:
        relative = normalize_required_relative(value, label)
        candidate = (self.root / relative).resolve()
        ensure_under_root(self.root, candidate, label)
        return candidate

    def read_registry(self) -> dict[str, Any]:
        try:
            raw = read_registry_bytes_anchored(
                self.root,
                self.registry_path,
                max_bytes=MAX_REGISTRY_STATE_BYTES,
            )
            if raw is None:
                return empty_registry()
            data = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=reject_duplicate_registry_json_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    SaveManagerError("registry contains a non-finite number")
                ),
            )
            validate_pending_json_shape(data)
        except SaveManagerError as exc:
            raise SaveManagerError(f"registry is invalid JSON: {exc}") from exc
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise SaveManagerError(f"registry is invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise SaveManagerError("registry must be a JSON object")
        if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise SaveManagerError(
                f"registry schema_version must be {REGISTRY_SCHEMA_VERSION}, got {data.get('schema_version')}"
            )
        data.setdefault("active_save_id", None)
        data.setdefault("campaigns", [])
        data.setdefault("saves", [])
        if not isinstance(data["campaigns"], list) or not isinstance(data["saves"], list):
            raise SaveManagerError("registry campaigns and saves must be arrays")
        validate_registry_document(data)
        return data

    def write_registry(self, registry: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
        with registry_lock(lock_path, root=self.root):
            self.write_registry_unlocked(registry)

    @contextmanager
    def registry_snapshot(self, *, write: bool) -> Iterator[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
        with registry_lock(lock_path, root=self.root):
            registry = self.read_registry()
            yield registry
            if write:
                self.write_registry_unlocked(registry)

    def write_registry_unlocked(self, registry: dict[str, Any]) -> None:
        validate_registry_document(registry)
        normalized = normalize_registry(registry)
        validate_pending_json_shape(normalized)
        try:
            text = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            encoded = text.encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise SaveManagerError("registry cannot be serialized safely") from exc
        if len(encoded) > MAX_REGISTRY_STATE_BYTES:
            raise SaveManagerError("registry exceeds the bounded size limit")
        write_registry_bytes_anchored(
            self.root,
            self.registry_path,
            encoded,
        )

    def merge_registry_save_record(self, record: dict[str, Any]) -> dict[str, Any]:
        expected_path = normalize_required_relative(record.get("path"), "save")
        expected_id = clean(record.get("id"))
        with self.registry_snapshot(write=True) as registry:
            latest = find_save_record_by_path(registry.get("saves", []), expected_path)
            if latest is None or (expected_id and clean(latest.get("id")) != expected_id):
                raise SaveManagerError("save binding changed before registry refresh")
            if bool(latest.get("archived")):
                raise SaveManagerError(f"save is archived: {latest.get('id') or expected_path}")
            path_errors = registry_record_path_errors(self.root, [latest], "save")
            if path_errors:
                raise SaveManagerError("; ".join(path_errors))
            refreshed = self.refresh_save_record(dict(latest))
            registry["saves"] = replace_record(registry.get("saves", []), refreshed)
            return refreshed


def empty_registry() -> dict[str, Any]:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "active_save_id": None, "campaigns": [], "saves": []}


def validate_registry_document(registry: Any) -> None:
    if not isinstance(registry, dict):
        raise SaveManagerError("registry must be a JSON object")
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise SaveManagerError(
            f"registry schema_version must be the string {REGISTRY_SCHEMA_VERSION}"
        )
    active_save_id = registry.get("active_save_id")
    if active_save_id is not None and not canonical_registry_string(
        active_save_id,
        allow_empty=False,
    ):
        raise SaveManagerError("registry active_save_id must be a canonical string or null")
    for collection, record_kind in (("campaigns", "campaign"), ("saves", "save")):
        records = registry.get(collection, [])
        if not isinstance(records, list):
            raise SaveManagerError("registry campaigns and saves must be arrays")
        for record in records:
            if not isinstance(record, dict):
                raise SaveManagerError(f"registry {collection} entries must be JSON objects")
            for field in ("id", "path"):
                if not canonical_registry_string(record.get(field), allow_empty=False):
                    raise SaveManagerError(
                        f"{record_kind} registry {field} must be a canonical string"
                    )
            optional_path = "starter_save_path" if record_kind == "campaign" else "campaign_path"
            if optional_path in record and record[optional_path] is not None and not canonical_registry_string(
                record[optional_path],
                allow_empty=True,
            ):
                raise SaveManagerError(
                    f"{record_kind} registry {optional_path} must be a canonical string or null"
                )


def canonical_registry_string(value: Any, *, allow_empty: bool) -> bool:
    if not identity_input_is_bounded_utf8(value) or value != clean(value):
        return False
    return allow_empty or bool(value)


def normalize_registry(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "active_save_id": registry.get("active_save_id"),
        "campaigns": [dict(item) for item in registry.get("campaigns", []) if isinstance(item, dict)],
        "saves": [dict(item) for item in registry.get("saves", []) if isinstance(item, dict)],
    }


def current_save_authority(*, refresh: bool) -> dict[str, Any]:
    return {
        "record_source": "workspace_registry",
        "summary_source": "data/game.sqlite" if refresh else "registry_cache",
        "summary_authoritative": bool(refresh),
        "fact_authority": "data/game.sqlite",
    }


@contextmanager
def connect_existing_campaign_database(
    campaign: Any,
    *,
    read_only: bool,
) -> Iterator[sqlite3.Connection]:
    database_path = Path(campaign.database_path)
    if not database_path.is_file():
        raise SaveManagerError("registered save fact database is missing")
    mode = "ro" if read_only else "rw"
    try:
        conn = sqlite3.connect(
            f"{database_path.as_uri()}?mode={mode}",
            uri=True,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 5000")
    except sqlite3.Error as exc:
        raise SaveManagerError("registered save fact database cannot be opened safely") from exc
    try:
        yield conn
    except sqlite3.Error as exc:
        raise SaveManagerError("registered save fact database operation failed") from exc
    finally:
        conn.close()


def registry_record_path_errors(root: Path, records: list[dict[str, Any]], record_kind: str) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for record in records:
        record_id = clean(record.get("id"))
        display_id = record_id or "<unknown>"
        if record_id:
            if record_id in seen_ids:
                errors.append(f"{record_kind} registry contains duplicate id: {record_id}")
            seen_ids.add(record_id)
        for field, required in registry_path_fields(record_kind):
            try:
                relative = validate_registry_record_relative(
                    root,
                    record.get(field),
                    f"{record_kind}.{field}",
                    required=required,
                )
            except SaveManagerError as exc:
                errors.append(f"{record_kind} registry record {display_id} {field}: {exc}")
                continue
            if field == "path" and relative:
                if relative in seen_paths:
                    errors.append(f"{record_kind} registry contains duplicate path: {relative}")
                seen_paths.add(relative)
    return errors


def registry_path_fields(record_kind: str) -> tuple[tuple[str, bool], ...]:
    if record_kind == "campaign":
        return (("path", True), ("starter_save_path", False))
    if record_kind == "save":
        return (("path", True), ("campaign_path", False))
    return (("path", True),)


def validate_registry_record_relative(root: Path, value: Any, label: str, *, required: bool) -> str | None:
    relative = normalize_required_relative(value, label) if required else normalize_optional_relative(value, label)
    if relative is None:
        return None
    candidate = (root / relative).resolve()
    ensure_under_root(root, candidate, label)
    return relative


def thread_local_lock_depths(state: threading.local) -> dict[str, int]:
    current_pid = os.getpid()
    if getattr(state, "pid", None) != current_pid:
        state.pid = current_pid
        state.depths = {}
    return state.depths


@contextmanager
def confirmation_claim_lock(
    path: Path,
    *,
    root: Path | None = None,
    timeout: float = 10.0,
) -> Iterator[None]:
    lock_key = str(path.resolve())
    with process_file_lock(
        path,
        root=root,
        timeout=timeout,
        unavailable_message="pending confirmation claim is unavailable",
        timeout_message="timed out waiting for pending confirmation claim",
    ):
        depths = thread_local_lock_depths(_CONFIRMATION_LOCK_STATE)
        depths[lock_key] = depths.get(lock_key, 0) + 1
        try:
            yield
        finally:
            remaining = depths.get(lock_key, 0) - 1
            if remaining > 0:
                depths[lock_key] = remaining
            else:
                depths.pop(lock_key, None)


def confirmation_lock_held_by_current_thread(path: Path) -> bool:
    depths = thread_local_lock_depths(_CONFIRMATION_LOCK_STATE)
    return depths.get(str(path.resolve()), 0) > 0


@contextmanager
def process_file_lock(
    path: Path,
    *,
    unavailable_message: str,
    timeout_message: str,
    root: Path | None = None,
    timeout: float = 10.0,
) -> Iterator[None]:
    acquisition_pid = os.getpid()
    directory_fd = -1
    authority_fd = -1
    fd = -1
    authority_acquired = False
    authority_opened: os.stat_result | None = None
    authority_name = ""
    authority_key = (
        f"{root}:{path}"
        if root is not None and os.name != "nt"
        else ""
    )
    authority_depths = thread_local_lock_depths(_WORKSPACE_LOCK_STATE)
    authority_reentrant = bool(authority_key and authority_depths.get(authority_key, 0) > 0)
    try:
        if root is not None:
            ensure_under_root(root, path, "process lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = (
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if root is not None and os.name != "nt":
            directory_fd, name = open_registry_parent_anchored(root, path)
            fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise SaveManagerError(unavailable_message)
            authority_name = f".{name}.authority"
            authority_fd = os.open(
                authority_name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
            authority_opened = os.fstat(authority_fd)
            if not stat.S_ISREG(authority_opened.st_mode):
                raise SaveManagerError(unavailable_message)
            if not registry_parent_matches(root, path, directory_fd) or not registry_file_matches(
                directory_fd,
                name,
                opened,
            ) or not registry_file_matches(directory_fd, authority_name, authority_opened):
                raise SaveManagerError(unavailable_message)
        else:
            fd = os.open(path, flags, 0o600)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SaveManagerError(unavailable_message)
    except (OSError, SaveManagerError) as exc:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.close(directory_fd)
        except OSError:
            pass
        try:
            os.close(authority_fd)
        except OSError:
            pass
        raise SaveManagerError(unavailable_message) from exc
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        if authority_fd >= 0 and not authority_reentrant:
            while True:
                try:
                    acquire_confirmation_file_lock(authority_fd)
                    authority_acquired = True
                    authority_depths[authority_key] = authority_depths.get(authority_key, 0) + 1
                    break
                except (OSError, SaveManagerError) as exc:
                    if isinstance(exc, SaveManagerError):
                        raise SaveManagerError(unavailable_message) from exc
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise SaveManagerError(unavailable_message) from exc
                    if time.monotonic() >= deadline:
                        raise SaveManagerError(timeout_message) from exc
                    time.sleep(0.05)
        while True:
            try:
                if not authority_reentrant:
                    acquire_confirmation_file_lock(fd)
                    acquired = True
                if root is not None and os.name != "nt":
                    if not registry_parent_matches(
                        root,
                        path,
                        directory_fd,
                    ) or not registry_file_matches(
                        directory_fd,
                        name,
                        opened,
                    ) or authority_opened is None or not registry_file_matches(
                        directory_fd,
                        authority_name,
                        authority_opened,
                    ):
                        raise SaveManagerError(unavailable_message)
                break
            except (OSError, SaveManagerError) as exc:
                if isinstance(exc, SaveManagerError):
                    raise SaveManagerError(unavailable_message) from exc
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise SaveManagerError(unavailable_message) from exc
                if time.monotonic() >= deadline:
                    raise SaveManagerError(timeout_message) from exc
                time.sleep(0.05)
        yield
    finally:
        same_process = os.getpid() == acquisition_pid
        if acquired and same_process:
            try:
                release_confirmation_file_lock(fd)
            except OSError:
                pass
        if authority_acquired and same_process:
            try:
                release_confirmation_file_lock(authority_fd)
            except OSError:
                pass
            remaining = authority_depths.get(authority_key, 0) - 1
            if remaining > 0:
                authority_depths[authority_key] = remaining
            else:
                authority_depths.pop(authority_key, None)
        try:
            os.close(fd)
        except OSError:
            pass
        if directory_fd >= 0:
            try:
                os.close(directory_fd)
            except OSError:
                pass
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass


def acquire_confirmation_file_lock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is None:  # pragma: no cover - supported platforms provide one implementation.
        raise SaveManagerError("process-safe confirmation lock is unavailable")
    if os.fstat(fd).st_size == 0:
        os.write(fd, b"\0")
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def release_confirmation_file_lock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    if msvcrt is None:  # pragma: no cover - supported platforms provide one implementation.
        return
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def registry_lock(path: Path, *, root: Path | None = None, timeout: float = 10.0) -> Iterator[None]:
    with process_file_lock(
        path,
        root=root,
        timeout=timeout,
        unavailable_message="save registry lock is unavailable",
        timeout_message="timed out waiting for save registry lock",
    ):
        yield


def resolve_registry_path(root: Path, registry_path: str | Path | None) -> Path:
    if registry_path is None:
        candidate = root / DEFAULT_REGISTRY_RELATIVE
    else:
        raw = str(registry_path).strip()
        if not raw:
            raise SaveManagerError("registry_path is required")
        if "\\" in raw:
            raise SaveManagerError("registry_path must not contain backslashes")
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            raise SaveManagerError("registry_path must be relative to the workspace root")
        if candidate == Path("."):
            raise SaveManagerError("registry_path must be a file path")
        if ".." in candidate.parts:
            raise SaveManagerError("registry_path must not contain '..'")
        candidate = root / candidate
    ensure_under_root(root, candidate, "registry_path")
    return candidate


def normalize_optional_relative(value: Any, label: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return normalize_required_relative(raw, label)


def normalize_required_relative(value: Any, label: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise SaveManagerError(f"{label} is required")
    if "\\" in raw:
        raise SaveManagerError(f"{label} must not contain backslashes")
    path = Path(raw)
    if path.is_absolute():
        raise SaveManagerError(f"{label} must be relative to the workspace root")
    if ".." in path.parts:
        raise SaveManagerError(f"{label} must not contain '..'")
    return path.as_posix()


def ensure_under_root(root: Path, candidate: Path, label: str) -> None:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise SaveManagerError(f"{label} escapes workspace root")


def ensure_registry_path_is_local_file(
    root: Path,
    path: Path,
    *,
    allow_missing: bool,
) -> None:
    if path.is_symlink():
        raise SaveManagerError("registry path must not be a symbolic link")
    ensure_under_root(root, path, "registry_path")
    if not path.exists():
        if allow_missing:
            return
        raise SaveManagerError("registry path is unavailable")
    if not path.is_file():
        raise SaveManagerError("registry path must be a regular file")


def open_registry_parent_anchored(root: Path, path: Path) -> tuple[int, str]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SaveManagerError("registry_path escapes workspace root") from exc
    if not relative.parts or relative.name in {"", ".", ".."}:
        raise SaveManagerError("registry_path must be a file path")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(root, flags)
        for part in relative.parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
    except OSError as exc:
        try:
            os.close(directory_fd)
        except (OSError, UnboundLocalError):
            pass
        raise SaveManagerError("registry parent path is unavailable") from exc
    return directory_fd, relative.name


def registry_parent_matches(root: Path, path: Path, directory_fd: int) -> bool:
    try:
        current_fd, _ = open_registry_parent_anchored(root, path)
    except SaveManagerError:
        return False
    try:
        expected = os.fstat(directory_fd)
        current = os.fstat(current_fd)
        return (expected.st_dev, expected.st_ino) == (current.st_dev, current.st_ino)
    finally:
        os.close(current_fd)


def registry_file_stat(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(current.st_mode):
        raise SaveManagerError("registry path must be a regular file")
    return current


def registry_file_matches(
    directory_fd: int,
    name: str,
    expected: os.stat_result | None,
) -> bool:
    try:
        current = registry_file_stat(directory_fd, name)
    except SaveManagerError:
        return False
    if expected is None or current is None:
        return expected is current
    return (expected.st_dev, expected.st_ino) == (current.st_dev, current.st_ino)


def read_registry_bytes_anchored(
    root: Path,
    path: Path,
    *,
    max_bytes: int,
) -> bytes | None:
    if path.parent.is_symlink():
        raise SaveManagerError("registry parent path must not be a symbolic link")
    if not path.parent.exists():
        ensure_under_root(root, path, "registry_path")
        return None
    if os.name == "nt":  # pragma: no cover - Windows lacks dir_fd support.
        ensure_registry_path_is_local_file(root, path, allow_missing=True)
        if not path.exists():
            return None
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise SaveManagerError("registry exceeds the bounded size limit")
        return raw
    directory_fd, name = open_registry_parent_anchored(root, path)
    file_fd = -1
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            if not registry_parent_matches(root, path, directory_fd):
                raise SaveManagerError("registry path changed while being read")
            return None
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise SaveManagerError("registry path must be a regular file")
        raw = bytearray()
        while len(raw) <= max_bytes:
            chunk = os.read(file_fd, min(65536, max_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > max_bytes:
            raise SaveManagerError("registry exceeds the bounded size limit")
        if not registry_parent_matches(root, path, directory_fd) or not registry_file_matches(
            directory_fd,
            name,
            opened,
        ):
            raise SaveManagerError("registry path changed while being read")
        return bytes(raw)
    except OSError as exc:
        raise SaveManagerError("registry path is unavailable") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)


def write_registry_bytes_anchored(root: Path, path: Path, data: bytes) -> None:
    if os.name == "nt":  # pragma: no cover - Windows lacks dir_fd support.
        ensure_registry_path_is_local_file(root, path, allow_missing=True)
        write_text_atomic(path, data.decode("utf-8"))
        return
    directory_fd, name = open_registry_parent_anchored(root, path)
    temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
    temporary_fd = -1
    temporary_identity: os.stat_result | None = None
    replaced = False
    try:
        existing = registry_file_stat(directory_fd, name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        temporary_fd = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        view = memoryview(data)
        while view:
            written = os.write(temporary_fd, view)
            view = view[written:]
        if existing is not None:
            os.fchmod(temporary_fd, existing.st_mode & 0o777)
        os.fsync(temporary_fd)
        temporary_identity = os.fstat(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = -1
        if not registry_parent_matches(root, path, directory_fd) or not registry_file_matches(
            directory_fd,
            name,
            existing,
        ):
            raise SaveManagerError("registry path changed before publication")
        os.replace(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replaced = True
        published = registry_file_stat(directory_fd, name)
        if (
            published is None
            or temporary_identity is None
            or (published.st_dev, published.st_ino)
            != (temporary_identity.st_dev, temporary_identity.st_ino)
            or not registry_parent_matches(
                root,
                path,
                directory_fd,
            )
            or not registry_file_matches(directory_fd, name, temporary_identity)
        ):
            raise SaveManagerError("registry path changed during publication")
        os.fsync(directory_fd)
        if not registry_parent_matches(
            root,
            path,
            directory_fd,
        ) or not registry_file_matches(directory_fd, name, temporary_identity):
            raise SaveManagerError("registry path changed during publication")
    except (OSError, SaveManagerError) as exc:
        if replaced:
            raise RegistryPublicationUncertain(
                "registry replacement completed but durability is uncertain"
            ) from exc
        if isinstance(exc, SaveManagerError):
            raise
        raise SaveManagerError("registry publication failed") from exc
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def write_anchored_text(root: Path, path: Path, text: str, *, label: str) -> None:
    try:
        data = text.encode("utf-8")
        write_registry_bytes_anchored(root, path, data)
    except (OSError, UnicodeError, SaveManagerError) as exc:
        raise SaveManagerError(f"{label} publication failed") from exc


def anchored_file_exists(root: Path, path: Path) -> bool:
    if os.name == "nt":  # pragma: no cover - Windows lacks dir_fd support.
        ensure_registry_path_is_local_file(root, path, allow_missing=True)
        return path.exists()
    if path.parent.is_symlink():
        raise SaveManagerError("canonical evidence parent must not be a symbolic link")
    if not path.parent.exists():
        ensure_under_root(root, path, "canonical evidence")
        return False
    directory_fd, name = open_registry_parent_anchored(root, path)
    try:
        current = registry_file_stat(directory_fd, name)
        if not registry_parent_matches(root, path, directory_fd):
            raise SaveManagerError("canonical evidence path changed while being checked")
        return current is not None
    finally:
        os.close(directory_fd)


def unlink_anchored_file(root: Path, path: Path, *, label: str) -> None:
    if os.name == "nt":  # pragma: no cover - Windows lacks dir_fd support.
        if not anchored_file_exists(root, path):
            return
        try:
            path.unlink()
        except OSError as exc:
            raise SaveManagerError(f"{label} removal failed") from exc
        return
    directory_fd, name = open_registry_parent_anchored(root, path)
    quarantine_name = f".{name}.{uuid.uuid4().hex}.remove"
    try:
        existing = registry_file_stat(directory_fd, name)
        if existing is None:
            return
        if not registry_parent_matches(root, path, directory_fd) or not registry_file_matches(
            directory_fd,
            name,
            existing,
        ):
            raise SaveManagerError(f"{label} path changed before removal")
        os.rename(
            name,
            quarantine_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        try:
            quarantined = os.stat(
                quarantine_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            quarantined = None
        if (
            quarantined is None
            or not stat.S_ISREG(quarantined.st_mode)
            or (quarantined.st_dev, quarantined.st_ino) != (existing.st_dev, existing.st_ino)
        ):
            if quarantined is not None:
                try:
                    os.link(
                        quarantine_name,
                        name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    os.unlink(quarantine_name, dir_fd=directory_fd)
                except OSError:
                    pass
            raise SaveManagerError(f"{label} path changed before removal")
        if not registry_parent_matches(root, path, directory_fd):
            raise SaveManagerError(f"{label} path changed during removal")
        quarantined = os.stat(
            quarantine_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(quarantined.st_mode)
            or (quarantined.st_dev, quarantined.st_ino) != (existing.st_dev, existing.st_ino)
        ):
            raise SaveManagerError(f"{label} path changed during removal")
        os.unlink(quarantine_name, dir_fd=directory_fd)
        if not registry_parent_matches(root, path, directory_fd):
            raise SaveManagerError(f"{label} path changed during removal")
        try:
            remaining = registry_file_stat(
                directory_fd,
                name,
            )
        except SaveManagerError as exc:
            raise SaveManagerError(f"{label} path changed during removal") from exc
        if remaining is not None:
            raise SaveManagerError(f"{label} path changed during removal")
        os.fsync(directory_fd)
    except SaveManagerError:
        raise
    except OSError as exc:
        raise SaveManagerError(f"{label} removal failed") from exc
    finally:
        os.close(directory_fd)


def ensure_empty_target(path: Path) -> None:
    if path.exists() and path.is_file():
        raise FileExistsError(f"save target is a file: {path}")
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"save directory is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def directory_entry_identity(path: Path) -> tuple[int, int]:
    current = path.lstat()
    if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise SaveManagerError("created Save target is not a local directory")
    return current.st_dev, current.st_ino


def remove_created_directory_if_unchanged(
    root: Path,
    path: Path,
    expected_identity: tuple[int, int],
) -> None:
    if os.name == "nt":  # pragma: no cover - Windows lacks dir_fd support.
        try:
            current = path.lstat()
        except FileNotFoundError:
            return
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            return
        shutil.rmtree(path)
        return
    try:
        directory_fd, name = open_registry_parent_anchored(root, path)
    except SaveManagerError:
        return
    quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
    try:
        try:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            return
        os.rename(
            name,
            quarantine_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        quarantined = os.stat(
            quarantine_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(quarantined.st_mode)
            or stat.S_ISLNK(quarantined.st_mode)
            or (quarantined.st_dev, quarantined.st_ino) != expected_identity
        ):
            try:
                os.rename(
                    quarantine_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except OSError:
                pass
            return
        if not registry_parent_matches(root, path, directory_fd):
            return
        quarantined = os.stat(
            quarantine_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(quarantined.st_mode)
            or stat.S_ISLNK(quarantined.st_mode)
            or (quarantined.st_dev, quarantined.st_ino) != expected_identity
        ):
            return
        shutil.rmtree(quarantine_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except (FileNotFoundError, OSError, SaveManagerError):
        return
    finally:
        os.close(directory_fd)


def make_save_id() -> str:
    stamp = re.sub(r"[^0-9]", "", utc_now())[:14]
    return f"save_{stamp}_{uuid.uuid4().hex[:8]}"


def make_save_target_relative(campaign_id: str, save_id: str) -> str:
    safe_campaign = slugify(campaign_id or "campaign")
    return f"{DEFAULT_SAVES_DIR}/{safe_campaign}/{save_id}"


def slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return text or "campaign"


def find_record(records: Any, record_id: str) -> dict[str, Any] | None:
    if not isinstance(records, list):
        return None
    for record in records:
        if isinstance(record, dict) and str(record.get("id", "")) == record_id:
            return record
    return None


def find_save_record_by_path(records: Any, save_path: str) -> dict[str, Any] | None:
    normalized = normalize_required_relative(save_path, "save")
    if not isinstance(records, list):
        return None
    for record in records:
        if isinstance(record, dict) and normalize_optional_relative(record.get("path"), "save") == normalized:
            return record
    return None


def replace_record(records: Any, record: dict[str, Any]) -> list[dict[str, Any]]:
    items = [dict(item) for item in records if isinstance(item, dict) and item.get("id") != record.get("id")]
    items.append(record)
    return sorted(items, key=lambda item: str(item.get("id", "")))


def pending_action_expires_at(*, ttl_seconds: int = DEFAULT_PENDING_ACTION_TTL_SECONDS) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()


def pending_action_expires_at_from_created(
    created_at: str,
    *,
    ttl_seconds: int = DEFAULT_PENDING_ACTION_TTL_SECONDS,
) -> str:
    created = parse_canonical_utc_datetime(created_at)
    if created is None:
        raise SaveManagerError("pending player session has an invalid creation time")
    try:
        return (created + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()
    except OverflowError:
        raise SaveManagerError("pending player session has an invalid TTL") from None


def pending_action_is_expired(session: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires_at = clean(session.get("expires_at"))
    if not expires_at:
        created_at = clean(session.get("created_at"))
        if not created_at:
            return False
        try:
            ttl_seconds = int(session.get("ttl_seconds") or DEFAULT_PENDING_ACTION_TTL_SECONDS)
        except (TypeError, ValueError):
            return True
        created = parse_datetime(created_at)
        if created is None:
            return True
        deadline = created + timedelta(seconds=max(1, ttl_seconds))
    else:
        deadline = parse_datetime(expires_at)
        if deadline is None:
            return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return deadline <= current


def parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_canonical_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or value != clean(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.isoformat() != value
    ):
        return None
    return parsed


def platform_session_metadata(*, platform: str, session_key: str, actor_id: str = "") -> dict[str, Any]:
    validate_platform_session_pair(
        platform=platform,
        session_key=session_key,
        actor_id=actor_id,
    )
    data: dict[str, Any] = {}
    platform_value = clean(platform)
    session_value = clean(session_key)
    actor_value = clean(actor_id)
    if platform_value:
        data["platform"] = platform_value
    if session_value:
        data["session_key_hash"] = hash_identity(session_value)
    if actor_value:
        data["actor_id_hash"] = hash_identity(actor_value)
    return data


def identity_input_is_bounded_utf8(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > MAX_PENDING_STRING_LENGTH:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def player_identity_inputs_are_valid(
    *,
    platform: Any,
    session_key: Any,
    actor_id: Any = "",
) -> bool:
    if not all(
        identity_input_is_bounded_utf8(value)
        for value in (platform, session_key, actor_id)
    ):
        return False
    return bool(clean(platform)) == bool(clean(session_key))


def validate_platform_session_pair(
    *,
    platform: str,
    session_key: str,
    actor_id: str = "",
) -> None:
    if not player_identity_inputs_are_valid(
        platform=platform,
        session_key=session_key,
        actor_id=actor_id,
    ):
        if not all(
            identity_input_is_bounded_utf8(value)
            for value in (platform, session_key, actor_id)
        ):
            raise SaveManagerError("platform identity values must be bounded valid UTF-8 strings")
        raise SaveManagerError("platform and session_key must be provided together")


def pending_session_id(kind: str, pending: dict[str, Any] | None) -> str:
    if pending is None:
        return ""
    key = "session_id" if kind == "action" else "clarification_id"
    return clean(pending.get(key))


def pending_token_is_canonical_or_empty(value: Any) -> bool:
    return value == "" or pending_token_is_canonical(value)


def pending_token_is_canonical(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != clean(value)
        or len(value) > MAX_PENDING_STRING_LENGTH
    ):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def pending_generation_digest(kind: str, pending: dict[str, Any] | None) -> str:
    if pending is None:
        return ""
    return stable_payload_digest({"kind": kind, "pending": pending})


def pending_session_identity_matches(
    pending: dict[str, Any],
    *,
    platform: str,
    session_key: str,
    actor_id: str,
    supplied_hashes: bool = False,
    session_key_hash: str = "",
    actor_id_hash: str = "",
) -> bool:
    if supplied_hashes:
        if not all(
            identity_input_is_bounded_utf8(value)
            for value in (platform, session_key_hash, actor_id_hash)
        ) or bool(clean(platform)) != bool(clean(session_key_hash)):
            return False
    elif not player_identity_inputs_are_valid(
        platform=platform,
        session_key=session_key,
        actor_id=actor_id,
    ):
        return False
    pending_identity = (
        clean(pending.get("platform")),
        clean(pending.get("session_key_hash")),
        clean(pending.get("actor_id_hash")),
    )
    supplied_identity = (
        clean(platform),
        clean(session_key_hash) if supplied_hashes else (hash_identity(clean(session_key)) if clean(session_key) else ""),
        clean(actor_id_hash) if supplied_hashes else (hash_identity(clean(actor_id)) if clean(actor_id) else ""),
    )
    return pending_identity == supplied_identity


def pending_matches_save(pending: dict[str, Any], save: dict[str, Any]) -> bool:
    try:
        pending_path = normalize_required_relative(pending.get("save_path"), "pending save")
        save_path = normalize_required_relative(save.get("path"), "save")
    except SaveManagerError:
        return False
    return clean(pending.get("save_id")) == clean(save.get("id")) and pending_path == save_path


def exact_save_record_matches(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return (
        isinstance(first.get("id"), str)
        and isinstance(first.get("path"), str)
        and first.get("id") == second.get("id")
        and first.get("path") == second.get("path")
    )


def pending_lifecycle_projection(
    kind: str,
    pending: dict[str, Any] | None,
    *,
    state: str,
    include_pending_id: bool = False,
) -> dict[str, Any]:
    lifecycle: dict[str, Any] = {"state": state, "kind": kind}
    if pending is None:
        return lifecycle
    if include_pending_id:
        pending_id = pending_session_id(kind, pending)
        if pending_id:
            lifecycle["pending_id"] = pending_id
    for key in ("save_id", "created_at", "expires_at", "ttl_seconds", "clarification_origin"):
        value = pending.get(key)
        if value not in (None, ""):
            lifecycle[key] = value
    return lifecycle


def pending_conflict_result(
    *,
    save: dict[str, Any],
    kind: str,
    pending: dict[str, Any] | None,
    same_identity: bool,
    message: str,
    state: str = "conflict",
) -> dict[str, Any]:
    del message
    public_message = "another player request is waiting for an explicit lifecycle decision"
    return {
        "ok": False,
        "active_save_id": save.get("id"),
        "status": "pending_conflict" if state == "conflict" else state,
        "ready_to_confirm": False,
        "session_id": None,
        "pending_clarification_id": None,
        "saved": False,
        "lifecycle": pending_lifecycle_projection(
            kind or "unknown",
            pending,
            state=state,
            include_pending_id=same_identity,
        ) if same_identity else {"state": state, "kind": kind or "unknown"},
        "warnings": [],
        "errors": [public_message],
    }


def pending_terminal_result(
    *,
    save: dict[str, Any],
    kind: str,
    pending: dict[str, Any],
    state: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "active_save_id": save.get("id"),
        "status": state,
        "ready_to_confirm": False,
        "session_id": None,
        "pending_clarification_id": None,
        "saved": False,
        "lifecycle": pending_lifecycle_projection(kind, pending, state=state),
        "warnings": [],
        "errors": [],
    }


def pending_cancel_conflict(kind: str, pending: dict[str, Any], message: str) -> dict[str, Any]:
    del pending, message
    return {
        "ok": False,
        "status": "conflict",
        "saved": False,
        "lifecycle": {"state": "conflict", "kind": kind},
        "errors": ["another player request is waiting for an explicit lifecycle decision"],
    }


def pending_clarification_waiting_result(*, save: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "active_save_id": save.get("id"),
        "status": "needs_clarification",
        "ready_to_confirm": False,
        "session_id": None,
        "clarification": pending.get("clarification"),
        "pending_clarification_id": pending_session_id("clarification", pending),
        "saved": False,
        "lifecycle": pending_lifecycle_projection(
            "clarification",
            pending,
            state="active",
            include_pending_id=True,
        ),
        "warnings": [],
        "errors": [],
    }


def clarification_origin_for_result(
    result: dict[str, Any],
    *,
    external_intent_candidate: dict[str, Any] | None,
) -> str:
    if not isinstance(external_intent_candidate, dict):
        return "player_input_ambiguity"
    interpretation = result.get("interpretation")
    intent = interpretation.get("intent") if isinstance(interpretation, dict) else None
    if not isinstance(intent, dict):
        return "player_input_ambiguity"
    source = clean(intent.get("source"))
    agreement = clean(intent.get("agreement_with_external"))
    quality = clean(intent.get("external_candidate_quality"))
    semantic_mismatch_qualities = {"incomplete", "wrong_action", "wrong_mode", "wrong_slots"}
    if source == "candidate_contract_mismatch" or (
        source == "ai_disagreement"
        and agreement == "disagree"
        and quality in semantic_mismatch_qualities
    ):
        return "candidate_contract_mismatch"
    return "player_input_ambiguity"


def clarification_correction_is_allowed(
    pending: dict[str, Any],
    *,
    expected_pending_id: str,
    clarification_id: str,
    external_intent_candidate: dict[str, Any] | None,
) -> bool:
    current_id = pending_session_id("clarification", pending)
    if (
        clean(pending.get("clarification_origin")) != "candidate_contract_mismatch"
        or not current_id
        or expected_pending_id != current_id
        or clarification_id != current_id
        or not isinstance(external_intent_candidate, dict)
    ):
        return False
    previous_digest = clean(pending.get("external_candidate_digest"))
    return bool(previous_digest and stable_payload_digest(external_intent_candidate) != previous_digest)


def validate_clarification_payload_privacy(
    clarification: dict[str, Any],
    *,
    session_key: str = "",
    actor_id: str = "",
    session_key_hash: str = "",
    actor_id_hash: str = "",
) -> None:
    validate_pending_json_shape(clarification)
    forbidden_identity_keys = {
        "sessionkey",
        "sessionkeyhash",
        "actorid",
        "actoridhash",
    }
    raw_identity_values = frozenset(
        clean(value)
        for value in (session_key, actor_id)
        if isinstance(value, str) and clean(value)
    )
    identity_hashes = frozenset(
        value
        for value in (session_key_hash, actor_id_hash)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
    )

    def is_raw_identity(value: str) -> bool:
        normalized = clean(value)
        return bool(
            normalized
            and (
                normalized in raw_identity_values
                or (identity_hashes and hash_identity(normalized) in identity_hashes)
            )
        )

    stack: list[Any] = [clarification]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
                if normalized_key in forbidden_identity_keys or is_raw_identity(key):
                    raise SaveManagerError(
                        "pending player clarification contains raw identity fields"
                    )
                stack.append(item)
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str) and is_raw_identity(value):
            raise SaveManagerError(
                "pending player clarification contains raw identity values"
            )


def validate_pending_envelope(kind: str, pending: dict[str, Any], *, allow_legacy: bool = False) -> None:
    if pending.get("schema_version") != "1":
        raise SaveManagerError("pending player session has an invalid schema version")
    common = {"save_id", "save_path", "created_at"}
    required = set(common)
    if kind == "action":
        required.update({"session_id", "expires_at", "ttl_seconds", "delta", "turn_proposal"})
        allowed = required | {
            "schema_version",
            "user_text",
            "action",
            "platform",
            "session_key_hash",
            "actor_id_hash",
            "confirmation_claim",
        }
    elif kind == "clarification":
        required.update({"clarification_id", "original_user_text", "clarification"})
        if not allow_legacy:
            required.update({"expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"})
        allowed = required | {
            "schema_version",
            "expires_at",
            "ttl_seconds",
            "clarification_origin",
            "external_candidate_digest",
            "platform",
            "session_key_hash",
            "actor_id_hash",
        }
    else:
        raise SaveManagerError("pending player session has an unknown kind")
    if not set(pending).issubset(allowed):
        raise SaveManagerError("pending player session contains unknown or raw identity fields")
    if any(key not in pending for key in required):
        if "save_path" not in pending:
            raise SaveManagerError("pending player session save path is incomplete")
        raise SaveManagerError("pending player session is incomplete")
    identifier_key = "session_id" if kind == "action" else "clarification_id"
    raw_identifier = pending.get(identifier_key)
    if (
        not isinstance(raw_identifier, str)
        or not raw_identifier
        or raw_identifier != clean(raw_identifier)
    ):
        raise SaveManagerError("pending player session has an invalid owner token")
    identifier = raw_identifier
    raw_save_id = pending.get("save_id")
    raw_save_path = pending.get("save_path")
    if (
        not isinstance(raw_save_id, str)
        or not raw_save_id
        or raw_save_id != clean(raw_save_id)
        or not isinstance(raw_save_path, str)
        or not raw_save_path
        or raw_save_path != clean(raw_save_path)
        or normalize_required_relative(raw_save_path, "pending save") != raw_save_path
    ):
        raise SaveManagerError("pending player session identity is incomplete")
    for identity_key in ("platform", "session_key_hash", "actor_id_hash"):
        if identity_key not in pending:
            continue
        identity_value = pending.get(identity_key)
        if (
            not isinstance(identity_value, str)
            or not identity_value
            or identity_value != clean(identity_value)
        ):
            raise SaveManagerError("pending player session has invalid identity evidence")
        if identity_key.endswith("_hash") and re.fullmatch(r"[0-9a-f]{64}", identity_value) is None:
            raise SaveManagerError("pending player session has invalid identity evidence")
    if bool(pending.get("platform")) != bool(pending.get("session_key_hash")):
        raise SaveManagerError("pending player session has incomplete platform identity evidence")
    raw_created_at = pending.get("created_at")
    if (
        not isinstance(raw_created_at, str)
        or not raw_created_at
        or raw_created_at != clean(raw_created_at)
    ):
        raise SaveManagerError("pending player session has an invalid creation time")
    created_at = parse_canonical_utc_datetime(raw_created_at)
    if created_at is None:
        raise SaveManagerError("pending player session has an invalid creation time")
    if kind == "action" and (
        not isinstance(pending.get("delta"), dict) or not isinstance(pending.get("turn_proposal"), dict)
    ):
        raise SaveManagerError("pending player action is incomplete")
    if kind == "clarification" and (
        not isinstance(pending.get("original_user_text"), str)
        or not isinstance(pending.get("clarification"), dict)
    ):
        raise SaveManagerError("pending player clarification is incomplete")
    if kind == "clarification":
        clarification_payload = pending["clarification"]
        validate_clarification_payload_privacy(
            clarification_payload,
            session_key_hash=clean(pending.get("session_key_hash")),
            actor_id_hash=clean(pending.get("actor_id_hash")),
        )
        if (
            "clarification_id" in clarification_payload
            and (
                not isinstance(clarification_payload.get("clarification_id"), str)
                or clarification_payload.get("clarification_id") != pending.get("clarification_id")
            )
        ):
            raise SaveManagerError("pending player clarification contains conflicting identity evidence")
    migration_fields = ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest")
    legacy_missing = allow_legacy and any(key not in pending for key in migration_fields)
    try:
        expected_expires_at = created_at + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
    except OverflowError:
        raise SaveManagerError("pending player session has an invalid TTL") from None
    if "expires_at" in pending:
        raw_expires_at = pending.get("expires_at")
        if (
            not isinstance(raw_expires_at, str)
            or not raw_expires_at
            or raw_expires_at != clean(raw_expires_at)
        ):
            raise SaveManagerError("pending player session has an invalid TTL")
        expires_at = parse_canonical_utc_datetime(raw_expires_at)
        if expires_at is None or expires_at != expected_expires_at:
            raise SaveManagerError("pending player session has an invalid TTL")
    if "ttl_seconds" in pending and (
        type(pending.get("ttl_seconds")) is not int
        or pending.get("ttl_seconds") != DEFAULT_PENDING_ACTION_TTL_SECONDS
    ):
        raise SaveManagerError("pending player session has an invalid TTL")
    if kind == "clarification":
        clarification_origin = pending.get("clarification_origin")
        if "clarification_origin" in pending and (
            not isinstance(clarification_origin, str)
            or clarification_origin not in {
                "player_input_ambiguity",
                "candidate_contract_mismatch",
            }
        ):
            raise SaveManagerError("pending player clarification has an invalid origin")
        candidate_digest = pending.get("external_candidate_digest")
        if "external_candidate_digest" in pending and (
            not isinstance(candidate_digest, str)
            or (candidate_digest and re.fullmatch(r"[0-9a-f]{64}", candidate_digest) is None)
        ):
            raise SaveManagerError("pending player clarification has invalid candidate evidence")
        if clarification_origin == "candidate_contract_mismatch" and not candidate_digest:
            raise SaveManagerError("pending player clarification has invalid candidate evidence")
    if legacy_missing:
        return


def migrate_legacy_clarification(pending: dict[str, Any]) -> dict[str, Any]:
    validate_pending_envelope("clarification", pending, allow_legacy=True)
    created_at = clean(pending.get("created_at"))
    migrated = dict(pending)
    migrated.setdefault("expires_at", pending_action_expires_at_from_created(created_at))
    migrated.setdefault("ttl_seconds", DEFAULT_PENDING_ACTION_TTL_SECONDS)
    migrated.setdefault("clarification_origin", "player_input_ambiguity")
    migrated.setdefault("external_candidate_digest", "")
    return migrated


def validate_pending_platform_session(session: dict[str, Any], *, platform: str, session_key: str, actor_id: str = "") -> None:
    validate_platform_session_pair(
        platform=platform,
        session_key=session_key,
        actor_id=actor_id,
    )
    pending_platform = clean(session.get("platform"))
    pending_session_hash = clean(session.get("session_key_hash"))
    pending_actor_hash = clean(session.get("actor_id_hash"))
    provided_platform = clean(platform)
    provided_session_hash = hash_identity(session_key) if clean(session_key) else ""
    provided_actor_hash = hash_identity(actor_id) if clean(actor_id) else ""
    if not pending_platform and not pending_session_hash and not pending_actor_hash:
        if provided_platform or provided_session_hash or provided_actor_hash:
            raise SaveManagerError("pending player action received unexpected platform identity")
        return
    if (
        (not pending_platform and provided_platform)
        or (not pending_session_hash and provided_session_hash)
        or (not pending_actor_hash and provided_actor_hash)
    ):
        raise SaveManagerError("pending player action received unexpected platform identity")
    if (pending_platform or pending_session_hash) and (not provided_platform or not provided_session_hash):
        raise SaveManagerError("pending player action requires matching platform session identity")
    if pending_platform and pending_platform != provided_platform:
        raise SaveManagerError("pending player action belongs to a different platform")
    if pending_session_hash and pending_session_hash != provided_session_hash:
        raise SaveManagerError("pending player action belongs to a different platform session")
    if pending_actor_hash and not provided_actor_hash:
        raise SaveManagerError("pending player action requires matching platform actor identity")
    if pending_actor_hash and pending_actor_hash != provided_actor_hash:
        raise SaveManagerError("pending player action belongs to a different platform actor")


def upsert_campaign_record(records: Any, campaign: Any, path: str, starter_path: str | None) -> list[dict[str, Any]]:
    items = [dict(item) for item in records if isinstance(item, dict) and item.get("id") != campaign.campaign_id]
    existing = next((item for item in records if isinstance(item, dict) and item.get("id") == campaign.campaign_id), {})
    record = {
        "id": campaign.campaign_id,
        "name": campaign.name,
        "path": path,
        "starter_save_path": starter_path if starter_path is not None else existing.get("starter_save_path"),
        "last_validated_at": utc_now(),
        "status": "ok",
    }
    items.append(record)
    return sorted(items, key=lambda item: str(item.get("id", "")))


def build_save_summary(inspect: dict[str, Any], location_name: str | None) -> str:
    time_block = inspect.get("current_time_block") or "未知时间"
    location = location_name or inspect.get("current_location_id") or "未知地点"
    return f"{time_block}，位于{location}。"


def clear_cached_save_sensitive_fields(record: dict[str, Any]) -> None:
    for key in ("current_location_id", "current_location_name", "summary"):
        if record.get(key):
            record[key] = "[hidden]"
    for key in ("errors", "warnings", "error_details"):
        if record.get(key):
            record[key] = ["[hidden]"] if isinstance(record[key], list) else "[hidden]"


def save_blocks_player_entry(record: dict[str, Any]) -> bool:
    return record.get("health") == "error" and not bool(record.get("entry_ok"))


def current_location_is_player_hidden_location(conn: Any, location_id: str) -> bool:
    if not location_id:
        return False
    ensure_visibility_sql_functions(conn)
    row = conn.execute(
        """
        select type, status, visibility
        from entities
        where id = ?
        """,
        (location_id,),
    ).fetchone()
    return bool(
        row
        and normalize_visibility_label(str(row["type"])) == "location"
        and normalize_visibility_label(str(row["status"])) != "archived"
        and is_player_hidden_visibility(str(row["visibility"]))
    )


def location_name_from_save(save_path: Path, inspect: dict[str, Any]) -> str | None:
    location_id = inspect.get("current_location_id")
    if not location_id:
        return None
    try:
        result = GMRuntime.from_path(save_path).query("entity", str(location_id), view="player").to_dict()
    except Exception:
        return None
    text = str(result.get("text", ""))
    first = text.splitlines()[0].strip() if text.splitlines() else ""
    for prefix in ("## 地点：", "## "):
        if first.startswith(prefix):
            return first[len(prefix):].strip()
    return None


def extract_scene_summary(scene_text: str) -> str:
    lines = [line.rstrip() for line in scene_text.splitlines()]
    summary: list[str] = []
    in_overview = False
    for line in lines:
        if line.startswith("### "):
            in_overview = line.strip() == "### 全景"
            continue
        if in_overview and line.strip():
            summary.append(line.strip())
        if len(summary) >= 2:
            break
    if summary:
        return "\n".join(summary)
    for line in lines:
        if line and not line.startswith("#") and not line.startswith("|"):
            return line
    return ""


def extract_affordances(scene_text: str, *, limit: int = 5) -> list[str]:
    actions: list[str] = []
    for line in scene_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip(" `") for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in {"#", "---"} or cells[1] in {"行动", "------"}:
            continue
        action = cells[1].strip()
        if action and action not in actions:
            actions.append(action)
    if not actions:
        actions = ["查看周围", "盘点库存", "和附近的人交谈", "选择一个方向探索", "安排行动"]
    return actions[:limit]


def render_onboarding_text(save: dict[str, Any], scene: dict[str, Any], *, mode: str, user_text: str | None = None) -> str:
    scene_text = str(scene.get("text", ""))
    campaign_name = str(save.get("campaign_name") or save.get("campaign_id") or "当前剧情")
    current_time = str(save.get("current_time_block") or "当前时间")
    current_location = str(save.get("current_location_name") or save.get("current_location_id") or "当前位置")
    scene_summary = extract_scene_summary(scene_text)
    affordances = extract_affordances(scene_text)
    title = f"你正在开始《{campaign_name}》。" if mode == "created" else f"继续《{campaign_name}》。"
    lines = [
        title,
        "",
        f"现在是 {current_time}，你位于 {current_location}。",
    ]
    if scene_summary:
        lines.extend(["", scene_summary])
    lines.extend(["", "你可以直接说想做什么，例如："])
    lines.extend(f"- {item}" for item in affordances)
    lines.extend(
        [
            "",
            "我会先告诉你行动可能的风险、代价和需要确认的地方；你确认后，结果才会写进存档。",
        ]
    )
    text = "\n".join(lines).strip() + "\n"
    for term in INTERNAL_ONBOARDING_TERMS:
        text = text.replace(term, "存档")
    return text


def player_action_message(result: dict[str, Any], *, ready: bool) -> str:
    message = str(result.get("player_message") or "").strip()
    if not message:
        if ready:
            message = "我理解了这个行动，并准备好让你确认。"
        else:
            message = "我还不能安全推进这个行动，需要你补充或改写。"
    lines = [message]
    warnings = [str(item) for item in result.get("warnings", []) if str(item).strip()]
    missing = [str(item) for item in result.get("missing_required", []) if str(item).strip()]
    if missing:
        lines.extend(["", "还需要补充："])
        lines.extend(f"- {item}" for item in missing)
    if warnings:
        lines.extend(["", "需要留意："])
        lines.extend(f"- {item}" for item in warnings)
    if ready:
        lines.extend(["", "确认后我会把结果写进当前存档。"])
    else:
        repair_options = result.get("repair_options", [])
        if repair_options:
            lines.extend(["", "你可以这样调整："])
            for option in repair_options[:5]:
                if isinstance(option, dict):
                    label = option.get("label") or option.get("id") or "选项"
                    description = option.get("effect") or option.get("description") or ""
                    lines.append(f"- {label}: {description}".rstrip(": "))
    return "\n".join(lines).strip() + "\n"


def extract_result_clarification(result: dict[str, Any]) -> dict[str, Any] | None:
    interpretation = result.get("interpretation")
    if isinstance(interpretation, dict):
        clarification = interpretation.get("clarification")
        if isinstance(clarification, dict):
            return dict(clarification)
        intent = interpretation.get("intent")
        if isinstance(intent, dict) and isinstance(intent.get("clarification"), dict):
            return dict(intent["clarification"])
    return None


def player_turn_error_preserves_clarification(result: dict[str, Any]) -> bool:
    if clean(result.get("status")) in {"invalid_request", "invalid_state", "error", "failed"}:
        return True
    error_details = result.get("error_details")
    if not isinstance(error_details, list):
        return False
    external_contract_errors = {
        ("INTENT_CONTRACT_VERSION_MISMATCH", "contract_version_mismatch"),
        ("UNKNOWN_INTENT_SAFETY_FLAG", "unknown_safety_flag"),
    }
    return any(
        isinstance(detail, dict)
        and (detail.get("code"), detail.get("reason")) in external_contract_errors
        for detail in error_details
    )


def normalize_player_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def player_confirm_message(result: dict[str, Any]) -> str:
    write_status = str(result.get("write_status") or "committed")
    projection_status = str(result.get("projection_status") or "unknown")
    replay = write_status == "already_confirmed" and bool(result.get("idempotent_replay"))
    if write_status == "committed":
        first = "行动结果已经写进当前存档。"
    elif replay:
        first = "这项行动此前已经确认；本次是幂等重放，没有重复写入存档。"
    else:
        first = "行动结果没有完成保存。"
    lines = [first]
    if replay and projection_status in {"unknown", "None"}:
        lines.append("本次未重复执行可见内容刷新。")
    elif projection_status and projection_status not in {"clean", "ok", "unknown", "None"}:
        lines.append(f"可见内容刷新状态：{projection_status}。")
    else:
        lines.append("可见内容已经刷新。")
    state_audit = result.get("state_audit")
    if isinstance(state_audit, dict) and state_audit.get("findings"):
        lines.append(f"保存前检查发现 {len(state_audit.get('findings', []))} 条提示，已经按规则处理。")
    return "\n".join(lines).strip() + "\n"


def error_dict(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    return {
        "ok": False,
        "errors": [message],
        "error_details": issues_from_messages([message], default_code="SAVE_MANAGER_ERROR"),
    }


def stable_payload_digest(payload: dict[str, Any]) -> str:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded = text.encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise SaveManagerError("confirmation replay evidence is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def validate_low_level_publication_integrity(
    expected_publication: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "save_id",
        "save_path",
        "pending_kind",
        "pending_generation",
        "owner_incarnation",
        "owner_revision",
        "owner_scope_hash",
        "require_active_save_match",
        "canonical_publication",
        "platform",
        "session_key_hash",
        "actor_id_hash",
        "publication_token",
    }
    if not isinstance(expected_publication, dict) or set(expected_publication) != expected_keys:
        raise SaveManagerError("low-level clarification publication evidence is invalid")
    publication_token = expected_publication.get("publication_token")
    publication = dict(expected_publication)
    publication.pop("publication_token", None)
    if (
        not isinstance(publication_token, str)
        or re.fullmatch(r"[0-9a-f]{64}", publication_token) is None
        or not hmac.compare_digest(
            publication_token,
            low_level_publication_token(publication),
        )
    ):
        raise SaveManagerError("low-level clarification publication evidence is invalid")
    return publication


def low_level_publication_token(publication: dict[str, Any]) -> str:
    try:
        text = json.dumps(
            publication,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded = text.encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise SaveManagerError("low-level clarification publication evidence is invalid") from exc
    return hmac.new(
        _LOW_LEVEL_PUBLICATION_SIGNING_KEY,
        encoded,
        hashlib.sha256,
    ).hexdigest()


def validate_confirmation_receipt_envelope(receipt: dict[str, Any]) -> None:
    if set(receipt) != CONFIRMATION_RECEIPT_KEYS or receipt.get("schema_version") != "1":
        raise SaveManagerError("confirmation replay receipt has an invalid schema")
    supplied_digest = receipt.get("receipt_digest")
    if (
        not isinstance(supplied_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", supplied_digest) is None
    ):
        raise SaveManagerError("confirmation replay receipt has an invalid digest")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if supplied_digest != stable_payload_digest(body):
        raise SaveManagerError("confirmation replay receipt failed integrity validation")
    for key in ("save_id", "command_id", "turn_id"):
        value = receipt.get(key)
        if not isinstance(value, str) or not value or value != clean(value):
            raise SaveManagerError(f"confirmation replay receipt has an invalid {key}")
    save_path = receipt.get("save_path")
    if (
        not isinstance(save_path, str)
        or not save_path
        or save_path != clean(save_path)
        or normalize_required_relative(save_path, "receipt save") != save_path
    ):
        raise SaveManagerError("confirmation replay receipt has an invalid save binding")
    for key in (
        "confirmation_session_hash",
        "command_hash",
        "delta_digest",
        "proposal_digest",
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise SaveManagerError(f"confirmation replay receipt has an invalid {key}")
    for key in ("platform_hash", "session_key_hash", "actor_id_hash"):
        value = receipt.get(key)
        if (
            not isinstance(value, str)
            or (value and re.fullmatch(r"[0-9a-f]{64}", value) is None)
        ):
            raise SaveManagerError("confirmation replay receipt has invalid identity evidence")
    if bool(receipt.get("platform_hash")) != bool(receipt.get("session_key_hash")):
        raise SaveManagerError("confirmation replay receipt has incomplete identity evidence")
    event_count = receipt.get("event_count")
    if type(event_count) is not int or event_count < 0:
        raise SaveManagerError("confirmation replay receipt has an invalid event count")
    if receipt.get("write_status") != "already_confirmed":
        raise SaveManagerError("confirmation replay receipt has an invalid result classification")
    projection_status = receipt.get("projection_status")
    if projection_status not in {
        "",
        "clean",
        "failed",
        "partial_failure",
        "stale",
        "dirty",
        "outbox_pending",
    }:
        raise SaveManagerError("confirmation replay receipt has an invalid projection status")


def validate_confirmation_history_entries(receipts: Any) -> list[dict[str, Any]]:
    if not isinstance(receipts, list) or len(receipts) > MAX_CONFIRMATION_HISTORY_ENTRIES:
        raise SaveManagerError("confirmation replay history exceeds its bounded entry limit")
    validated: list[dict[str, Any]] = []
    session_hashes: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise SaveManagerError("confirmation replay history contains an invalid receipt")
        validate_confirmation_receipt_envelope(receipt)
        session_hash = str(receipt["confirmation_session_hash"])
        if session_hash in session_hashes:
            raise SaveManagerError("confirmation replay history contains a duplicate session")
        session_hashes.add(session_hash)
        validated.append(dict(receipt))
    return validated


def confirmation_history_order_digest(receipts: list[dict[str, Any]]) -> str:
    return stable_payload_digest(
        {
            "schema_version": "1",
            "receipt_digests": [clean(receipt.get("receipt_digest")) for receipt in receipts],
        }
    )


def validate_confirmation_history_transition(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> None:
    previous_hashes = [str(receipt["confirmation_session_hash"]) for receipt in previous]
    current_hashes = [str(receipt["confirmation_session_hash"]) for receipt in current]
    previous_set = set(previous_hashes)
    current_set = set(current_hashes)
    retained_previous = [session_hash for session_hash in previous_hashes if session_hash in current_set]
    retained_current = [session_hash for session_hash in current_hashes if session_hash in previous_set]
    if retained_previous != retained_current:
        raise SaveManagerError("confirmation replay history order cannot be rewritten")
    saw_new = False
    for session_hash in current_hashes:
        if session_hash not in previous_set:
            saw_new = True
        elif saw_new:
            raise SaveManagerError("confirmation replay history can only append new sessions")


def read_bounded_json_object(
    *,
    root: Path,
    path: Path,
    label: str,
    max_bytes: int,
) -> dict[str, Any] | None:
    try:
        raw = read_registry_bytes_anchored(root, path, max_bytes=max_bytes)
    except SaveManagerError as exc:
        if "escapes workspace root" in str(exc):
            raise
        if "exceeds the bounded size limit" in str(exc):
            raise SaveManagerError(f"{label} exceeds the bounded size limit") from exc
        raise SaveManagerError(f"{label} is invalid") from exc
    if raw is None:
        return None
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(SaveManagerError(f"{label} contains a non-finite number")),
        )
    except SaveManagerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SaveManagerError(f"{label} is invalid") from exc
    if not isinstance(data, dict):
        raise SaveManagerError(f"{label} must be a JSON object")
    validate_pending_json_shape(data)
    return data


def validate_pending_json_shape(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_PENDING_JSON_NODES or depth > MAX_PENDING_JSON_DEPTH:
            raise SaveManagerError("pending state exceeds its JSON structure limit")
        if isinstance(current, str):
            if len(current) > MAX_PENDING_STRING_LENGTH:
                raise SaveManagerError("pending state contains an oversized string")
            try:
                current.encode("utf-8")
            except UnicodeError as exc:
                raise SaveManagerError("pending state contains invalid Unicode") from exc
            continue
        if current is None or isinstance(current, bool) or isinstance(current, int):
            continue
        if isinstance(current, float):
            if not (float("-inf") < current < float("inf")):
                raise SaveManagerError("pending state contains a non-finite number")
            continue
        if isinstance(current, dict):
            if len(current) > MAX_PENDING_CONTAINER_ITEMS:
                raise SaveManagerError("pending state contains an oversized container")
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > MAX_PENDING_STRING_LENGTH:
                    raise SaveManagerError("pending state contains an invalid JSON object key")
                try:
                    key.encode("utf-8")
                except UnicodeError as exc:
                    raise SaveManagerError("pending state contains an invalid JSON object key") from exc
                stack.append((item, depth + 1))
            continue
        if isinstance(current, list):
            if len(current) > MAX_PENDING_CONTAINER_ITEMS:
                raise SaveManagerError("pending state contains an oversized container")
            stack.extend((item, depth + 1) for item in current)
            continue
        raise SaveManagerError("pending state contains a non-JSON value")


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SaveManagerError("confirmation replay receipt contains duplicate JSON keys")
        result[key] = value
    return result


def reject_duplicate_registry_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SaveManagerError("registry contains duplicate JSON keys")
        result[key] = value
    return result


def validate_confirmation_result_contract(result: dict[str, Any]) -> None:
    write_status = clean(result.get("write_status"))
    ok = result.get("ok")
    replay = result.get("idempotent_replay")
    if (
        type(ok) is not bool
        or not ok
        or type(replay) is not bool
        or write_status not in {"committed", "already_confirmed"}
        or replay != (write_status == "already_confirmed")
    ):
        raise SaveManagerError("invalid confirmation write result")


def confirmation_registry_needs_repair(save: dict[str, Any], result: dict[str, Any]) -> bool:
    if clean(result.get("write_status")) == "committed":
        return True
    turn_id = clean(result.get("turn_id"))
    return bool(turn_id and clean(save.get("current_turn_id")) != turn_id)


def rewrite_save_manifests(target: Path, campaign: Any) -> None:
    config_path = target / "campaign.yaml"
    config = dict(campaign.config)
    config["database"] = "data/game.sqlite"
    config["events"] = "data/events.jsonl"
    config["current_snapshot"] = "snapshots/current.md"
    config["current_snapshot_json"] = "snapshots/current.json"
    config["cards"] = "cards"
    config["content"] = normalize_content_paths_for_save(campaign, target)
    write_text_atomic(
        config_path,
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )
    save_manifest = {
        "save_schema_version": "1",
        "campaign_id": campaign.campaign_id,
        "campaign_version": campaign.package_version,
        "engine_version": campaign.engine_version,
        "source_campaign_path": relative_path(target, campaign.root),
        "created_at": utc_now(),
    }
    write_text_atomic(
        target / "save.yaml",
        yaml.safe_dump(save_manifest, allow_unicode=True, sort_keys=False),
    )


def normalize_content_paths_for_target(campaign: Any, target: Path) -> dict[str, Any]:
    return normalize_content_paths_for_save(campaign, target)


def relative_path(base: Path, path: Path) -> str:
    return Path(os.path.relpath(path, base)).as_posix()
