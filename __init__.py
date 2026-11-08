"""barrier-shield: Control-Barrier Function & Closed-Loop Lyapunov Safety Controller."""

from __future__ import annotations

try:
    from .engine import (
        CBF_CONTROLLER_SCHEMA,
        CBF_PROJECT_SCHEMA,
        CBF_TELEMETRY_SCHEMA,
        handle_cbf_configure_controller,
        handle_cbf_project_action,
        handle_cbf_state_telemetry,
    )
    from .middleware import (
        cbf_llm_request_middleware,
        cbf_tool_request_middleware,
        post_llm_call_hook,
        pre_llm_call_hook,
    )
except (ImportError, ValueError):
    from engine import (
        CBF_CONTROLLER_SCHEMA,
        CBF_PROJECT_SCHEMA,
        CBF_TELEMETRY_SCHEMA,
        handle_cbf_configure_controller,
        handle_cbf_project_action,
        handle_cbf_state_telemetry,
    )
    from middleware import (
        cbf_llm_request_middleware,
        cbf_tool_request_middleware,
        post_llm_call_hook,
        pre_llm_call_hook,
    )


def register(ctx) -> None:
    ctx.register_tool(
        name="barrier_shield_project_action",
        toolset="barrier_shield",
        schema=CBF_PROJECT_SCHEMA,
        handler=handle_cbf_project_action,
        is_async=False,
        emoji="🛡️",
    )
    ctx.register_tool(
        name="barrier_shield_state_telemetry",
        toolset="barrier_shield",
        schema=CBF_TELEMETRY_SCHEMA,
        handler=handle_cbf_state_telemetry,
        is_async=False,
        emoji="📈",
    )
    ctx.register_tool(
        name="barrier_shield_configure_controller",
        toolset="barrier_shield",
        schema=CBF_CONTROLLER_SCHEMA,
        handler=handle_cbf_configure_controller,
        is_async=False,
        emoji="🎛️",
    )

    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)

    ctx.register_middleware("tool_request", cbf_tool_request_middleware)
    ctx.register_middleware("llm_request", cbf_llm_request_middleware)

    ctx.register_command(
        name="cbf",
        handler=lambda args="": handle_cbf_configure_controller({"mode": args.strip() or "ADAPTIVE_CLF_CBF"}),
        description="Control barrier-shield safety envelope mode (STRICT_BARRIER | ADAPTIVE_CLF_CBF | RND_SANDBOX_BOOST)",
    )

    from pathlib import Path
    skills_dir = Path(__file__).parent / "skills"
    if hasattr(ctx, "register_skill") and skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
