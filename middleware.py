"""Continuous Control-Barrier Function (`tool_request` and `llm_request`) middleware."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Union

try:
    from .engine import get_session_cbf_state, handle_cbf_project_action
except (ImportError, ValueError):
    from engine import get_session_cbf_state, handle_cbf_project_action

_PLUGIN_CTX: Any = None


def set_plugin_context(ctx: Any) -> None:
    """Store the HermesPluginContext captured during registration."""
    global _PLUGIN_CTX
    _PLUGIN_CTX = ctx


def get_plugin_config(key: str, default: Any = None) -> Any:
    """Retrieve configuration option from the registered HermesPluginContext."""
    ctx = _PLUGIN_CTX
    if ctx is not None:
        if hasattr(ctx, "get_config"):
            try:
                val = ctx.get_config(key, default)
                if val is not None:
                    return val
            except TypeError:
                try:
                    cfg = ctx.get_config()
                    if isinstance(cfg, dict) and key in cfg:
                        return cfg[key]
                except Exception:
                    pass
            except Exception:
                pass
        if hasattr(ctx, "config") and isinstance(ctx.config, dict):
            if key in ctx.config:
                return ctx.config[key]
    return default


def pre_llm_call_hook(
    session_id: Union[str, Dict[str, Any]] = "",
    user_message: str = "",
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    if isinstance(session_id, dict):
        return session_id
    return None


def post_llm_call_hook(
    session_id: Union[str, Dict[str, Any]] = "",
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    payload = session_id if isinstance(session_id, dict) else kwargs.get("payload")
    sid = session_id if isinstance(session_id, str) else str(
        session_id.get("session_id", "default") if isinstance(session_id, dict) else kwargs.get("session_id", "default")
    )
    state = get_session_cbf_state(sid)
    if isinstance(payload, dict) and state.get("history"):
        latest = state["history"][-1]
        if latest.get("deflected"):
            payload.setdefault("directives", []).append(latest.get("transcript_directive", ""))
        return payload
    return None


def _project_tool_args(args: Dict[str, Any], session_id: str = "default") -> tuple[Dict[str, Any], Dict[str, Any]]:
    new_args = dict(args)
    batch_files = float(new_args.get("batch_files", new_args.get("limit", 5.0)))
    workers = float(new_args.get("workers", new_args.get("concurrency", 2.0)))
    spend = float(new_args.get("delta_spend_usd", 0.5))

    qp_raw = handle_cbf_project_action({
        "session_id": session_id,
        "delta_spend_usd": spend,
        "batch_files": batch_files,
        "workers": workers,
        "loop_entropy": 0.05,
        "commit_state": True,
    })
    qp = json.loads(qp_raw) if isinstance(qp_raw, str) else qp_raw

    if qp.get("deflected"):
        safe_u = qp.get("u_safe_projected", [spend, batch_files, workers, 0.05])
        if "batch_files" in new_args:
            new_args["batch_files"] = max(1, int(round(safe_u[1])))
        if "limit" in new_args:
            new_args["limit"] = max(1, int(round(safe_u[1])))
        if "workers" in new_args:
            new_args["workers"] = max(1, int(round(safe_u[2])))
        if "concurrency" in new_args:
            new_args["concurrency"] = max(1, int(round(safe_u[2])))
        # Note: We NEVER modify payment amounts or append '| head' to terminal commands
    return new_args, qp


def cbf_tool_request_middleware(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """
    Continuous Control-Barrier Function (CBF-QP) tool request middleware.

    Conforms to Hermes keyword-args middleware contract:
    called as `tool_request(tool_name=..., args=..., original_args=..., session_id=..., ...)`.
    Returns `{"args": new_args}` when projected/rewritten, or `None` if safe/unmodified.
    """
    if args is None:
        args = kwargs.get("args") or kwargs.get("arguments")
    if not isinstance(args, dict):
        return None

    actual_tool_name = str(tool_name or kwargs.get("tool_name", ""))
    sid = str(session_id or kwargs.get("session_id") or "default")

    # Read opt-in config from HermesPluginContext captured during register()
    enable_rewriting = bool(
        kwargs.get("enable_argument_rewriting")
        if "enable_argument_rewriting" in kwargs
        else get_plugin_config("enable_argument_rewriting", False)
    )
    raw_rewritable = (
        kwargs.get("rewritable_tools")
        if "rewritable_tools" in kwargs
        else get_plugin_config("rewritable_tools", [])
    )
    rewritable_tools = set(raw_rewritable) if isinstance(raw_rewritable, (list, tuple, set)) else set()

    # Never edit terminal commands
    if actual_tool_name in ("terminal", "execute_bash", "bash", "sh"):
        return None

    # Only rewrite if explicitly enabled and tool is in configured allowlist
    if not enable_rewriting or actual_tool_name not in rewritable_tools:
        return None

    new_args, qp = _project_tool_args(args, session_id=sid)
    if not qp.get("deflected"):
        return None

    return {"args": new_args}


def cbf_llm_request_middleware(
    request: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Control Lyapunov Function (CLF) temperature damping when loop energy V(x) rises (opt-in)."""
    if request is None:
        request = kwargs.get("request")
    if not isinstance(request, dict):
        return None

    enable_damping = bool(
        kwargs.get("enable_temperature_damping")
        if "enable_temperature_damping" in kwargs
        else get_plugin_config("enable_temperature_damping", False)
    )
    if not enable_damping:
        return None

    sid = str(session_id or kwargs.get("session_id") or "default")
    state = get_session_cbf_state(sid)

    history = state.get("history", [])
    if history and history[-1].get("lyapunov_energy_v", 0.0) > 0.35 and "temperature" in request:
        new_req = dict(request)
        new_req["temperature"] = round(float(new_req["temperature"]) * 0.65, 3)
        return {
            "request": new_req,
            "source": "barrier-shield",
            "reason": "Lyapunov energy V(x) > 0.35; cooled sampling temperature by 0.65x",
        }
    return None
