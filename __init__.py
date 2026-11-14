"""barrier-shield: Control-Barrier Function & Closed-Loop Lyapunov Safety Controller."""

from __future__ import annotations

try:
    from .engine import (
        CBF_CONTROLLER_SCHEMA,
        CBF_PROJECT_SCHEMA,
        CBF_TELEMETRY_SCHEMA,
        _ensure_json_str,
        handle_cbf_configure_controller,
        handle_cbf_project_action,
        handle_cbf_state_telemetry,
        set_plugin_context as set_engine_context,
    )
    from .middleware import (
        cbf_llm_request_middleware,
        cbf_tool_request_middleware,
        post_llm_call_hook,
        pre_llm_call_hook,
        set_plugin_context as set_middleware_context,
    )
except (ImportError, ValueError):
    from engine import (
        CBF_CONTROLLER_SCHEMA,
        CBF_PROJECT_SCHEMA,
        CBF_TELEMETRY_SCHEMA,
        _ensure_json_str,
        handle_cbf_configure_controller,
        handle_cbf_project_action,
        handle_cbf_state_telemetry,
        set_plugin_context as set_engine_context,
    )
    from middleware import (
        cbf_llm_request_middleware,
        cbf_tool_request_middleware,
        post_llm_call_hook,
        pre_llm_call_hook,
        set_plugin_context as set_middleware_context,
    )

_PLUGIN_CTX = None


def _tool_handler(fn):
    """Wrap a dict-returning engine handler so Hermes tool_call gets a JSON string."""
    def wrapper(args=None, **kwargs):
        result = fn(args if args is not None else {}, **kwargs)
        return _ensure_json_str(result)
    return wrapper


def register(ctx) -> None:
    global _PLUGIN_CTX
    _PLUGIN_CTX = ctx
    set_engine_context(ctx)
    set_middleware_context(ctx)

    ctx.register_tool(
        name="barrier_shield_project_action",
        toolset="barrier_shield",
        schema=CBF_PROJECT_SCHEMA,
        handler=_tool_handler(handle_cbf_project_action),
        is_async=False,
        emoji="🛡️",
    )
    ctx.register_tool(
        name="barrier_shield_state_telemetry",
        toolset="barrier_shield",
        schema=CBF_TELEMETRY_SCHEMA,
        handler=_tool_handler(handle_cbf_state_telemetry),
        is_async=False,
        emoji="📈",
    )
    ctx.register_tool(
        name="barrier_shield_configure_controller",
        toolset="barrier_shield",
        schema=CBF_CONTROLLER_SCHEMA,
        handler=_tool_handler(handle_cbf_configure_controller),
        is_async=False,
        emoji="🎛️",
    )

    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)

    ctx.register_middleware("tool_request", cbf_tool_request_middleware)
    ctx.register_middleware("llm_request", cbf_llm_request_middleware)

    ctx.register_command(
        name="cbf",
        handler=lambda args="": _ensure_json_str(handle_cbf_configure_controller({"mode": args.strip() or "ADAPTIVE_CLF_CBF"}, is_owner=True)),
        description="Control barrier-shield safety envelope mode (STRICT_BARRIER | ADAPTIVE_CLF_CBF | RND_SANDBOX_BOOST)",
    )

    from pathlib import Path
    skills_dir = Path(__file__).parent / "skills"
    if hasattr(ctx, "register_skill") and skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
