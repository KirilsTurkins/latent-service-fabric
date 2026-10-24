# TypeScript signed borrow-release probe: source integration stage

This source packet adds a closed compiler diagnostic, finite canonical read
wrapper, real component composer and signed host harness. None has been built
or executed together. It is partial #745 work, with no Node socket, whole-cost,
kernel-retirement or production-enablement claim.

The internal `Compiler.compile(..., diagnostic_profile=...)` selector accepts
only the exact maintained source/WIT graph and import runtime. It rejects extra
files, changed bytes, captured application modules, changed generated read
declarations and application selection of its private builtin. The selected
application imports exactly the original streams interface, its wrapped alias
and the pure diagnostic interface. Default selection leaves generated binding
bytes unchanged. Compiler provenance includes all new source inputs; normal
engine-input validators and native engine paths remain unchanged.

The component composer imports `latent:network/streams@0.1.0` once, passes that
same instance to the gate and actual compiler-built TypeScript component, and
aliases the gate's original resource types. It preserves raw compiler bytes and
observation separately from the composed signing observation. The maintained
cryptographic package admission machinery signs/admit the actual composed
bytes. No JSON resource-handle adoption is used. Pinned encoder API source was
inspected; actual encoder compilation, validation and component linking remain
unexecuted.

The gate forwards seven operations and wraps one read. `entered()==1` requires
an actually started inner host read, nonzero child handle, waitable join and
parked wrapper. Cancellation records phase2 while retaining that read. Real
peer release lets the callback dispose an owned result, drop the actual child
and waitable set, and invoke canonical task.cancel. Phase3 or borrow release
never certifies provider IoCall/IoTransfer retirement. The fixture checks the
actual public `activation-runtime-import-cancelled` rejection without masking
finally/finish errors. It must use the new OWN-result engine with the actual
retired-finish/cancel-race fixes after that engine's native prerequisite campaign succeeds.
The historical #1399 engine is explicitly refused as a pass candidate.

The finite signed harness has four semantic cases and fresh successful
admission after each root failure:

| Case | Real peer barriers | Planned network WIT calls |
| --- | --- | --- |
| Normal copy/dispose | started read, `norm`, one-byte result, consuming close | 5 |
| Logical cancellation | `canc`, pending read owner sample, `rels`, actual borrow acknowledgement, `ack!`, separately admitted same-resource permit read, consuming close | 8 |
| Root trap with held read | primary plus second admitted control connection, `canc`, both pending-read owner sample, control permit/read/dispose/close, primary `held`, intentional terminal Wasm trap | 8 |
| Original root deadline with held read | same control barriers, then finite wait under original deadline | 8 |

The mode1 JS branch throws and catches only the exact intentional Error message,
then calls a pure diagnostic that requires phase2 before executing an actual
integer division by zero. Other JS errors rethrow unchanged; wrong gate phase
traps with ordinary Unreachable. The host requires the receipt's original
closed `activation.guest-trap-kind=integer-division-by-zero`, so a generic
GuestTrap or lost JS assertion cannot masquerade as the intended abrupt Wasm
root trap. This pure diagnostic adds no network authority, owner or quota.

The second control connection uses the same endpoint grant and original limits.
Its read, buffers, transfer and closure are recorded separately. Every dispatch,
including chunk-bytes and consuming close, fits the original eight requests;
no quota is raised. A deadline before the actual post-control `held` barrier is
failure. The original root deadline is never restarted. The provider source has
separate read/write directions and does not hold its connection mutex across
readiness waits; actual hosted duplex progress remains unexecuted.

At post-ack sampling the original connection/socket and its admitted IoCall and
IoTransfer must remain live until consuming close. The extra one-byte permit
read has its own borrow/buffer reservations and is never attributed to the
cancelled child. Actual counts are logged. Root failure samples either retained
owners or actual retirement; all actual peer sockets must close and all shared
owners drain before the next fresh activation. The logical reference provider
cannot certify kernel physical retirement. Raw future typed-result cleanup
records must also be retained by the actual engine campaign.

Four host-only profile controls and four input-refusal controls pass without skips. Existing rustfmt
parsed the two new Rust files; this is not Rust typechecking or signed evidence.
The prepared `BORROW-COMPILE.json` input contract and retained OWN qualification
receipt bind the exact `latent.typescript.owned-result-prerequisites.v1` native
prerequisite scope. Its canonical-component, signed, physical and whole-cost
claims remain explicitly false. The authenticated product selector, real
tsc/Jco/component build and bounded hosted owning
workflow must be reviewed after the fresh engine product is available. A source-only input selector and hosted recipe now accompany the harness.
The actual successful prerequisite source is `9d07a6dfa3ebb77aa75eb1b5899cb9360e26728d`,
run `40056035407`, job `120759116551`, artifact `12546161304` (196,485,292 bytes,
SHA256 `b4f21ecfb457adf9bb206c4c0b3ec36cbfd786f0da9e2ea2d8ca9d9e9a676123`).
The source reader pins that exact tuple and preserves the original native-only
receipt. One shared extraction from its authenticated cached carrier passed the
unchanged normal engine/splicer validators and immutable producer-source checks.
Its first failed run remains failed. No new campaign, component/engine build,
download or publication has occurred in this source review.

The first signed owning attempt, [run40059659439/job120770194309](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40059659439/job/120770194309),
failed before guest/host compilation with
`compiler-working-directory-outside-captured-workspace`: the diagnostic used a
sibling isolation directory while its compiler cwd was `prepared/project`.
The fix uses the existing `prepared` parent for both project and build. The
normal isolation guard is unchanged; this failed attempt establishes no
canonical or signed runtime pass and remains retained.
