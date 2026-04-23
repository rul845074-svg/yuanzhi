#!/usr/bin/env python3
"""Concept candidate review operations — list, approve, reject."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSPACE_ROOT / "config" / "agent.config.json"


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="seconds")


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _vault_root(profile: str | None = None) -> Path:
    config = _load_config()
    prof = profile or config.get("default_profile", "dev")
    root = config["profiles"][prof]["vault_root"]
    return Path(root).expanduser()


def _candidates_path(profile: str | None = None) -> Path:
    config = _load_config()
    vault = _vault_root(profile)
    rel = config["paths"]["concept_candidates"]
    return vault / rel


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_concept_candidates(profile: str | None = None) -> dict[str, Any]:
    path = _candidates_path(profile)
    data = _read_json(path, {"candidates": []})
    return data


def review_concept(concept_id: str, action: str, profile: str | None = None) -> dict[str, Any]:
    if action not in ("approve", "reject"):
        raise ValueError(f"Invalid action: {action}. Must be 'approve' or 'reject'.")

    path = _candidates_path(profile)
    data = _read_json(path, {"candidates": []})
    candidates = data.get("candidates", [])

    target = next((c for c in candidates if c.get("id") == concept_id), None)
    if not target:
        raise ValueError(f"Concept candidate not found: {concept_id}")

    now = _now_iso()
    target["status"] = "approved" if action == "approve" else "rejected"
    target["reviewed_at"] = now
    data["updated_at"] = now
    _write_json(path, data)

    return {"updated_at": now, "concept": target}
