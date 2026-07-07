from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS
from .atomic_io import write_text_atomic
from .campaign import load_campaign
from .db import utc_now
from .game_session import clean, hash_identity
from .intent_router import make_intent_ai_config, make_intent_request_meta
from .runtime import GMRuntime, intent_ai_config_kwargs, intent_request_meta_kwargs
from .save_service import init_v1_save, inspect_v1_save, normalize_content_paths_for_save
from .validation_issues import issues_from_messages


REGISTRY_SCHEMA_VERSION = "1"
DEFAULT_REGISTRY_RELATIVE = ".aigm/save-registry.json"
DEFAULT_PENDING_ACTION_RELATIVE = ".aigm/pending-player-action.json"
DEFAULT_PENDING_CLARIFICATION_RELATIVE = ".aigm/pending-player-clarification.json"
DEFAULT_PENDING_ACTION_TTL_SECONDS = 1800
DEFAULT_SAVES_DIR = "saves"
INTERNAL_ONBOARDING_TERMS = ("delta", "commit", "SQLite", "save_dir", "campaign.yaml", "game.sqlite")


class SaveManagerError(ValueError):
    """Raised for player-entry and save-registry validation failures."""


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
        registry = self.read_registry()
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
            changed = False
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
                changed = True
            if changed:
                registry["campaigns"] = campaigns
                self.write_registry(registry)
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
        registry = self.read_registry()
        campaigns = [dict(item) for item in registry.get("campaigns", []) if isinstance(item, dict)]
        campaigns = [item for item in campaigns if item.get("id") != loaded.campaign_id]
        campaigns.append(record)
        registry["campaigns"] = sorted(campaigns, key=lambda item: str(item.get("id", "")))
        self.write_registry(registry)
        return {"ok": True, "campaign": record, "errors": []}

    def list_saves(
        self,
        *,
        campaign_id: str | None = None,
        include_archived: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        registry = self.read_registry()
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
                    "saves": filtered,
                    "errors": path_errors,
                    "error_details": issues_from_messages(path_errors, default_code="SAVE_MANAGER_ERROR"),
                }
            refreshed: list[dict[str, Any]] = []
            changed = False
            for record in saves:
                if any(record.get("id") == item.get("id") for item in filtered):
                    refreshed_record = self.refresh_save_record(record)
                    refreshed.append(refreshed_record)
                    changed = True
                else:
                    refreshed.append(record)
            if changed:
                registry["saves"] = refreshed
                self.write_registry(registry)
                filtered_ids = {str(item.get("id")) for item in filtered}
                filtered = [dict(item) for item in refreshed if str(item.get("id")) in filtered_ids]
        return {
            "ok": True,
            "active_save_id": registry.get("active_save_id"),
            "saves": filtered,
            "errors": [],
        }

    def current_save(self, *, refresh: bool = False) -> dict[str, Any]:
        registry = self.read_registry()
        active_save_id = registry.get("active_save_id")
        if not active_save_id:
            return {
                "ok": False,
                "active_save_id": None,
                "save": None,
                "errors": ["no active save is configured"],
                "error_details": issues_from_messages(["no active save is configured"], default_code="SAVE_MANAGER_ERROR"),
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
        if refresh:
            path_errors = registry_record_path_errors(self.root, registry.get("saves", []), "save")
            if path_errors:
                return {
                    "ok": False,
                    "active_save_id": active_save_id,
                    "save": None,
                    "errors": path_errors,
                    "error_details": issues_from_messages(path_errors, default_code="SAVE_MANAGER_ERROR"),
                }
            record = self.refresh_save_record(dict(record))
            registry["saves"] = replace_record(registry.get("saves", []), record)
            self.write_registry(registry)
        return {
            "ok": True,
            "active_save_id": active_save_id,
            "save": record,
            "current_save_authority": current_save_authority(refresh=refresh),
            "errors": [],
        }

    def switch_save(self, save_id: str, *, refresh: bool = True) -> dict[str, Any]:
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
        registry["active_save_id"] = save_id
        self.write_registry(registry)
        return {"ok": True, "active_save_id": save_id, "save": record, "errors": []}

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
        ensure_empty_target(target)

        source = "save_init"
        if starter_path:
            starter = self.resolve_relative(starter_path, "starter_save")
            if not starter.exists():
                raise SaveManagerError(f"starter save does not exist: {starter_path}")
            shutil.copytree(starter, target)
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
        registry = self.read_registry()
        registry["campaigns"] = upsert_campaign_record(
            registry.get("campaigns", []),
            campaign_obj,
            campaign_path,
            starter_path,
        )
        registry["saves"] = replace_record(registry.get("saves", []), record)
        if activate:
            registry["active_save_id"] = save_id
        self.write_registry(registry)
        return {
            "ok": record.get("health") != "error",
            "mode": "created",
            "active_save_id": registry.get("active_save_id"),
            "save": record,
            "errors": [] if record.get("health") != "error" else list(record.get("errors", [])),
        }

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
        shutil.copytree(source_path, target_path)
        record = self.build_save_record(
            save_id=new_save_id,
            campaign_path=str(source_record.get("campaign_path", "")),
            save_path=target_relative,
            label=label or f"{source_record.get('label', '存档')} · 副本",
            kind=str(source_record.get("kind", "normal")),
            source="duplicate",
        )
        registry["saves"] = replace_record(registry.get("saves", []), record)
        if activate:
            registry["active_save_id"] = new_save_id
        self.write_registry(registry)
        return {
            "ok": record.get("health") != "error",
            "mode": "created",
            "active_save_id": registry.get("active_save_id"),
            "save": record,
            "errors": [] if record.get("health") != "error" else list(record.get("errors", [])),
        }

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
        if save.get("health") == "error":
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
        current = self.current_save(refresh=False)
        if current["ok"] and current.get("save"):
            return self.resolve_relative(str(current["save"]["path"]), "save")
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
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        save = self.require_save(refresh=True, save_path=save_path)
        pending_clarification = self.read_pending_clarification()
        self.clear_pending_action()
        if (
            pending_clarification
            and str(pending_clarification.get("save_id")) == str(save["id"])
            and normalize_player_text(user_text) == normalize_player_text(pending_clarification.get("original_user_text"))
        ):
            clarification = pending_clarification.get("clarification") if isinstance(pending_clarification.get("clarification"), dict) else {}
            return {
                "ok": False,
                "active_save_id": save["id"],
                "status": "needs_confirmation",
                "action": None,
                "message": "我正在等待你回答上一个澄清问题；请补充你的真实意图，而不是重复原句。\n",
                "ready_to_confirm": False,
                "session_id": None,
                "clarification": clarification,
                "pending_clarification_id": pending_clarification.get("clarification_id"),
                "saved": False,
                "warnings": [],
                "errors": ["pending clarification requires a fresh player answer"],
                "repair_options": [],
            }
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
        session_id: str | None = None
        if ready:
            session_id = f"player_action:{uuid.uuid4().hex}"
            self.clear_pending_clarification()
            self.write_pending_action(
                {
                    "schema_version": "1",
                    "session_id": session_id,
                    "save_id": save["id"],
                    "save_path": save["path"],
                    "created_at": utc_now(),
                    "expires_at": pending_action_expires_at(),
                    "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
                    "user_text": user_text,
                    "action": result.get("action"),
                    "delta": result.get("delta_draft"),
                    "turn_proposal": result.get("turn_proposal"),
                    **platform_session_metadata(platform=platform, session_key=session_key, actor_id=actor_id),
                }
            )
        elif clarification:
            clarification_id = str(clarification.get("clarification_id") or f"clarification:{uuid.uuid4().hex}")
            clarification = {**clarification, "clarification_id": clarification_id}
            self.write_pending_clarification(
                {
                    "schema_version": "1",
                    "clarification_id": clarification_id,
                    "save_id": save["id"],
                    "save_path": save["path"],
                    "created_at": utc_now(),
                    "original_user_text": user_text,
                    "clarification": clarification,
                    **platform_session_metadata(platform=platform, session_key=session_key, actor_id=actor_id),
                }
            )
        else:
            self.clear_pending_clarification()
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
        save = self.require_save(refresh=True, save_path=save_path)
        session = self.read_pending_action()
        if not session:
            raise SaveManagerError("no pending player action to confirm")
        if pending_action_is_expired(session):
            self.clear_pending_action()
            raise SaveManagerError("pending player action expired; ask the player to run player_turn again")
        if str(session.get("save_id")) != str(save["id"]):
            raise SaveManagerError("pending player action belongs to a different active save")
        validate_pending_platform_session(session, platform=platform, session_key=session_key, actor_id=actor_id)
        expected_session_id = str(session.get("session_id") or "").strip()
        provided_session_id = str(session_id or "").strip()
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
        proposal = dict(proposal)
        provenance = proposal.get("provenance") if isinstance(proposal.get("provenance"), dict) else {}
        proposal["provenance"] = {
            **dict(provenance),
            "confirmed_via": "player_confirm",
            "confirmation_session_id": expected_session_id,
            "confirmed_at": utc_now(),
        }
        proposal["human_confirmed"] = True
        runtime = GMRuntime.from_path(self.resolve_relative(str(save["path"]), "save"))
        result = runtime.commit_turn(delta, turn_proposal=proposal).to_dict()
        self.clear_pending_action()
        refreshed = self.refresh_save_record(dict(save))
        registry = self.read_registry()
        registry["saves"] = replace_record(registry.get("saves", []), refreshed)
        self.write_registry(registry)
        return {
            "ok": bool(result.get("ok", True)),
            "active_save_id": save["id"],
            "save": refreshed,
            "saved": True,
            "message": player_confirm_message(result),
            "write_status": result.get("write_status"),
            "projection_status": result.get("projection_status"),
            "warnings": result.get("warnings", []),
            "errors": result.get("errors", []),
        }

    def require_active_save(self, *, refresh: bool) -> dict[str, Any]:
        return self.require_save(refresh=refresh)

    def require_save(self, *, refresh: bool, save_path: str = "") -> dict[str, Any]:
        if save_path:
            relative_path = normalize_required_relative(save_path, "save")
            registry = self.read_registry()
            record = find_save_record_by_path(registry.get("saves", []), relative_path)
            if record is None:
                raise SaveManagerError(f"save not found for path: {relative_path}")
            record = dict(record)
            if bool(record.get("archived")):
                raise SaveManagerError(f"save is archived: {record.get('id') or relative_path}")
            if refresh:
                path_errors = registry_record_path_errors(self.root, [record], "save")
                if path_errors:
                    raise SaveManagerError("; ".join(path_errors))
            if refresh:
                record = self.refresh_save_record(record)
                registry["saves"] = replace_record(registry.get("saves", []), record)
                self.write_registry(registry)
            if record.get("health") == "error":
                raise SaveManagerError(
                    "; ".join([f"save is not healthy: {record.get('label') or record.get('id')}", *record.get("errors", [])])
                )
            return record
        current = self.current_save(refresh=refresh)
        if not current["ok"] or not current.get("save"):
            raise SaveManagerError("; ".join(current.get("errors", [])) or "no active save is configured")
        save = dict(current["save"])
        if save.get("health") == "error":
            raise SaveManagerError(
                "; ".join([f"active save is not healthy: {save.get('label') or save.get('id')}", *save.get("errors", [])])
            )
        return save

    def pending_action_path(self) -> Path:
        return (self.root / DEFAULT_PENDING_ACTION_RELATIVE).resolve()

    def pending_clarification_path(self) -> Path:
        return (self.root / DEFAULT_PENDING_CLARIFICATION_RELATIVE).resolve()

    def read_pending_action(self) -> dict[str, Any] | None:
        path = self.pending_action_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SaveManagerError("pending player action must be a JSON object")
        return data

    def write_pending_action(self, session: dict[str, Any]) -> None:
        path = self.pending_action_path()
        ensure_under_root(self.root, path, "pending action")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        write_text_atomic(path, text)

    def clear_pending_action(self) -> None:
        try:
            self.pending_action_path().unlink()
        except FileNotFoundError:
            pass

    def read_pending_clarification(self) -> dict[str, Any] | None:
        path = self.pending_clarification_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SaveManagerError("pending player clarification must be a JSON object")
        return data

    def write_pending_clarification(self, session: dict[str, Any]) -> None:
        path = self.pending_clarification_path()
        ensure_under_root(self.root, path, "pending clarification")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        write_text_atomic(path, text)

    def clear_pending_clarification(self) -> None:
        try:
            self.pending_clarification_path().unlink()
        except FileNotFoundError:
            pass

    def mark_played(self, save_id: str) -> None:
        registry = self.read_registry()
        record = find_record(registry.get("saves", []), save_id)
        if record is None:
            return
        record = dict(record)
        record["last_played_at"] = utc_now()
        registry["saves"] = replace_record(registry.get("saves", []), record)
        self.write_registry(registry)

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
            inspect = inspect_v1_save(self.resolve_relative(str(record.get("path", "")), "save"))
            location_name = location_name_from_save(self.resolve_relative(str(record.get("path", "")), "save"), inspect)
            health = "ok" if inspect.get("ok") else "error"
            record.update(
                {
                    "campaign_id": inspect.get("campaign_id") or record.get("campaign_id", ""),
                    "campaign_name": inspect.get("campaign_name") or record.get("campaign_name", ""),
                    "current_turn_id": inspect.get("current_turn_id"),
                    "current_game_day": inspect.get("current_game_day"),
                    "current_time_block": inspect.get("current_time_block"),
                    "current_location_id": inspect.get("current_location_id"),
                    "current_location_name": location_name,
                    "summary": build_save_summary(inspect, location_name),
                    "health": health,
                    "last_inspected_at": now,
                    "errors": list(inspect.get("errors", [])),
                    "warnings": list(inspect.get("warnings", [])),
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
        return record

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
        if not self.registry_path.exists():
            return empty_registry()
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SaveManagerError(f"registry is invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise SaveManagerError("registry must be a JSON object")
        if str(data.get("schema_version", "")) != REGISTRY_SCHEMA_VERSION:
            raise SaveManagerError(
                f"registry schema_version must be {REGISTRY_SCHEMA_VERSION}, got {data.get('schema_version')}"
            )
        data.setdefault("active_save_id", None)
        data.setdefault("campaigns", [])
        data.setdefault("saves", [])
        if not isinstance(data["campaigns"], list) or not isinstance(data["saves"], list):
            raise SaveManagerError("registry campaigns and saves must be arrays")
        return data

    def write_registry(self, registry: dict[str, Any]) -> None:
        registry = normalize_registry(registry)
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
        with registry_lock(lock_path):
            text = json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            write_text_atomic(self.registry_path, text)


def empty_registry() -> dict[str, Any]:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "active_save_id": None, "campaigns": [], "saves": []}


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


def registry_record_path_errors(root: Path, records: list[dict[str, Any]], record_kind: str) -> list[str]:
    errors: list[str] = []
    for record in records:
        record_id = str(record.get("id") or "<unknown>")
        for field, required in registry_path_fields(record_kind):
            try:
                validate_registry_record_relative(root, record.get(field), f"{record_kind}.{field}", required=required)
            except SaveManagerError as exc:
                errors.append(f"{record_kind} registry record {record_id} {field}: {exc}")
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


@contextmanager
def registry_lock(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise SaveManagerError(f"timed out waiting for registry lock: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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
        candidate = root / candidate
    candidate = candidate.resolve()
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


def ensure_empty_target(path: Path) -> None:
    if path.exists() and path.is_file():
        raise FileExistsError(f"save target is a file: {path}")
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"save directory is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


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


def platform_session_metadata(*, platform: str, session_key: str, actor_id: str = "") -> dict[str, Any]:
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


def validate_pending_platform_session(session: dict[str, Any], *, platform: str, session_key: str, actor_id: str = "") -> None:
    pending_platform = clean(session.get("platform"))
    pending_session_hash = clean(session.get("session_key_hash"))
    pending_actor_hash = clean(session.get("actor_id_hash"))
    provided_platform = clean(platform)
    provided_session_hash = hash_identity(session_key) if clean(session_key) else ""
    provided_actor_hash = hash_identity(actor_id) if clean(actor_id) else ""
    if not pending_platform and not pending_session_hash and not pending_actor_hash:
        return
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


def normalize_player_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def player_confirm_message(result: dict[str, Any]) -> str:
    write_status = str(result.get("write_status") or "committed")
    projection_status = str(result.get("projection_status") or "unknown")
    if write_status == "committed":
        first = "行动结果已经写进当前存档。"
    else:
        first = "行动结果没有完成保存。"
    lines = [first]
    if projection_status and projection_status not in {"clean", "ok", "unknown", "None"}:
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
