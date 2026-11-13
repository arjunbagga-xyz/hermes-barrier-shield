---
name: barrier-shield-workflow
description: Enforce continuous forward-invariant safety envelopes h(x) >= 0 via Control-Barrier Function Quadratic Programming (CBF-QP) and closed-loop Lyapunov damping.
---
# Velvet Control-Barrier Safety Shield Workflow
When executing batch file mutations, concurrent subagents, shell pipelines, or budgeted API/trading operations:
1. Use `barrier_shield_project_action` or `barrier_shield_configure_controller` to project nominal control inputs `u_nom` onto the safe tangent cone `h(x_{t+1}) >= (1 - gamma) h(x_t)`.
2. Emit a standalone paragraph `::barrier-shield{min_h="..." damping="..."}` when an action is smoothly deflected along the barrier boundary. The directive MUST use attribute syntax (`key="value"` pairs), NOT a JSON object — the desktop plugin's transcript-directive parser only matches attribute-style directives and prints raw JSON as text otherwise.

## Pitfalls
-
- **Tool handlers return dicts internally but Hermes `tool_call` requires strings.** Engine handlers (`handle_*`) return dicts for middleware/command/internal callers; the registered tool handler must wrap them (e.g. `_ensure_json_str` or a `_tool_handler` closure) so `tool_call` gets a JSON string. Without wrapping, calls fail with `unsupported result type: dict`. This pattern applies across multiple plugins including `omnisight`, `ghostbox`, and any plugin whose engine handlers return `dict` instead of `str`.
- **Directive attrs are the only data channel to the card.** The desktop plugin receives only parsed attrs. Pass every value the card/pane/chip needs (mode, gamma, limits, min_h before/after) through the directive string — there is no shared backend state channel to the frontend.
- **Desktop visual surfaces default to static.** A pane or chip registered with a static `render: () => jsx(...)` never updates. Share state across components with a module-level store updated by the directive's render callback, plus a `CustomEvent` + `useEffect` listener so pane/chip re-render when a new directive lands.

## Controller modes
- `STRICT_BARRIER`: gamma 0.25 — high-damping conservative envelope for production.
- `ADAPTIVE_CLF_CBF`: gamma 0.45 — balanced (default).
- `RND_SANDBOX_BOOST`: gamma 0.85 — wide exploration envelope for R&D.
- `emergency_dampen`: drops gamma to 0.15.
- Lyapunov coupling: pass `lyapunov_lambda1` > 0.02 to auto-tighten gamma (chaos-takens feedback).

## Safety configuration
- Argument rewriting (`enable_argument_rewriting`) and temperature damping (`enable_temperature_damping`) are opt-in and disabled by default.
- Payment amounts are never scaled or modified, and terminal commands are never modified.

## State semantics
State x = [spend_usd, blast_radius_files, concurrency_workers, loop_entropy]; limits x_max default [25, 50, 16, 1.0]. State decays exponentially toward resting baseline per session. `commit_state` (default true) advances x. Use `commit_state=False` for dry-run projections. Reset via `barrier_shield_state_telemetry({"reset": true}).`
