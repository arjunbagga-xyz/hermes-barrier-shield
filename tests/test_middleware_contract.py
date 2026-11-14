"""Tests for barrier-shield middleware signature contract, config retrieval, and safety controls."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from engine import (
    SESSION_STATES,
    get_session_cbf_state,
    handle_cbf_configure_controller,
    handle_cbf_project_action,
    prune_session_states,
)
from middleware import (
    cbf_llm_request_middleware,
    cbf_tool_request_middleware,
    get_plugin_config,
    post_llm_call_hook,
    pre_llm_call_hook,
    set_plugin_context,
)
import __init__ as barrier_shield
register = barrier_shield.register


class MockContext:
    def __init__(self, config=None):
        self.config = config or {}
        self.tools = {}
        self.hooks = {}
        self.middlewares = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_middleware(self, hook_type, fn):
        self.middlewares[hook_type] = fn

    def register_command(self, name, handler, description="", **kwargs):
        self.commands[name] = {"handler": handler, "description": description}


def test_tool_request_middleware_keyword_args_no_type_error():
    """Verify Hermes keyword-only middleware call does NOT raise TypeError."""
    ctx = MockContext({"enable_argument_rewriting": False})
    set_plugin_context(ctx)

    # Hermes calls middleware with keyword arguments only:
    result = cbf_tool_request_middleware(
        tool_name="some_tool",
        args={"limit": 10},
        original_args={"limit": 10},
        session_id="test_sess_1",
    )
    # Default is disabled rewriting, should return None cleanly without TypeError
    assert result is None


def test_tool_request_middleware_opt_in_rewriting():
    """Verify opt-in rewriting reads config from ctx and returns {'args': new_args}."""
    ctx = MockContext({
        "enable_argument_rewriting": True,
        "rewritable_tools": ["batch_fetcher"],
    })
    set_plugin_context(ctx)

    # First, prime the session state near boundary so an aggressive action will deflect
    sid = "test_rewrite_sess"
    state = get_session_cbf_state(sid)
    # Put state close to limits: blast radius already 48 out of 50
    state["x"] = np.array([20.0, 48.0, 10.0, 0.5], dtype=float)

    # Call with keywords as Hermes does:
    result = cbf_tool_request_middleware(
        tool_name="batch_fetcher",
        args={"batch_files": 20, "workers": 8},
        session_id=sid,
    )

    assert result is not None
    assert "args" in result
    # batch_files should be damped below 20
    assert result["args"]["batch_files"] < 20


def test_terminal_commands_never_rewritten():
    """Verify terminal execution tools are never modified even if in allowlist."""
    ctx = MockContext({
        "enable_argument_rewriting": True,
        "rewritable_tools": ["terminal", "bash", "sh", "execute_bash"],
    })
    set_plugin_context(ctx)

    for t_name in ("terminal", "bash", "sh", "execute_bash"):
        res = cbf_tool_request_middleware(
            tool_name=t_name,
            args={"command": "rm -rf /tmp/foo"},
            session_id="test_term_sess",
        )
        assert res is None


def test_llm_request_middleware_keyword_args():
    """Verify llm_request middleware handles keyword arguments and respects damping config."""
    ctx = MockContext({"enable_temperature_damping": False})
    set_plugin_context(ctx)

    res = cbf_llm_request_middleware(
        request={"temperature": 0.8},
        session_id="test_llm_sess",
    )
    assert res is None

    # Enable damping and induce high Lyapunov energy
    ctx_damped = MockContext({"enable_temperature_damping": True})
    set_plugin_context(ctx_damped)
    sid = "test_llm_damped_sess"
    state = get_session_cbf_state(sid)
    state["history"].append({"lyapunov_energy_v": 0.8})

    res_damped = cbf_llm_request_middleware(
        request={"temperature": 0.8},
        session_id=sid,
    )
    assert res_damped is not None
    assert "request" in res_damped
    assert res_damped["request"]["temperature"] < 0.8


def test_configure_controller_prevents_arbitrary_limit_raising():
    """Verify the model cannot arbitrarily raise limits beyond owner-configured ceilings."""
    ctx = MockContext({
        "max_budget_usd": 25.0,
        "max_blast_radius_files": 50.0,
    })
    set_plugin_context(ctx)
    sid = "test_limits_protect_sess"
    state = get_session_cbf_state(sid)

    # Attempt to raise limits to huge numbers as an autonomous model tool call:
    res = handle_cbf_configure_controller({
        "session_id": sid,
        "limits_x_max": [100000.0, 500000.0, 1000.0, 100.0],
    })

    # Limits must be clamped to owner ceilings [25.0, 50.0, 16.0, 1.0]
    assert state["x_max"][0] <= 25.0
    assert state["x_max"][1] <= 50.0
    assert state["x_max"][2] <= 16.0
    assert state["x_max"][3] <= 1.0
    assert "limits_note" in res

    # Model can tighten (lower) limits safely:
    res_tight = handle_cbf_configure_controller({
        "session_id": sid,
        "limits_x_max": [10.0, 20.0, 4.0, 0.5],
    })
    assert state["x_max"][0] == 10.0
    assert state["x_max"][1] == 20.0


def test_session_states_pruning():
    """Verify session state cache does not grow memory indefinitely."""
    # Add multiple test sessions
    now = time.time()
    for i in range(300):
        sid = f"prune_test_sess_{i}"
        SESSION_STATES[sid] = {
            "x": np.array([0.0, 0.0, 1.0, 0.05]),
            "x_max": np.array([25.0, 50.0, 16.0, 1.0]),
            "gamma": 0.45,
            "history": [{"step": j} for j in range(80)],
            "last_step_time": now - (10000 if i < 50 else 10),
        }

    prune_session_states(max_sessions=100, ttl_seconds=3600)
    assert len(SESSION_STATES) <= 101  # 100 max + default
    # Verify expired sessions were cleaned up
    assert "prune_test_sess_0" not in SESSION_STATES


def test_full_plugin_registration():
    """Verify complete plugin register() surface."""
    ctx = MockContext()
    register(ctx)

    assert "barrier_shield_project_action" in ctx.tools
    assert "barrier_shield_state_telemetry" in ctx.tools
    assert "barrier_shield_configure_controller" in ctx.tools
    assert "pre_llm_call" in ctx.hooks
    assert "post_llm_call" in ctx.hooks
    assert "tool_request" in ctx.middlewares
    assert "llm_request" in ctx.middlewares
    assert "cbf" in ctx.commands
