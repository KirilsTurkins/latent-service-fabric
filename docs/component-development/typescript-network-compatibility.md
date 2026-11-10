# TypeScript networking compatibility and prerequisite boundary

Dependency implementation reviewed on 2026-11-09, with #738/#739 open status
rechecked on 2026-11-10; compiler-gate, Socket event and idle-timeout
continuations on 2026-11-10 for issue #745 and integration into
`feat/typescript-runtime-745`, starting at
`83c339673b87afabfa06f3a8e818324f46c1ae6f`. The development comparison used
`b3e296215d764d22e4c683ab32c9926072610db7`. This is a partial integration
boundary, **not production enablement or completion of #745**.

The available standard module is the finite, activation-local TCP subset
`lsf-node-net-tcp-v1`. There is no general Node stream implementation, public DNS
API or Node TLS port. No new signed Component Model execution was performed for
these diagnostic, Socket event and idle-timeout changes. Older signed receipts below remain evidence for their
own exact source and reference provider only.

## Dependency status

| Prerequisite | Reviewed status | What exists | What this does not authorize |
| --- | --- | --- | --- |
| [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737) | Closed for design | ADR-0061 accepted on 2026-10-16; review #1007 and acceptance record #1050. Finite TCP, separately selected host TLS, original authority/budgets and uncertainty/retirement rules are specified. | Production installation, a guest TLS port, public DNS calls, generic Node compatibility or changed resource limits. |
| [#738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738) | Open; implementation and qualification incomplete | `latent:network/streams@0.1.0`, V5 recognition, bounded provider, development-only logical-library reference, real provider/component controls. Merged #1894 fences abandoned writes and preserves known prefixes without replay. | Production kernel/native final-retirement qualification or qualified TLS. `ACCOUNTING_QUALIFIED` in `crates/latent-streams/src/tls.rs` is still false at the reviewed development source. |
| [#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739) | Open; operator qualification incomplete | Protected configuration, journal/currentness and recovery work. Merged #1825 retains pending operations across credential handoff; merged #1903 sends the exact journaled policy/binding bytes and retains uncertain mutations. | Qualified installed-provider lifecycle, live TLS/credential rotation or complete physical retirement. The #1903 loopback parser probe did not apply a policy to an authenticated node. |

The authoritative contract is [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md),
the [finite outbound profile](../runtime/outbound-stream-profile.md) and its
[owner acceptance](../runtime/outbound-stream-acceptance-2026-10-16.md). The design
chooses a qualified **guest** TLS port for ordinary-library TLS observables.
Replacing `node:tls` with provider `host-tls` would lose STARTTLS, verification
callbacks, pinning and client-identity semantics and is not an approved shortcut.

At the reviewed development source, `StreamProvider::install` still requires
`kernel::require_supported_profile` and the test/development feature gate.
`install_for_qualification` is explicitly a nonproduction logical-library
reference; descriptor/future destruction is not a kernel-final-free certificate.
The TLS accounting reference is test-only. Do not select those references as
production providers, make the qualification constant true, or treat an ABI
import as authority.

## API compatibility matrix

“Mapped” below means implemented source, not unrestricted Node compatibility.
“Historical signed” refers only to the retained finite TCP programme described
later, not to every operation or adversarial case in a row.

| API or behavior | Maintained mapping | Boundary and evidence |
| --- | --- | --- |
| `net` / `node:net`: `Socket`, `connect`, `createConnection` | `net_profile.py` selects the exact activation-import runtime and stream WIT shape; `net_builtin.mjs` supplies `node_net.mjs`; `node_net_bindings.mjs` supplies the private transport. | TCP outbound only. Exact endpoint/port/transport grant is independent. Historical signed direct client exists; no general socket or ambient OS API. |
| `connect({host, port})` and finite positional overloads | Broker `streams.connect` with transport `tcp`; bounded host/port validation. | Hostname resolution is internal to the authorized provider operation. No custom `lookup`, `family`, `localAddress`, descriptor adoption, address racing or implicit reconnect. |
| `write`, callback, return-value backpressure, `drain` | Bounded copied queue; partial `streams.write`; zero progress waits on `streams.ready` before another write. | Callback reports local transfer outcome, not peer commit. Known prefix and uncertain effects are retained; no hidden replay. Partial-write and callback behavior have host controls; signed TCP echo is narrower. |
| `data`, `pause`, `resume`, EOF/`end` | `streams.read`, owned chunk, `chunk-bytes`, original borrow acknowledgement, chunk disposal, copied Buffer. | EOF is an absent chunk, never an empty/failed transfer. Paused graceful end can probe real EOF but refuses actual unread data rather than discarding it. No `Readable` inheritance, `pipe`, async iteration or object mode. |
| Readiness | Internal writable wake hint through `streams.ready`; finite `connect`/`ready` Socket events. | The public `ready` event follows connect; it is not a reusable native poll handle. Readiness does not promise bytes, successful transfer or retirement. No libuv, OS descriptor or cross-activation polling API. |
| `end`, send half-close, `finish` | TCP send shutdown after queued writes. Accepted terminal intent can join actual peer EOF/borrow release/close before root completion. | End initiation is not consuming close. Receive-only shutdown, host-TLS send half-close, listeners and servers are not silently emulated. |
| `destroy`, errors, `close` | Cancel pending originals, join their acknowledgements and callback tails, consume connection close. | Logical `destroyed`/`closed` flags are not physical-retirement evidence. Failed close or acknowledgement cannot certify an empty registry. Open sockets without accepted terminal intent fail root completion. |
| `on`, `once`, `off`, `removeListener`, `removeAllListeners`, `emit` | Finite event facade; one-shot registrations are consumed by identity before invocation. | Duplicate functions remain distinct registrations. Nested emission cannot replay a consumed one-shot row; removals do not cancel an in-progress snapshot or erase a replacement registration. Current host controls compare the ordinary Node Socket facade; not full `EventEmitter` or signed execution qualification. |
| `setTimeout` / `timeout` | Application idle notification before/during connect and on a connected socket, using the selected activation timer runtime. Zero disables the timer and removes only the supplied matching callback. | A stale/replaced timer cannot notify or clear the current timer. Notification does not itself destroy the socket, extend an original provider/activation deadline, or refund an owner. Finite integer milliseconds only; actual native clock and signed deadline-race qualification remain separate. |
| `dns`, `node:dns`, `dns/promises`, `node:dns/promises` | Explicit compiler refusal. | WIT has no public lookup/resolve/reverse/resolver operation or standalone DNS authority. A dummy connect must not be used to implement DNS. |
| `tls` / `node:tls`, `TLSSocket`, `tls.connect`, STARTTLS | Explicit compiler refusal. | No qualified TypeScript guest TLS/crypto/entropy/trust/credential lifecycle mapping. The `tls-failed` WIT error tag is not a TLS implementation. |
| `stream` / `node:stream`, `/promises`, `/web`, `/consumers`, legacy `_stream_*` builtins | Explicit compiler refusal. | No complete Node stream classes, pipeline/finished, Web Streams adapters, generalized queue ownership or their lifecycle qualification. A finite Socket API is not a general stream API. |
| `createServer`, listening, Unix/OS handles, arbitrary socket options | Outside the finite runtime declaration; runtime methods that exist for refusal throw. Other missing named exports fail the normal compiler. | No successful no-op, ambient Node fallback or automatic gateway. Full POSIX/Node emulation is not the approved goal. |

The selected profile remains two socket states, three pending operations per
socket, 64 KiB/16 queued write records and 16 KiB transfer windows. These are
model limits, not proof that engine, captured objects, TLS/native or kernel bytes
are fully bounded. This change modifies no native admission policy, limit, provider,
AbortSignal implementation, cleanup owner or capability declaration. The idle
clock is now admitted before a connect reserves its socket, rather than being
silently deferred until connection success.

### Error translation is deliberately coarse

The source maps provider `connect-failed` to `ERR_LSF_CONNECT_FAILED`,
`dns-failed` to `ERR_LSF_DNS_FAILED`, `tls-failed` to `ERR_LSF_TLS_FAILED`,
`timeout` to `ETIMEDOUT`, `cancelled` to `ABORT_ERR`, denied/revoked to `EACCES`,
and exhaustion to `ERR_LSF_RESOURCE_EXHAUSTED`. The original cause and provider
code survive. The WIT does not distinguish every OS error: do not fabricate
`ECONNREFUSED`, `ENOTFOUND`, a certificate error or remote rollback from a coarse
tag. Libraries depending on those exact distinctions require qualification or
an explicitly reviewed contract extension, not optimistic aliases.

## Selection, source binding and diagnostics

The normal compiler selects the module from the runtime profile and the exact
`latent:network/streams@0.1.0` graph, never from an npm package name. Both bare
`net` and `node:net` resolve to the same compiler-owned module. The rule applies
inside captured direct and transitive ESM/CommonJS dependencies. An application
cannot choose `standardNet*` fields or import
`lsf:typescript-node-net-transport`; only the maintained module identity can
reach that private binding.

`net_profile.identities` binds the backend, transport, bindings, resolver,
declaration and WIT bytes. The selected-module receipt carries those identities;
a changed resolver cannot reuse an earlier receipt. A tree-shaken unused module
does not produce a selected-network receipt. Merely parsing a declaration or
installing a library adds no grant and does not make an unavailable provider
available.

The diagnostic boundary is a closed list of **standard module specifiers**, not
an allow/deny list of package identities. The resolver refuses the DNS, TLS and
stream families before captured npm or browser-shim resolution, independently
of the build host's Node builtin inventory. Bare and `node:` aliases emit the
same canonical diagnostic, for example:

```text
standard-node-network-module-unavailable:node:dns/promises
standard-node-network-module-unavailable:node:tls
standard-node-network-module-unavailable:node:stream/web
```

Each diagnostic includes the missing semantic boundary and points here. Type
checking can reject a missing declaration earlier; these resolver diagnostics
also cover reachable imports inside captured JavaScript dependencies. Type-only
or erased unused imports are not evidence of installed runtime support.

`standard-node-net-requires-exact-stream-runtime-and-declaration` is preserved
for an unselected TCP profile, now with guidance to use the maintained runtime
and exact WIT through the normal compiler. That guidance is not a grant or a
recommendation to enable an unqualified provider. A distinct package such as
`dns-packet` or `readable-stream`, and a relative `./dns` import, is left to the
normal captured-module rules; its name does not select or authorize networking.

An application that requires an unavailable API must use a genuinely supported
library/profile or wait for the owning implementation and qualification. Do not
replace TLS with cleartext, disable verification, supply a fake DNS response,
return successful empty streams, add a browser/Node fallback, or require a
hand-written LSF transport as a substitute for the standard-module work.

## Execution evidence and required remaining cases

The retained [ordinary TCP guide](typescript-node-net.md) and
[published-client receipt](../testing/typescript-node-net-client-evidence.json)
record run `40157957656` at source
`d94290f662172df734029874d0c1d8188f56b7d7`: one normal signed Component Model
build and eight actual cases using the approved nonproduction reference
provider. Six finite socket cases were followed by granted/denied executions of
unchanged published `is-port-reachable@4.0.0`, with the normal `net` import, all
five published files and the original npm archive retained. The granted case
contacted its peer once; denied contact was zero. A later same-backend activation
is part of the finite programme. These are not Nodemailer, TLS, full DNS, general
stream or published-transitive-library qualification.

The historical reference used its already approved Task32/Queued32/Native128
profile. It is neither a new budget request nor evidence that lower budgets or
all physical costs are sufficient. Zero post-root logical counters do not prove
kernel final-free. Those original receipts and failures remain unchanged.

| Required case | Available evidence / gap |
| --- | --- |
| Denied endpoint, ordinary connect, EOF, close, fresh activation | Historical signed finite TCP cases; current source needs fresh signed execution. |
| Real connection refusal and DNS failure | New host controls inject the corresponding closed WIT tags and verify one attempt, original cause, error-before-close and no retry. Actual signed provider/DNS failures remain pending; a denied endpoint is not connection refusal. |
| TLS verification/handshake failure and successful TLS | Translation of an injected `tls-failed` tag is covered. No TLS port, handshake or signed TLS result is claimed; prerequisite remains blocked. |
| Partial read/write, no-progress readiness, backpressure | Existing source/transport controls pass. Historical signed echo/held-read evidence does not cover every adversarial short-transfer schedule. |
| Cancellation, callback exceptions, distinct cancel/borrow acknowledgements | Existing captured-initializer/host controls and narrower historical signed destroy case. They do not certify final native/kernel retirement. |
| Idle timeout, late callback and repeated activations | Controls cover pre-connect/pending-connect notification, identity-fenced replacement, zero-disable/callback removal, snapshot refusal, timer-admission refusal before socket reservation, reentrant rearm and callback faults. A pending-connect model retains distinct cancel/result/borrow acknowledgements across two fresh instances. Actual signed timeout/deadline races remain pending. |
| Direct/transitive selection and fallback refusal | Resolver/source-binding controls pass; a separate actual pinned-bundler control exercises transitive CommonJS through ESM and fake npm/browser fallbacks. The compiler gate now also checks caught CommonJS imports, side-effect imports, transitive profile disablement and relative filename lookalikes. It is selected by a separate compiler-only workflow; its new hosted result remains pending; local supplementary discovery still skips the two pre-existing frontend cases. |
| Unchanged published library | The historical direct `is-port-reachable` programme is real. No new published-library or signed transitive execution was performed in this change. |

The initial diagnostic slice used Node 22.16.0 for host-only controls, not the
pinned 24.19.0 qualification toolchain: five boundary cases plus the unchanged
30-case socket suite ran with 33 passes and two existing frontend skips. The
2026-11-10 continuation adds two preflight/result-gate controls: 37 tests ran
with 35 passes and those same two skips. No compiler or signed pass is inferred.
Those first two compiler-only slices left supported `node:net` emission
unchanged. The subsequent Socket event repair below changes the emitted backend;
both backend and resolver identities now require a fresh normal receipt.

### Socket one-shot event repair (2026-11-10)

The parent `99d122fbce0b2dc55519686923558f54c9db7247` consumed a one-shot
listener through public `removeListener(name, function)`. That operation removes
the **last** matching registration, so it could erase a persistent duplicate and
leave the one-shot registration live. Its emission snapshot could also invoke a
one-shot row already consumed by a nested emission. Removing all listeners and
re-registering the same function during emission exposed a third manifestation:
the old snapshot removed the replacement. Callback exceptions did not repair the
incorrect registry state.

The repair consumes the exact original registration before invoking its callback
and skips a row already consumed by nested emission. It reuses the existing
`once` field (persistent/pending/consumed); it adds no listener field, queue,
transport owner or limit. Public `removeListener`/`off` still removes the last
matching registration. Existing in-flight snapshots, callback receiver and
arguments, original thrown values and the transport tail `finally` are preserved.
This follows the [Node event contract](https://nodejs.org/api/events.html#emitteronceeventname-listener),
not a broader claim of `EventEmitter` support.

All four new regression tests failed with the exact original backend and passed
with the repair. The direct comparisons use real Node 22.16.0 `Socket` objects
without connecting them: duplicate registration orders, nested emissions,
removal/replacement during a snapshot, public removal order, and original thrown
values including `undefined`, `null`, false and zero. A separate control uses the
actual LSF facade and transport with the existing provider/ACK doubles: a caught
synchronous callback fault leaves the connected model usable and its existing
close path completes in two fresh instances. That control is not a native socket,
physical-retirement or cross-tenant signed observation.

The combined boundary and unchanged socket suites ran 41 tests: 39 passed and the
two existing pinned-frontend controls skipped. The four new controls are selected
automatically by the existing no-skip compiler gate; no workflow, fixture
inventory or exact test-count assertion changed. The pinned Node 24.19.0 gate
and fresh signed TCP execution remain pending. Historical signed receipts do not
qualify the changed backend.

### Socket idle-timeout repair (2026-11-10)

Parent `7e3817f69610b670e7228138b16cc890aaeaf6ad` only armed an idle timer
on a connected socket. A library setting its ordinary timeout before a connect
could therefore wait indefinitely for the connection from the facade's point of
view (the independent provider/root deadline still applied). Disabling a timer
with `setTimeout(0, callback)` added that callback instead of removing its newest
matching registration. A callback already selected from a replaced timer could
also notify and clear the slot holding a newer timer, preventing later cleanup
from clearing the actual current timer. Calls on destroyed sockets retained new
callback state.

The facade now arms the existing bounded timer before/during connect as well as
after it. Connect refreshes the timer before publishing its supplied listener or
reserving a socket; a refused refresh therefore cannot dispatch a connection or
strand a reserved socket without a connect result. A failed timer admission
publishes no supplied timeout callback. The configured interval remains a
configuration value, not proof that admission succeeded; retrying is explicit.
Zero disables the timer and removes only the supplied matching callback. A call
on a destroyed socket changes neither timer nor listeners. Nonzero snapshot-time
arming is explicitly refused, including before any connection is attempted.
The supported argument subset remains integer milliseconds from zero through
`2147483647`; this is not all Node timer coercion behavior.

Each callback captures its actual returned timer identifier and runs only while
that identifier is still current. The selected native activation timer owner
uses monotonically increasing, non-reused IDs and fails on ID exhaustion;
`native_timers.h` and its policy are unchanged. Clear/replacement invalidates the
facade slot before calling the original clear operation. A stale callback cannot
steal a replacement, and a callback may install a new timer without the old
callback subsequently erasing it. No timer owner, budget, clock, cancellation
acknowledgement or physical-retirement rule is replaced by this identity check.

Timeout remains a **notification**, not implicit destroy, reconnect, operation
rollback, success, deadline extension or retirement. The existing transport
owns callback tails: an escaping callback fault, including a falsey value,
poisons that original socket rather than certifying a clean root return. The
pending-connect control observes timeout without cancellation, then explicitly
destroys and requires distinct cancel, logical-result and borrow acknowledgements
before consuming close. Two fresh modeled instances execute that sequence.

Eight focused controls pass on the repair. Against the exact published parent
backend (Git blob `98080307950dd5cd0c9c298f4b319bba86dccd87`), seven fail and the
original callback-fault custody control passes. All earlier event controls and
the unchanged socket suite remain selected: **49 tests ran, 47 passed and the two
existing pinned-frontend tests skipped**. No exact-count gate was changed.
Node 22.16.0 supplies a real unconnected-Socket timer and callback-removal
reference; the selected Node 24.19.0
[`setStreamTimeout` source](https://github.com/nodejs/node/blob/v24.19.0/lib/internal/stream_base_commons.js)
was also reviewed. That source comparison is not execution of Node 24.19.0.
The LSF facade/transport execute unchanged provider/ACK and deterministic-clock
doubles; they are not signed execution, actual LSF native clock, DNS/contact,
root-deadline or physical-retirement evidence. Fresh pinned compiler and signed
TCP results are still required for this changed backend.

### Fail-closed compiler gate

Run the gate with the normal installed pinned frontend:

```sh
python3 -B -m tools.tests.test_typescript_network_boundary \
  --frontend /absolute/path/to/normal-installed-tools
```

This checks the pinned Node version, unchanged tool manifest/lock and installed
esbuild/Acorn/TypeScript versions before running the actual bundler controls.
It then runs every current boundary and original socket test with the selected
frontend and Acorn. Missing tools, zero tests, skips, expected failures and
ordinary failures all refuse. There is no exact-test-count inventory to update
when a test is added. Ordinary unittest discovery remains supplementary:

```sh
python3 -B -m unittest -v tools.tests.test_typescript_network_boundary \
  tools.tests.test_typescript_node_net
```

The `TypeScript networking compiler boundary` workflow invokes the gate with
the normal pinned tools and Python requirements. It is independent of the native
engine/Fetch jobs, so their failures cannot skip these compiler controls. The
new compiler-only job has a 15-minute limit and a five-minute gate limit; it
installs the normal frontend but builds no engine or native provider. Existing
TypeScript workflows and their source/provider/origin gates are unchanged.
Separate `typescript-network-boundary-<source>` artifacts retain `controls.log`
and `result.json` even if a later job fails. A failed gate can leave an empty
result file: artifact presence alone is never a pass. Only a successful step
and a complete `latent.typescript.network-boundary.v1` result establish this
compiler/model observation. The result records unchanged before/after source
hashes, observed compiler cases and actual test totals; `signedExecution` and
`providerQualification` are explicitly false. It is not a signing attestation,
physical-retirement receipt or qualified provider installation.

The first hosted integration at `a11228373ecd403e30f71ac1a1cb9ede2e2bc57e`
executed synthetic merge `1df7c56c2500f30a3c75f1ba7f4dff388e3dec6c` in
[CI run 42699479553](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42699479553).
Retained artifact `13724619433` (ZIP SHA-256
`154773c1189ece9b0f4144749437a864b8985d1d2d401678db13802a95294c29`)
records the five initial boundary cases without failure; it did not invoke the
explicit compiler control. Its four failures are in AOT input agreement,
composition source binding and embedded/Java shared-runner preservation tests.
The Rust lane and the separate signed Fetch lane also failed; those results
are not green CI and do not supply signed TCP evidence. This continuation does
not modify their runtime, budget or AbortSignal owners.

The existing signed owner is `tools/qualify_typescript_borrow_signed.py
--programme node-net`. Its authenticated source, provider and native-product
prerequisites and fixed workflow-origin checks must be satisfied; running an old
binary or relabelling an old receipt is not a new result. A generic successful
Fetch run also does not qualify the socket or TLS mapping.

On 2026-11-10 the signed owner's required producer run `40077087832` listed
zero artifacts. `borrow_signed_inputs.py` still authenticates producer artifact
`12553639081`, source `6d834e502beea33fbae9347fbaf23ff8c37223b3` and its exact
size/digest. A fresh signed TCP run therefore requires a retained matching
producer or a separately reviewed source-authenticated replacement chain, plus
the owner workflow's origin and native/provider inputs. Substituting the recent
Fetch engine, widening the allowed workflow origins or attributing the old
client receipt to this branch would not satisfy that gate. Those checks are
unchanged here; no fresh signed TCP execution is claimed.

The complete acquisition chain was traced on 2026-11-10; restoring just the
engine ZIP would not unblock execution:

| Required input / origin | Existing binding | Observed blocker |
| --- | --- | --- |
| OWN compiler/engine prerequisites | `borrow_signed_inputs.py`: run `40077087832`, artifact `12553639081`, source `6d834e502beea33fbae9347fbaf23ff8c37223b3` | Producer lists zero artifacts. Exact executed native/source controls and receipt are required; a successful Fetch build is not equivalent. |
| Native CLI/tool products | `java_phase_native_products.py`: run `39420914927`, artifact `12265176239`, source `77bf0e3f3b68e17342b6146abd6f2de34a3efa00` | This producer also lists zero artifacts. Its authenticated five products are mandatory to build/admit the ordinary client. |
| Retained library used to rebuild OWN prerequisites | `owned_result_library.py` consumes `typescript_borrow_retry_inputs.py`: run `40042939576`, artifact `12541695434`, source `e2dfcf6d1b48b650fee585e83cd15720bf7f745c` | This producer lists zero artifacts as well. Re-running the old OWN job alone cannot restore its missing library input. The old failed producer's successful library products were never a full qualification pass. |
| Signed TCP workflow origin | `borrow_signed_controls.py` requires push/attempt 1 on `feat/typescript-accepted-close-20261025` through `typescript-borrow-signed.yml` | The Agent 4 integration branch is not an accepted origin. This fixed gate is unchanged; no environment spoofing or broadened allow-list is used. |

These immutable checks cannot be satisfied by editing an artifact identifier,
copying recent Fetch products, or marking an unavailable job as passed. A
replacement needs a reviewed current-source producer chain, normal compiler and
engine validation, actual prerequisite controls, authenticated native products,
and a narrowly owned signed-run origin. It must retain the original provider,
authority and resource gates and record new identities rather than rewriting the
historical receipts. No replacement producer or new signed run is claimed here.

## What still prevents #745 from closing

The finite standard-library networking workload still needs qualified provider
and operator lifecycles under #738/#739, required conformance under #740, an
implemented guest TLS/stream surface where the selected unchanged library
requires it, and fresh signed execution with original authority, deadlines and
physical owner accounting. Public DNS methods need a defined authorized API
before they can be mapped; the approved internal connect resolver is not one.
The accepted matrix's unchanged Nodemailer workload remains unqualified.

The aggregate activation/engine accounting and AbortSignal work owned by the
other #745 agents remains independent. No claim here closes those requirements.
This boundary must stay fail-closed until the missing implementations and their
exact-source evidence exist.
