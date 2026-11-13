# barrier-shield

**Control-Barrier Function ($h(x) \ge 0$) & Lyapunov Continuous Safety Shield for Hermes Agent.**

Current AI safety guardrails are binary regex brick walls: they either let a dangerous action through at 100% speed or throw a hard `PermissionError` that crashes the agent's reasoning loop.

Inspired by aerospace flight-envelope protection (Ames et al., *Control Barrier Functions: Theory and Applications*), `barrier-shield` defines a continuous safe state manifold $\mathcal{C} = \{x \in \mathbb{R}^n : h_i(x) \ge 0\}$ over cumulative API/compute spend, filesystem blast radius, concurrency load, and irreversible mutation intensity. Before any tool executes (`tool_request` middleware), `barrier-shield` solves a real-time **Quadratic Program (CBF-QP)**:

$$u^* = \arg\min_{u \in \mathcal{U}} \frac{1}{2}\|u - u_{\text{nom}}\|_2^2 \quad \text{s.t.} \quad h_i(x_t + B u) - h_i(x_t) \ge -\gamma_i h_i(x_t)$$

By **Nagumo's Theorem**, $\mathcal{C}$ is mathematically **forward-invariant**: the agent never crashes into a hard error wall, and never crosses $h(x) < 0$—instead, its batch sizes, concurrency, and blast radius smoothly and tangentially decelerate along the safety boundary!

## Configuration

All active argument rewriting and temperature damping behaviors are opt-in and disabled by default:

- `enable_argument_rewriting` (boolean, default: `false`): When enabled, projects resource parameters (`batch_files`, `workers`, `concurrency`, `limit`) onto safe forward-invariant bounds for tools explicitly listed in `rewritable_tools`. Terminal commands and financial payment amounts are never modified.
- `rewritable_tools` (list of strings, default: `[]`): Explicit allowlist of tool names whose resource parameters may be adjusted when `enable_argument_rewriting` is true.
- `enable_temperature_damping` (boolean, default: `false`): When enabled, applies Lyapunov energy damping to cool sampling temperature when loop instability rises.
- State is scoped per `session_id` and decays exponentially toward baseline over time to prevent permanent throttling across long-running sessions.
