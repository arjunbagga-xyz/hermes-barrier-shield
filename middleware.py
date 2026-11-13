"""Continuous Control-Barrier Function (`tool_request` and `llm_request`) middleware."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Union

try:
    from .engine import get_session_cbf_state, handle_cbf_project_action
except (ImportError, ValueError):
    from engine import get_session_cbf_state, handle_cbf_project_action


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
    sid = session_id if isinstance(session_id, str) else str(session_id.get("session_id", "default") if isinstance(session_id, dict) else "default")
    state = get_session_cbf_state(sid)
    if isinstance(session_id, dict) and state.get("history"):
        latest = state["history"][-1]
        if latest.get("deflected"):
            session_id.setdefault("directives", []).append(latest.get("transcript_directive", ""))
        return session_id
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
    first_arg: Union[str, Dict[str, Any]],
    second_arg: Union[Dict[str, Any], Callable[[Dict[str, Any]], Any]],
    original_args: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """
    Supports both:
      1. Upstream Hermes `tool_request` contract: `(tool_name: str, args: dict, original_args: dict = None, **kwargs)`
      2. Chain-style `(tool_request_dict, next_fn)`.
    """
    session_id = str(kwargs.get("session_id", "default"))
    enable_rewriting = bool(kwargs.get("enable_argument_rewriting", False))
    rewritable_tools = set(kwargs.get("rewritable_tools", []))

    if isinstance(first_arg, str) and isinstance(second_arg, dict):
        tool_name = first_arg
        # Never edit terminal commands
        if tool_name in ("terminal", "execute_bash", "bash", "sh"):
            return None

        # Only rewrite if explicitly enabled and tool is in configured allowlist
        if not enable_rewriting or tool_name not in rewritable_tools:
            return None

        new_args, qp = _project_tool_args(second_arg, session_id=session_id)
        if not qp.get("deflected"):
            return None

        return {
            "args": new_args,
            "source": "barrier-shield",
            "reason": f"CBF-QP projected arguments along h(x)>={qp.get('min_h_after', 0.0):.2f} (damped {qp.get('damping_ratio', 0.0):.0%})",
            "cbf_projection": qp,
        }

    if isinstance(first_arg, dict) and callable(second_arg):
        args = first_arg.get("arguments")
        tool_name = first_arg.get("name", "")
        if (
            enable_rewriting
            and tool_name in rewritable_tools
            and tool_name not in ("terminal", "execute_bash", "bash", "sh")
            and isinstance(args, dict)
        ):
            new_args, qp = _project_tool_args(args, session_id=session_id)
            first_arg["arguments"] = new_args
            first_arg["cbf_projection"] = qp
        return second_arg(first_arg)

    return None


def cbf_llm_request_middleware(
    request: Dict[str, Any],
    second_arg: Optional[Union[Dict[str, Any], Callable[[Dict[str, Any]], Any]]] = None,
    **kwargs: Any,
) -> Any:
    """Control Lyapunov Function (CLF) temperature damping when loop energy V(x) rises (opt-in)."""
    enable_damping = bool(kwargs.get("enable_temperature_damping", False))
    session_id = str(kwargs.get("session_id", "default"))
    state = get_session_cbf_state(session_id)

    if not enable_damping:
        if callable(second_arg):
            return second_arg(request)
        return None

    history = state.get("history", [])
    if callable(second_arg):
        if history and history[-1].get("lyapunov_energy_v", 0.0) > 0.35 and "temperature" in request:
            request["temperature"] = round(float(request["temperature"]) * 0.65, 3)
        return second_arg(request)

    if history and history[-1].get("lyapunov_energy_v", 0.0) > 0.35 and "temperature" in request:
        new_req = dict(request)
        new_req["temperature"] = round(float(new_req["temperature"]) * 0.65, 3)
        return {
            "request": new_req,
            "source": "barrier-shield",
            "reason": "Lyapunov energy V(x) > 0.35; cooled sampling temperature by 0.65x",
        }
    return None
