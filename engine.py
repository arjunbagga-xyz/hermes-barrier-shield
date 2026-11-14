"""Discrete-Time Exponential Control Barrier Function (CBF-QP) and Control Lyapunov Function solver."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.optimize import minimize


def emit_plugin_event(plugin_name: str, event_type: str, payload: Dict[str, Any]) -> None:
    """Safely broadcast plugin events (no-op fallback if event bus unavailable)."""
    pass


_PLUGIN_CTX: Any = None


def set_plugin_context(ctx: Any) -> None:
    """Store the HermesPluginContext captured during registration."""
    global _PLUGIN_CTX
    _PLUGIN_CTX = ctx


DEFAULT_OWNER_X_MAX = np.array([25.0, 50.0, 16.0, 1.0], dtype=float)


def get_owner_limits_ceiling() -> np.ndarray:
    """Retrieve owner-configured ceiling limits [max_spend, max_blast, max_workers, max_entropy]."""
    ctx = _PLUGIN_CTX
    spend = 25.0
    files = 50.0
    if ctx is not None:
        if hasattr(ctx, "get_config"):
            try:
                spend = float(ctx.get_config("max_budget_usd", 25.0))
                files = float(ctx.get_config("max_blast_radius_files", 50.0))
            except Exception:
                pass
        elif hasattr(ctx, "config") and isinstance(ctx.config, dict):
            spend = float(ctx.config.get("max_budget_usd", 25.0))
            files = float(ctx.config.get("max_blast_radius_files", 50.0))
    return np.array([spend, files, 16.0, 1.0], dtype=float)


# Per-session Control Barrier Function State with temporal decay and pruning
# 4D Agent State x_t = [spend_usd, blast_radius_files, concurrency_workers, entropy_loops]
# Barrier limits x_max = [max_spend, max_blast, max_workers, max_entropy]
SESSION_STATES: Dict[str, Dict[str, Any]] = {}
MAX_SESSION_STATES: int = 256
SESSION_TTL_SECONDS: float = 7200.0  # 2 hours
MAX_HISTORY_PER_SESSION: int = 50


def prune_session_states(
    max_sessions: int = MAX_SESSION_STATES,
    ttl_seconds: float = SESSION_TTL_SECONDS,
) -> None:
    """Evict expired or excess session states so a long-lived gateway doesn't grow memory indefinitely."""
    now = time.time()
    # 1. Prune expired sessions (keep "default")
    expired = [
        sid
        for sid, s in SESSION_STATES.items()
        if sid != "default" and (now - s.get("last_step_time", now)) > ttl_seconds
    ]
    for sid in expired:
        SESSION_STATES.pop(sid, None)

    # 2. If count still exceeds max_sessions, evict LRU (least recently used)
    if len(SESSION_STATES) > max_sessions:
        sorted_sessions = sorted(
            [
                (sid, s.get("last_step_time", 0.0))
                for sid, s in SESSION_STATES.items()
                if sid != "default"
            ],
            key=lambda item: item[1],
        )
        excess = len(SESSION_STATES) - max_sessions
        for sid, _ in sorted_sessions[:excess]:
            SESSION_STATES.pop(sid, None)


def get_session_cbf_state(session_id: str = "default") -> Dict[str, Any]:
    """Retrieve or initialize per-session barrier state with exponential decay toward baseline."""
    sid = str(session_id or "default")
    if sid not in SESSION_STATES:
        prune_session_states()
        owner_ceiling = get_owner_limits_ceiling()
        SESSION_STATES[sid] = {
            "x": np.array([0.0, 0.0, 1.0, 0.05], dtype=float),
            "x_max": owner_ceiling.copy(),
            "owner_x_max": owner_ceiling.copy(),
            "gamma": 0.45,
            "history": [],
            "last_step_time": time.time(),
        }
    state = SESSION_STATES[sid]
    now = time.time()
    elapsed = max(0.0, now - state.get("last_step_time", now))
    state["last_step_time"] = now
    # Exponential decay toward resting baseline (half-life ~60 seconds) so session doesn't stay permanently throttled
    decay_factor = math.exp(-elapsed / 60.0)
    baseline = np.array([0.0, 0.0, 1.0, 0.05], dtype=float)
    state["x"] = baseline + (state["x"] - baseline) * decay_factor
    return state


