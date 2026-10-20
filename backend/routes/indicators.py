"""Indicator definitions route."""

from __future__ import annotations

from fastapi import APIRouter

from backend.models import INDICATOR_DEFINITIONS

router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.get("")
def list_indicators():
    return {"indicators": INDICATOR_DEFINITIONS}
