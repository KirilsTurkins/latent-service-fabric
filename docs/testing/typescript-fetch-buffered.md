# Emitted buffered-body limits

This separate #691 programme compiles one ordinary global Response caller and
executes five signed/admitted cases plus a fresh activation. It does not repeat
the earlier31-case network/lifecycle programme. Select it explicitly with
`qualify_typescript_fetch_conformance.py --buffered-only`; the default remains
the complete network programme.

The first case reads131073 copied bytes in exact65536/65536/1 windows. Input
mutation cannot change the copied body. Microtask checkpoints before reading,
including after acquiring a reader, must leave bodyUsed false: no eager pull
is permitted. Another case cancels after one window, requires end-of-stream
and refuses reconsumption. Explicit tee/pipe/iteration refusals, the1048576-byte
body API ceiling and distinct null/empty-body disturbance are also observed.
The last activation repeats the first case to check fresh module/reader state.

The original one-request manifest, Task16/Queue16/Native64 and all other owner,
fuel/memory/body/cell limits remain. Both missing-grant controls run before
entry. Every entered case must charge zero outbound requests, the real peer
must observe no connection/request/mutation, and original provider/physical
idle checks plus clean reaped node/peer shutdown remain required. Normal source
capture, typecheck, component build, signing and authenticated historical
engine/native inputs are retained.

This observes backpressure over already-buffered bytes, not network streaming,
stream uploads, tee support or engine heap/reaction/timer exhaustion. Source
controls and typechecking do not qualify emitted execution; actual results
remain pending until the dedicated workflow passes.