CBF_STATE: Dict[str, Any] = get_session_cbf_state("default")


def compute_barrier_vector(x: np.ndarray, x_max: np.ndarray) -> np.ndarray:
    """Compute normalized barrier vector h(x) = (x_max - x) / x_max in (-inf, 1]. Safe set C = {x : h(x) >= 0}."""
    return (x_max - x) / np.maximum(x_max, 1e-9)


def compute_lyapunov_energy(x: np.ndarray, x_max: np.ndarray) -> float:
    """Control Lyapunov Function V(x) = 1/2 ||x / x_max||_2^2 measuring normalized system energy."""
    rel = x / np.maximum(x_max, 1e-9)
    return float(0.5 * np.sum(rel ** 2))


def solve_cbf_qp(
    x_current: np.ndarray,
    u_nominal: np.ndarray,
    x_max: np.ndarray,
    gamma: float = 0.45,
) -> Dict[str, Any]:
    """
    Solve the Discrete-Time Control Barrier Function Quadratic Program (DT-CBF-QP):
        min_{u}  1/2 ||u - u_nom||_2^2
        s.t.     h_i(x_t + u) - h_i(x_t) >= -gamma * h_i(x_t)   for all i
                 0 <= u_i <= u_nom_i (when u_nom_i >= 0)
    Equivalently, since h_i(x) = (x_max_i - x_i) / x_max_i:
        x_t + u <= x_t + gamma * (x_max - x_t)  ==>  u <= gamma * (x_max - x_t)
    We solve via SLSQP with coupled multi-resource barrier constraints (including cross-coupling
    between concurrency and blast radius) and compare against closed-form analytical bounds.
    """
    h_now = compute_barrier_vector(x_current, x_max)
    u_nom = np.maximum(0.0, np.asarray(u_nominal, dtype=float))

    # Coupling matrix B: concurrency slightly amplifies blast-radius and spend step
    B = np.array([
        [1.0, 0.0, 0.05, 0.0],
        [0.0, 1.0, 0.15, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=float)

    def barrier_constraint(u: np.ndarray) -> np.ndarray:
        x_next = x_current + B @ u
        h_next = compute_barrier_vector(x_next, x_max)
        # Required: h_next - (1 - gamma) * h_now >= 0
        return h_next - (1.0 - gamma) * h_now

    bounds = [(0.0, max(float(u_nom[i]), 1e-9)) for i in range(len(u_nom))]
    res = minimize(
        fun=lambda u: float(0.5 * np.sum((u - u_nom) ** 2)),
        x0=np.minimum(u_nom, gamma * np.maximum(0.0, x_max - x_current)),
        method="SLSQP",
        bounds=bounds,
        constraints=[{"type": "ineq", "fun": barrier_constraint}],
        options={"ftol": 1e-10, "maxiter": 100},
    )

    u_star = np.clip(res.x, 0.0, u_nom)
    # Enforce hard analytical forward-invariance guarantee
    max_safe_step = np.maximum(0.0, gamma * (x_max - x_current))
    u_star = np.minimum(u_star, np.linalg.solve(B, max_safe_step))
    u_star = np.maximum(0.0, u_star)

    x_next = x_current + B @ u_star
    h_next = compute_barrier_vector(x_next, x_max)

    nom_norm = float(np.linalg.norm(u_nom))
    diff_norm = float(np.linalg.norm(u_star - u_nom))
    damping_ratio = round(diff_norm / nom_norm, 4) if nom_norm > 1e-9 else 0.0
    deflected = bool(damping_ratio > 0.01)

    return {
        "u_nominal": [round(float(v), 4) for v in u_nom],
        "u_safe_projected": [round(float(v), 4) for v in u_star],
        "x_before": [round(float(v), 4) for v in x_current],
        "x_after": [round(float(v), 4) for v in x_next],
        "h_before": [round(float(v), 4) for v in h_now],
        "h_after": [round(float(v), 4) for v in h_next],
        "min_h_after": round(float(np.min(h_next)), 4),
        "lyapunov_energy_v": round(compute_lyapunov_energy(x_next, x_max), 4),
        "damping_ratio": damping_ratio,
        "deflected": deflected,
        "forward_invariant_verified": bool(np.all(h_next >= -1e-7)),
    }


def handle_cbf_project_action(args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """
    Project a proposed nominal control action u_nom = [delta_spend_usd, batch_files, workers, loop_entropy]
    onto the forward-invariant safe barrier manifold C = {x : h(x) >= 0} via CBF-QP.
    """
    session_id = str(args.get("session_id") or kwargs.get("session_id") or "default")
    state = get_session_cbf_state(session_id)
    gamma = float(args.get("gamma", state["gamma"]))
    if "state_x" in args and args["state_x"] is not None:
        x_curr = np.asarray(args["state_x"], dtype=float)
    else:
        x_curr = state["x"].copy()

    owner_ceiling = state.get("owner_x_max", get_owner_limits_ceiling())
    if "limits_x_max" in args and args["limits_x_max"] is not None:
        proposed = np.asarray(args["limits_x_max"], dtype=float)
        # Ensure model cannot arbitrarily raise limits beyond owner ceiling in project action
        x_max = np.minimum(proposed, owner_ceiling)
    else:
        x_max = state["x_max"].copy()

    u_nom = np.array([
        float(args.get("delta_spend_usd", 2.0)),
        float(args.get("batch_files", 25.0)),
        float(args.get("workers", 4.0)),
        float(args.get("loop_entropy", 0.1)),
    ], dtype=float)

    qp = solve_cbf_qp(x_curr, u_nom, x_max, gamma=gamma)
    if args.get("commit_state", True):
        state["x"] = np.asarray(qp["x_after"], dtype=float)

    # Impact metrics — what the barrier contained vs the nominal request
    impact = {
        "files_averted": round(float(qp["u_nominal"][1] - qp["u_safe_projected"][1]), 2),
        "spend_averted_usd": round(float(qp["u_nominal"][0] - qp["u_safe_projected"][0]), 2),
        "workers_averted": round(float(qp["u_nominal"][2] - qp["u_safe_projected"][2]), 2),
        "entropy_averted": round(float(qp["u_nominal"][3] - qp["u_safe_projected"][3]), 4),
        "damping_percent": round(qp["damping_ratio"] * 100, 1),
        "deflected": qp["deflected"],
        "forward_invariant": qp["forward_invariant_verified"],
    }

    if qp["deflected"]:
        summary = (
            "🛡️ barrier-shield: contained — "
            f"{impact['files_averted']} files averted, "
            f"${impact['spend_averted_usd']} spend damped, "
            f"{impact['workers_averted']} workers capped "
            f"({impact['damping_percent']}% damping)"
        )
    else:
        summary = (
            f"🛡️ barrier-shield: safe — "
            f"min_h={qp['min_h_after']}, no deflection needed"
        )

    qp["impact"] = impact
    qp["summary"] = summary
    qp["transcript_directive"] = summary  # plain text line, no visual
    qp["status"] = "CBF_DEFLECTED_SMOOTHLY" if qp["deflected"] else "NOMINAL_SAFE"
    state["history"].append(qp)
    if len(state["history"]) > MAX_HISTORY_PER_SESSION:
        state["history"] = state["history"][-MAX_HISTORY_PER_SESSION:]
    emit_plugin_event("barrier-shield", "cbf_projection", qp)
    return qp


def handle_cbf_state_telemetry(args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Inspect or reset the current 4D Control Barrier Function state x_t and barrier margins h(x_t)."""
    session_id = str(args.get("session_id") or kwargs.get("session_id") or "default")
    state = get_session_cbf_state(session_id)
    if args.get("reset"):
        state["x"] = np.array([0.0, 0.0, 1.0, 0.05], dtype=float)
        state["history"].clear()

    h_vec = compute_barrier_vector(state["x"], state["x_max"])
    return {
        "status": "ok",
        "session_id": session_id,
        "state_labels": ["spend_usd", "blast_radius_files", "concurrency_workers", "loop_entropy"],
        "state_x": [round(float(v), 4) for v in state["x"]],
        "limits_x_max": [round(float(v), 4) for v in state["x_max"]],
        "owner_limits_x_max": [round(float(v), 4) for v in state.get("owner_x_max", get_owner_limits_ceiling())],
        "barrier_h": [round(float(v), 4) for v in h_vec],
        "min_barrier_h": round(float(np.min(h_vec)), 4),
        "lyapunov_energy_v": round(compute_lyapunov_energy(state["x"], state["x_max"]), 4),
    }


CBF_PROJECT_SCHEMA: Dict[str, Any] = {
    "name": "barrier_shield_project_action",
    "description": (
        "Solve the Discrete-Time Control Barrier Function Quadratic Program (CBF-QP) to project "
        "a nominal action u_nom onto the forward-invariant safe set h(x) >= 0 without hard blocking."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "delta_spend_usd": {"type": "number", "description": "Nominal incremental spend in USD."},
            "batch_files": {"type": "number", "description": "Nominal number of files/items modified in batch."},
            "workers": {"type": "number", "description": "Nominal concurrent worker count."},
            "loop_entropy": {"type": "number", "description": "Nominal step entropy increment."},
            "gamma": {"type": "number", "description": "Barrier decay parameter gamma in (0, 1]."},
            "commit_state": {"type": "boolean", "description": "Whether to advance state x_{t+1} = x_t + B*u*."},
        },
    },
}

CBF_TELEMETRY_SCHEMA: Dict[str, Any] = {
    "name": "barrier_shield_state_telemetry",
    "description": "Return current Control Barrier Function margins h(x) and Control Lyapunov energy V(x).",
    "parameters": {
        "type": "object",
        "properties": {
            "reset": {"type": "boolean", "description": "Reset cumulative barrier state to initial values."},
        },
    },
}


CONTROLLER_MODES: Dict[str, Dict[str, Any]] = {
    "STRICT_BARRIER": {"gamma": 0.25, "temp_gain": 0.50, "desc": "High-damping conservative envelope for production"},
    "ADAPTIVE_CLF_CBF": {"gamma": 0.45, "temp_gain": 0.65, "desc": "Balanced exponential barrier + Lyapunov damping"},
    "RND_SANDBOX_BOOST": {"gamma": 0.85, "temp_gain": 0.90, "desc": "Wide exploration envelope for local R&D benchmarks"},
}


def handle_cbf_configure_controller(args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """
    Closed-Loop Control Mechanism for barrier-shield:
    Allows the operator or upstream dynamical plugins (e.g. velvet-takens Lyapunov exponent)
    to switch control modes, tune barrier decay rate gamma in (0.05, 1.0], update ceiling
    limits x_max = [spend_usd, blast_files, workers, loop_entropy], or trigger an emergency
    Lyapunov cooldown.
    Limits cannot be raised beyond owner-configured ceilings by model calls.
    """
    session_id = str(args.get("session_id") or kwargs.get("session_id") or "default")
    state = get_session_cbf_state(session_id)
    mode = str(args.get("mode", "")).upper()
    if mode in CONTROLLER_MODES:
        state["gamma"] = CONTROLLER_MODES[mode]["gamma"]
        state["mode"] = mode

    if "gamma" in args and args["gamma"] is not None:
        state["gamma"] = float(np.clip(float(args["gamma"]), 0.05, 1.0))

    limits_note = None
    if "limits_x_max" in args and isinstance(args["limits_x_max"], list) and len(args["limits_x_max"]) == 4:
        proposed = np.asarray(args["limits_x_max"], dtype=float)
        owner_ceiling = state.get("owner_x_max")
        if owner_ceiling is None:
            owner_ceiling = get_owner_limits_ceiling()
            state["owner_x_max"] = owner_ceiling.copy()

        # Check if caller is privileged owner (e.g. from internal API or CLI command)
        is_owner = bool(kwargs.get("is_owner", False))
        if is_owner:
            state["owner_x_max"] = np.maximum(proposed, 1e-3)
            state["x_max"] = state["owner_x_max"].copy()
        else:
            # Model cannot arbitrarily raise limits beyond owner-set ceiling.
            # It may only tighten (lower) limits or keep them within owner bounds.
            clamped = np.minimum(proposed, owner_ceiling)
            # Ensure strictly positive minimum limits
            clamped = np.maximum(clamped, np.array([0.1, 1.0, 1.0, 0.01], dtype=float))
            if not np.allclose(proposed, clamped, atol=1e-4):
                limits_note = (
                    f"Proposed limits exceeded owner ceiling {list(np.round(owner_ceiling, 2))}; "
                    f"clamped to {list(np.round(clamped, 2))}."
                )
            state["x_max"] = clamped

    if args.get("lyapunov_lambda1") is not None:
        # Automatic cross-plugin feedback control: if velvet-takens reports positive Lyapunov exponent
        # (chaotic instability), automatically tighten gamma!
        lam1 = float(args["lyapunov_lambda1"])
        if lam1 > 0.02:
            state["gamma"] = round(max(0.15, 0.45 / (1.0 + 4.0 * lam1)), 3)
            state["mode"] = "CHAOS_COUPLED_TIGHTENED"

    if args.get("emergency_dampen"):
        state["gamma"] = 0.15
        state["mode"] = "EMERGENCY_DAMPENED"

    h_vec = compute_barrier_vector(state["x"], state["x_max"])
    labels = ["spend_usd", "blast_radius_files", "concurrency_workers", "loop_entropy"]
    bottleneck_idx = int(np.argmin(h_vec))

    res = {
        "status": "CONTROLLER_UPDATED",
        "session_id": session_id,
        "active_mode": state.get("mode", "ADAPTIVE_CLF_CBF"),
        "gamma": state["gamma"],
        "state_x": [round(float(v), 4) for v in state["x"]],
        "limits_x_max": [round(float(v), 4) for v in state["x_max"]],
        "owner_limits_x_max": [round(float(v), 4) for v in state.get("owner_x_max", get_owner_limits_ceiling())],
        "barrier_h": [round(float(v), 4) for v in h_vec],
        "active_bottleneck_channel": labels[bottleneck_idx],
        "active_bottleneck_margin_h": round(float(h_vec[bottleneck_idx]), 4),
        "lyapunov_energy_v": round(compute_lyapunov_energy(state["x"], state["x_max"]), 4),
    }
    if limits_note:
        res["limits_note"] = limits_note
    return res


CBF_CONTROLLER_SCHEMA: Dict[str, Any] = {
    "name": "barrier_shield_configure_controller",
    "description": (
        "Interactive closed-loop control mechanism for the Control-Barrier safety shield: "
        "switch modes (STRICT_BARRIER, ADAPTIVE_CLF_CBF, RND_SANDBOX_BOOST), tune gamma, "
        "adjust resource ceilings x_max (tightening only, bounded by owner ceiling), or couple gamma directly to velvet-takens Lyapunov exponent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "Control mode: STRICT_BARRIER, ADAPTIVE_CLF_CBF, or RND_SANDBOX_BOOST."},
            "gamma": {"type": "number", "description": "Class-K barrier decay rate gamma in [0.05, 1.0]."},
            "limits_x_max": {"type": "array", "items": {"type": "number"}, "description": "[max_spend, max_files, max_workers, max_entropy] - cannot exceed owner-configured ceilings."},
            "lyapunov_lambda1": {"type": "number", "description": "Optional Largest Lyapunov Exponent from velvet-takens for chaos-coupled damping."},
            "emergency_dampen": {"type": "boolean", "description": "Immediately drop gamma to 0.15 emergency damping."},
        },
    },
}


def _ensure_json_str(res: Any) -> str:
    if isinstance(res, str):
        return res
    return json.dumps(res)
