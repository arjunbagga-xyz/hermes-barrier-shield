"""FastAPI web router for barrier-shield barrier state inspection."""

from __future__ import annotations

from fastapi import APIRouter

from ..engine import handle_cbf_state_telemetry

router = APIRouter()


@router.get("/status")
def get_cbf_status() -> dict:
    return {
        "plugin": "barrier-shield",
        "status": "active",
        "telemetry": handle_cbf_state_telemetry({}),
    }
