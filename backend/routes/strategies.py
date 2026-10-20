"""Strategy management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.database import (
    delete_strategy,
    get_active_strategy,
    get_strategies,
    get_strategy,
    insert_log,
    set_active_strategy,
    upsert_strategy,
)
from backend.models import STRATEGY_TEMPLATES, StrategyCreate, StrategyUpdate

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("/templates")
def list_templates():
    return STRATEGY_TEMPLATES


@router.get("")
def list_strategies():
    return {"strategies": get_strategies(), "active": get_active_strategy()}


@router.get("/{name}")
def read_strategy(name: str):
    s = get_strategy(name)
    if not s:
        raise HTTPException(404, f"Strategy '{name}' not found")
    return s


@router.post("")
def create_strategy(body: StrategyCreate):
    if body.template not in STRATEGY_TEMPLATES:
        raise HTTPException(400, f"Unknown template '{body.template}'")
    tmpl = STRATEGY_TEMPLATES[body.template]
    merged = {**tmpl["default_config"], **body.config}
    result = upsert_strategy(body.name, body.template, merged, body.enabled)
    insert_log("strategy", f"Created strategy '{body.name}'", strategy=body.name)
    return result


@router.patch("/{name}")
def update_strategy(name: str, body: StrategyUpdate):
    existing = get_strategy(name)
    if not existing:
        raise HTTPException(404, f"Strategy '{name}' not found")
    template = body.template or existing["template"]
    enabled = body.enabled if body.enabled is not None else existing["enabled"]
    config = {**existing["config"], **(body.config or {})}
    result = upsert_strategy(name, template, config, enabled)
    insert_log("strategy", f"Updated strategy '{name}'", strategy=name)
    return result


@router.delete("/{name}")
def remove_strategy(name: str):
    ok = delete_strategy(name)
    if not ok:
        raise HTTPException(404, f"Strategy '{name}' not found")
    insert_log("strategy", f"Deleted strategy '{name}'", strategy=name)
    return {"status": "deleted", "name": name}


@router.post("/{name}/activate")
def activate_strategy(name: str):
    result = set_active_strategy(name)
    if not result:
        raise HTTPException(404, f"Strategy '{name}' not found")
    insert_log("strategy", f"Activated strategy '{name}'", strategy=name)
    return result
