"""Continuous Control-Barrier Function (`tool_request` and `llm_request`) middleware."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Union

try:
    from .engine import CBF_STATE, handle_cbf_project_action
except (ImportError, ValueError):
    from engine import CBF_STATE, handle_cbf_project_action


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
    if isinstance(session_id, dict) and CBF_STATE["history"]:
        latest = CBF_STATE["history"][-1]
        if latest.get("deflected"):
            session_id.setdefault("directives", []).append(latest["transcript_directive"])
        return session_id
    return None


def _project_tool_args(args: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    new_args = dict(args)
    batch_files = float(new_args.get("batch_files", new_args.get("limit", 5.0)))
    workers = float(new_args.get("workers", new_args.get("concurrency", 2.0)))
    spend = float(new_args.get("delta_spend_usd", new_args.get("amount", 0.5) / 20.0 if "amount" in new_args else 0.5))

    qp_raw = handle_cbf_project_action({
        "delta_spend_usd": spend,
        "batch_files": batch_files,
        "workers": workers,
        "loop_entropy": 0.05,
        "commit_state": True,
    })
    qp = json.loads(qp_raw) if isinstance(qp_raw, str) else qp_raw

    if qp["deflected"]:
        safe_u = qp["u_safe_projected"]
        if "batch_files" in new_args:
            new_args["batch_files"] = max(1, int(round(safe_u[1])))
        if "limit" in new_args:
            new_args["limit"] = max(1, int(round(safe_u[1])))
        if "workers" in new_args:
            new_args["workers"] = max(1, int(round(safe_u[2])))
        if "concurrency" in new_args:
            new_args["concurrency"] = max(1, int(round(safe_u[2])))
        if "amount" in new_args:
            scale = safe_u[0] / max(spend, 1e-6)
            new_args["amount"] = round(float(new_args["amount"]) * scale, 2)
        if "command" in new_args and isinstance(new_args["command"], str) and "| head" not in new_args["command"]:
            new_args["command"] = f"{new_args['command']} | head -n {max(20, int(round(safe_u[1] * 5)))}"
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
         returning `{"args": new_args, "source": "barrier-shield", "reason": "..."}` or `None`.
      2. Chain-style `(tool_request_dict, next_fn)`.
    """
    if isinstance(first_arg, str) and isinstance(second_arg, dict):
        has_resource_keys = any(k in second_arg for k in ("batch_files", "limit", "workers", "concurrency", "amount", "delta_spend_usd", "command"))
        if first_arg not in ("terminal", "write_file", "patch", "execute_bash") and not has_resource_keys:
            return None
        new_args, qp = _project_tool_args(second_arg)
        if not qp["deflected"]:
            return None
        return {
            "args": new_args,
            "source": "barrier-shield",
            "reason": f"CBF-QP deflected action along h(x)>={qp['min_h_after']:.2f} (damped {qp['damping_ratio']:.0%})",
            "cbf_projection": qp,
        }

    if isinstance(first_arg, dict) and callable(second_arg):
        args = first_arg.get("arguments")
        if isinstance(args, dict):
            new_args, qp = _project_tool_args(args)
            first_arg["arguments"] = new_args
            first_arg["cbf_projection"] = qp
        return second_arg(first_arg)

    return None


def cbf_llm_request_middleware(
    request: Dict[str, Any],
    second_arg: Optional[Union[Dict[str, Any], Callable[[Dict[str, Any]], Any]]] = None,
    **kwargs: Any,
) -> Any:
    """Control Lyapunov Function (CLF) temperature damping when loop energy V(x) rises."""
    if callable(second_arg):
        if CBF_STATE["history"] and CBF_STATE["history"][-1]["lyapunov_energy_v"] > 0.35 and "temperature" in request:
            request["temperature"] = round(float(request["temperature"]) * 0.65, 3)
        return second_arg(request)

    if CBF_STATE["history"] and CBF_STATE["history"][-1]["lyapunov_energy_v"] > 0.35 and "temperature" in request:
        new_req = dict(request)
        new_req["temperature"] = round(float(new_req["temperature"]) * 0.65, 3)
        return {
            "request": new_req,
            "source": "barrier-shield",
            "reason": "Lyapunov energy V(x) > 0.35; cooled sampling temperature by 0.65x",
        }
    return None
