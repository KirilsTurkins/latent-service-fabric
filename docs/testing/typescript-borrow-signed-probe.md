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

Five host-only profile controls and four input-refusal controls pass across the retained focused runs. Existing rustfmt
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

The next attempt, [run40059928567/job120771018412](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40059928567/job/120771018412),
passed the workspace guard and reached the actual pinned WIT parser. It failed
on the diagnostic's void function because that parser omits a void `result`
field and the graph normalizer indexed it unconditionally. The repair treats
omission as the existing explicit empty result; a regression uses the retained
raw parser graph and still rejects nonvoid drift and invalid type references.
No guest/host compilation or signed case passed in that failed attempt. Its
620,180-byte artifact `12546483197` remains failed and retained (SHA256
`02c0b6d5824e65abc29fcb09c0d2c73353e35882bc69989baa10af408c6ae78d`).

The third attempt, [run40061029424/job120774360900](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40061029424/job/120774360900),
passed actual WIT normalization, typechecking and bundling. Component generation
then failed in 1.206 seconds: Wizer rejected the source-spliced core with
`expected i32 but nothing on stack` at offset `0x880e2a`. The outer read gate had
not been compiled and no signed case executed. Its retained failed artifact is
`12546449437` (660,849 bytes, SHA256
`635ace9c2bd8eda158bcc6c0acdf75284e9e862595b703f1441adceb79cd36a5`).

The closed diagnostic now retains the actual pre-Wizer core (maximum64MiB), raw
and transformed generated bindings (maximum8MiB each), and bounded splice
metadata (maximum1MiB). The exact original synchronous source-splicer call,
receiver and arguments remain intact; its result object identity, core bytes
and imports/exports are checked unchanged by the read-only tap. Default
compilation has no tap. The next attempt collects the missing carrier for the
actual validator failure; these captures do not establish a runtime pass or
authorize an engine-envelope reissue.

The retained carrier from [run40062189778/job120777895009](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40062189778/job/120777895009)
confirmed the shared compiler defect; see the [bounded failure evidence](typescript-borrow-splice-failure.json).
The connection resource-drop wrapper at table slot7386 calls local function104,
which requires two i32 operands, after supplying only the resource handle. Its
correct original resource-drop import is function84 with signature `(i32)->()`.
An existing-import ordinal had been used as a stable function ID after async
disposal preinserted that import. This correlation uses read-only parsing of the
actual retained core, not a simulated or executed Wasm result.

The failed source remains failed. A separate source-owned resolver correction
must produce a fresh normal splicer and engine once, with unchanged normal
low-level-library validation. This programme will consume only that actual
successful tuple through normal source/product validators. The old `9d07`
envelopes are immutable and cannot be reissued for changed source.

The corrected normal prerequisite campaign succeeded at source
`be356d28f93267dc34078ce137d49ed28c28bf47`, run`40062945676`,
job`120780152060` (`workflow_dispatch`, fixed import-function-identity branch).
The reader now pins artifact`12547924676`, 196,485,322 bytes, SHA256
`5b89337277d467076a42d45e301b0b17f1e535c0c58a4ef3cc8bb8ba615d2cfc`.
Its one shared cached extraction passed the original normal engine/splicer
validators with all41 SDK inputs matching that source. The engine bits remain
identical to9d, honestly rebuilt by the normal programme; its new source-bound
input envelope and splicer identities are retained unchanged. The9d native
prerequisite success and failed consumer histories are preserved. A new signed
consumer attempt is pending; no signed or physical pass follows from these
native prerequisites.
