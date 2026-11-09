# TypeScript networking compatibility and prerequisite boundary

Status reviewed on 2026-11-09 for issue #745 and integration into
`feat/typescript-runtime-745`, starting at
`83c339673b87afabfa06f3a8e818324f46c1ae6f`. The development comparison used
`b3e296215d764d22e4c683ab32c9926072610db7`. This is a partial integration
boundary, **not production enablement or completion of #745**.

The available standard module is the finite, activation-local TCP subset
`lsf-node-net-tcp-v1`. There is no general Node stream implementation, public DNS
API or Node TLS port. No new signed Component Model execution was performed for
this diagnostic change. Older signed receipts below remain evidence for their
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
| `setTimeout` / `timeout` | Application idle notification on the selected standard activation timer runtime. | Does not itself destroy the socket, extend an original provider/activation deadline, or refund a timer owner. Timeout callback races have model controls here; actual native clock ownership is a separate gate. |
| `dns`, `node:dns`, `dns/promises`, `node:dns/promises` | Explicit compiler refusal. | WIT has no public lookup/resolve/reverse/resolver operation or standalone DNS authority. A dummy connect must not be used to implement DNS. |
| `tls` / `node:tls`, `TLSSocket`, `tls.connect`, STARTTLS | Explicit compiler refusal. | No qualified TypeScript guest TLS/crypto/entropy/trust/credential lifecycle mapping. The `tls-failed` WIT error tag is not a TLS implementation. |
| `stream` / `node:stream`, `/promises`, `/web`, `/consumers`, legacy `_stream_*` builtins | Explicit compiler refusal. | No complete Node stream classes, pipeline/finished, Web Streams adapters, generalized queue ownership or their lifecycle qualification. A finite Socket API is not a general stream API. |
| `createServer`, listening, Unix/OS handles, arbitrary socket options | Outside the finite runtime declaration; runtime methods that exist for refusal throw. Other missing named exports fail the normal compiler. | No successful no-op, ambient Node fallback or automatic gateway. Full POSIX/Node emulation is not the approved goal. |

The selected profile remains two socket states, three pending operations per
socket, 64 KiB/16 queued write records and 16 KiB transfer windows. These are
model limits, not proof that engine, captured objects, TLS/native or kernel bytes
are fully bounded. This change modifies no runtime admission, limit, provider,
AbortSignal implementation, cleanup owner or capability declaration.

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
| Idle timeout, late callback and repeated activations | Deterministic application timer model checks notification without implicit close, reset on progress, cleared timer and inert late callback across fresh model instances. Actual signed timeout/deadline races remain pending. |
| Direct/transitive selection and fallback refusal | Resolver/source-binding controls pass; a separate actual pinned-bundler control exercises transitive CommonJS through ESM and fake npm/browser fallbacks. That new compiler control was not run because the pinned frontend was unavailable. The existing suite also skipped its two pinned frontend controls, not passed them. |
| Unchanged published library | The historical direct `is-port-reachable` programme is real. No new published-library or signed transitive execution was performed in this change. |

Local validation used Node 22.16.0 for host-only controls, not the pinned
24.19.0 qualification toolchain. The new five-test boundary module passed;
together with the unchanged 30-test socket owner, 35 tests completed with
33 passes and two pre-existing pinned-frontend skips. The supported
`node:net` module emitted by the resolver was compared byte-for-byte with the
starting resolver and is unchanged. The resolver source identity nevertheless
changes and requires a fresh normal receipt. Host model success and emission
equality are not a substitute for a source-matched signed run.

To execute the compiler controls with the normal installed pinned frontend:

```sh
LSF_TYPESCRIPT_FRONTEND=/absolute/path/to/normal-installed-tools \
  python3 -B -m unittest -v tools.tests.test_typescript_node_net tools.tests.test_typescript_network_boundary
python3 -B -m tools.tests.test_typescript_network_boundary \
  --frontend /absolute/path/to/normal-installed-tools
```

The second command requires the pinned Node/esbuild/Acorn versions and fails
when its tools are missing; it is a compiler control, not signed qualification.
It is not implicitly included in the host unittest pass count.

The existing signed owner is `tools/qualify_typescript_borrow_signed.py
--programme node-net`. Its authenticated source, provider and native-product
prerequisites and fixed workflow-origin checks must be satisfied; running an old
binary or relabelling an old receipt is not a new result. A generic successful
Fetch run also does not qualify the socket or TLS mapping.

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
