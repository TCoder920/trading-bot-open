"""Broker reconciliation and exposure routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.database import get_reconciliation_runs
from backend.services.exposure_service import ExposureService
from backend.services.fill_reconciler import FillReconciler
from backend.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.get("/exposure")
def exposure_snapshot():
    return ExposureService(state.get_config()).snapshot()


@router.post("/positions")
def sync_positions():
    return ReconciliationService(state.get_config()).sync_positions()


@router.post("/orders")
def reconcile_orders():
    return ReconciliationService(state.get_config()).reconcile_orders()


@router.post("/fills")
def reconcile_fills():
    """Poll Alpaca, record fills, realize PnL, and update the daily-loss kill switch."""
    return FillReconciler(state.get_config()).reconcile()


@router.get("/runs")
def reconciliation_runs(run_type: str | None = None, limit: int = 50):
    return {"runs": get_reconciliation_runs(run_type=run_type, limit=limit)}
