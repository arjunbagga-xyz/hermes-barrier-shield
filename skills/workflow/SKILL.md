---
name: barrier-shield-workflow
description: Enforce continuous forward-invariant safety envelopes h(x) >= 0 via Control-Barrier Function Quadratic Programming (CBF-QP) and closed-loop Lyapunov damping.
---
# Velvet Control-Barrier Safety Shield Workflow
When executing batch file mutations, concurrent subagents, shell pipelines, or budgeted API/trading operations:
1. Use `barrier_shield_project_action` or `barrier_shield_configure_controller` to project nominal control inputs `u_nom` onto the safe tangent cone `h(x_{t+1}) >= (1 - gamma) h(x_t)`.
2. Emit a standalone paragraph `::barrier-shield{min_h="..." damping="..."}` when an action is smoothly deflected along the barrier boundary.
