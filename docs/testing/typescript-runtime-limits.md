# TypeScript resource boundaries

The separate `typescript-runtime-limits.yml` programme builds and signs one
ordinary TypeScript component through the normal compiler. It reuses the
authenticated historical engine, splicer and native tools selected by
`tools/typescript_fetch_replay_inputs.py`. It does not rebuild the native host.

The fixture uses ordinary `Promise`, `.then`, `setTimeout`, `clearTimeout` and
`Uint8Array`. It calls no application task broker or HTTP API. Every profile runs
a positive bootstrap, its selected boundary and a fresh invocation, requiring
known outcomes, reaped caller processes, physical owner retirement and clean
node shutdown. A real peer must observe no contacts or mutations.

| Selected boundary | Tasks | Queued work | Native owners | Expected refusal |
| --- | --- | --- | --- | --- |
| Pending reactions: task | 16 | 64 | 256 | Exact task registration resource exhaustion |
| Pending reactions: queue | 64 | 16 | 256 | Exact queued-work registration resource exhaustion |
| Reachable promises: native | 64 | 64 | 64 | Exact Promise native registration resource exhaustion |
| Long timers | 64 | 64 | 256 | Exact timer-start resource exhaustion after eight admissions |
| Linear memory | 64 | 64 | 256 | Known resource exhaustion or guest trap after measured growth |

Executors remain two; waits, timers and results remain eight. These are explicit
test profiles, not a change to the original Fetch profile or a claim of minimum
client requirements. Held Promise graphs remain reachable during admission;
unreachable graphs retire through the existing native garbage collector. All
accepted timers are cleared. The timer callback must never fire.

The memory case narrows the caller budget to 64 MiB beneath the original
128 MiB node ceiling. Its bootstrap and fresh call use that same narrowed
budget. It retains touched 4 MiB arrays, requires at least 32 MiB growth above
bootstrap and rejects fuel exhaustion, deadlines, unknown outcomes or peaks
above the caller limit. It does not catch allocation failure as success.

The retained first attempt was rejected before guest execution because the
controller omitted HTTP authority required by the declared Fetch-world imports.
The controller now supplies the same explicit bounded HTTP grant as the other
zero-contact Fetch fixtures. This grants no implicit permission and does not
relax the real peer's zero-contact check. No resource boundary ran in that attempt.

Execution results are pending. Source controls and type checking alone do not
qualify these boundaries. This programme does not establish late-completion or
cross-tenant isolation and does not close the complete SDK or Fetch matrices.
