# Source-owned TypeScript import runtime candidate

`spidermonkey-activation-promises-clocks-imports-v1` is an explicit compiler
candidate. Its project, captured npm selection, exact engine input and exact
source-built compiler splicer must agree. The ordinary synchronous selection
remains the default.

The candidate links SDK-owned Promise jobs, timer globals, Abort/Event
ownership and separately scoped clock globals before application modules.
Its compiler retains actual asynchronous WIT imports, returns real native
Promises and drives timer/import readiness through one activation-local set.
Typed result lifting finishes before canonical subtask drop and physical
result/capture retirement. Asynchronous cancellation retains the original
handle, stable buffers and owners while the host reports `BLOCKED`.

The engine requests the existing activation interface and both clock
interfaces. Recognition, compiler selection and reading a clock grant no
authority: each interface still needs ordinary installation, policy and grants.
Unsupported runtime modules, addons, process APIs and dynamic loading retain
concrete diagnostics.

Build observations bind the exact native SDK source, original upstream pins,
source derivations, compiler-tool bytes and build/transpile receipts. Their
qualification remains `unknown` and API support remains `not-evaluated`.
An operator-provided compiler input cannot certify runtime support.

The maintained `tools/build_typescript_source_splicer.py` builder captures the
original ComponentizeJS archive, verifies the selected derivation preimages,
and uses its original locked Cargo workspace and upstream JCO componentization
and transpilation commands. Supply the unchanged compiler namespace produced
by `typescript_capsule.py install-tools` with `--tools`, and a fresh independent
directory with `--output`. It rechecks the original public WIT, Cargo lock,
derived sources and every captured compiler file after the build. The resulting
`splicer-input.json` binds the generated JS/Wasm bytes and successful command
receipts. The independent 20-minute source-splicer CI job executes this build;
its products remain compiler inputs until the signed runtime matrix passes.
The native engine builder accepts this completed build explicitly through
`--source-splicer-build`. It verifies the input and source/build/transpilation
receipts before and after compilation and binds `compilerSplicerInputDigest` in
the import engine envelope. This selection adds only the two internal import
bridge sources. The original native TextCodec definitions remain selected by
upstream CMake, with their source preimages and generated installation order
checked. The existing clock-engine build still runs before this additional
import-engine build; source compiler completion is a strict prerequisite.

The pinned SpiderMonkey derivation exports `ActivationPromiseHooks.h` through
its normal `js/src/moz.build` header list. The exact upstream build descriptor
is authenticated alongside the Promise implementation and object declaration;
an unreviewed descriptor fails before patching. A source rebuild needs this
export so the generated public include tree contains the native hook ABI.
Regenerate source-bound engine inputs after changing the derivation. The
[header export control](../testing/evidence/typescript-promise-header-export-2026-10-16.json)
confirms normal header generation and the changed-source rejection; it does
not establish a complete engine build or runtime qualification.

Contributor toolkit assembly can explicitly capture a `runtime-bundle.json`
with the named profile, exact engine and source-built splicer inputs, and
original notices. `build_dev_guest_tools.py --typescript-runtime-inputs`
includes these bytes in the existing authenticated managed-tool inventory.
The maintained recipe selects that bundle automatically for a project with
the same explicit profile. Missing inputs, profile disagreement and changed
bytes fail before application compilation. The bundle continues to record
unknown qualification and does not advertise a supported release.

The [source-bound production qualification record](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/typescript-runtime-reconciliation.md)
records source-built engine/splicer inputs and the original 26 signed controls:
15 ordinary cases, four clock cases, two service cases and five unchanged npm
cases, plus a fresh-after-failure control. These actual LSF runs are separate
from the earlier simulated-broker/Wizer compiler proofs. The four expected
ordinary failure cases remain guest traps, and both service cases execute a real
child. The input classification remains unknown/not-evaluated; the finite matrix
does not upgrade it to a supported distribution.

The [compiler-owned buffered fetch candidate](typescript-fetch-candidate.md)
adds automatic global HTTP APIs when this runtime and the exact streaming HTTP
import are selected. Its native semantic controls are separate from the signed
matrix above; actual fetch/library/provider qualification remains pending.

Broader exhaustion/cancellation/late-wake behavior, complete default fetch/body ownership,
complete private/update/watch workflows, automatic runtime selection and clean
installed distributions remain separate ticket requirements. This page does
not advertise a supported release or full Node environment.
