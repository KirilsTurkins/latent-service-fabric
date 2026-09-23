# Windows developer controller implementation

This work implements the Windows portion of [epic #559](https://github.com/KirilsTurkins/latent-service-fabric/issues/559).
The maintainer deferred the Mac requirements on September 23, 2026. The epic and
its children remain open until their actual acceptance evidence exists.

`latent-dev` is a separate executable. It does not replace `latent`, change the
operator CLI's single-operation behavior, or enable a production Windows node.
The Windows executable includes its Python interpreter; application developers
do not need Python, Rust, or an LSF checkout to run that executable. Guest
compilers remain separate, explicitly selected build inputs.

## Implemented controller contracts

- `dev doctor` reads Windows/WSL prerequisites without opening a project or
  executing recipes. Its result explicitly distinguishes host observation from
  authenticated node readiness. `--workspace NAME` runs the existing Linux
  filesystem/profile checks under the selected node identity.
- `dev acquire` authenticates provisioned offline developer inputs using the
  existing runtime publisher-policy format and GitHub attestation verification
  command. The separately provisioned policy selects an exact source revision.
  An arbitrary successful build does not approve a publisher identity.
- `dev provision` imports a distinctly named, verified WSL2 image only with
  `--consent-provision`. It records intent before import, checks the actual WSL
  registration and Linux version, and changes neither the default distro nor
  the global kernel configuration. Interrupted import is uncertain, never an
  excuse to unregister an unrelated distro.
- `dev wsl-workspace` creates a distinct unprivileged Linux user per workspace
  within the owned distro. Node configuration, tokens, catalogs and build outputs
  stay in private Linux storage; source synchronization contains none of these.
  `wsl-status` observes the actual recorded registration. `wsl-recover` reconciles
  the original registration and Linux user nonce; it never repeats an import.
  Both recovery and `wsl-purge` require `--confirm-distribution LSF-Dev-...`.
  Distro purge refuses to run until every owned workspace user has been removed.
- `dev connect` selects a preprovisioned direct Linux or explicit SSH backend.
  SSH requires a selected identity file and known-hosts file, strict host-key
  checking and no agent forwarding, proxy command or connection multiplexing.
- `dev trust` records the exact project recipe/tool/ABI selection outside the
  repository. Recipe changes invalidate trust. `dev init` only materializes
  authenticated language-owned templates into a new destination.
- `dev install` delegates to the maintained [native installer](../../packaging/linux/INSTALL.md).
  `up` runs its real configuration and authenticated readiness checks. Profile
  changes and runtime upgrades are never automatic.
  Versioned offline input documents transfer only the named release files,
  independent publisher policy, trusted roots and independently pinned Linux
  verifier. Transfers use 1 MiB chunks, at most 16 files/768 MiB per selection,
  and at most three selections per workspace. Each transfer has a 900-second
  deadline. Identical byte retransmission is
  allowed; changed bytes and gaps fail. Installer execution follows final hashes
  and its existing publisher verification. Set `resume: true` explicitly to use
  the existing installer's interrupted-install recovery.
- `dev install-tools --workspace NAME --tool-inputs PATH` transfers a selected
  compiler bundle and authenticates it inside the workspace before extraction.
  The JSON input has `schemaVersion: "latent.dev.tool-inputs.v1"`, the explicit
  `bundleDirectory`, `version`, `language`, `publisherPolicy`, `trustedRoot`,
  Linux `verifier` and its `verifierSha256`, plus `allowCandidate: true` and
  `consent: true`. Paths name separately provisioned host files. The policy must
  independently approve the exact candidate commit; the installer does not
  manufacture that approval. At most two compiler selections remain in private
  workspace storage, each within the existing bundle limits. Installation has
  a 600-second deadline. Interrupted extraction requires `resume: true`, checks
  the original ownership record and authenticates the same inputs again.
  A completed but changed cache fails without repair. The returned tool
  selection records its bundle, source, language, ABI and inventory digest.
  `build` and `up --watch` use that selection when `--tool-root` is omitted and
  reject a project whose template or compiler pins differ. Explicit tool roots
  remain available for reviewed custom/source development recipes. Purge removes
  the owned compiler cache along with the workspace's other generated data.
- Build, immutable source transfer, deployment and watch use bounded resources.
  A persisted mutation intent contains the original operation identity and
  observed preconditions. Recovery looks up that identity and does not replay
  an Invoke, publication or deployment. Unknown/expired receipts remain unknown.
  Confirmed publication/deployment metadata is persisted before clearing the
  intent; interruption between those writes repeats only local settlement.
  Invocation history retains result digests rather than unbounded payloads.
- Each build uses a fresh private attempt directory. Cache keys include source,
  trusted recipe, template, tools, host, ABI, target and installed packager bytes.
  A hit rechecks the tools, source, artifacts and actual package inspection.
  The compiler emits package inputs; the existing operator assembles the package
  afterward. Recipes cannot silently supply an already assembled package.
  Failed builds preserve the accepted build and deployment. Recovery retains the
  exact attempt alongside the original publication/deployment operation identity.
- Watch checks source and recipe changes during compilation and sends cancellation
  for that exact build identity. The Linux owner confirms child reaping before
  releasing the attempt. A final source check precedes deployment. `down`,
  `status`, `logs` and `build-status` remain available while a build holds the
  command lock. Interrupted transport requires an explicit cleanup observation;
  controller restart never adopts or signals an old numeric PID.
  Use `up --watch --test-select CASE` in a `test-` workspace for focused node
  scenarios after each confirmed deployment. Test failure is a separate event;
  it leaves that deployment selected and does not trigger rollback. Without a
  selection, watch reports that no post-deploy tests were selected.
- `down` addresses the workspace supervisor and retains data. `purge` requires
  the exact workspace name and delegates runtime removal to the existing
  installation owner before removing owned snapshots.
  A reaped node is reported separately from a clean shutdown: the latter requires
  a zero exit and the node's complete `stopped` record. A bounded reader drains
  diagnostics during readiness/shutdown and redacts credentials before retention.
  A changed guest boot/PID namespace proves old processes were reaped, while
  reporting that their shutdown was interrupted. A lost connection in the same
  guest instance remains uncertain.

These implementations still need the packaged integration runs below. An
adapter unit test is not a WSL provisioning receipt.

## Project, transfer and test boundaries

`latent.dev.project.v1` is closed and versioned. It identifies the language
owner (#544–#549), immutable template revision, ABI, build host, pinned tools,
explicit input roots, exclusions, output paths and application scenarios.
It integrates supplied language artifacts; it does not ship parallel SDKs or
claim the pending language-owner PRs are delivered.

The Linux helper uses pinned Python 3.13.5, negotiated before any operation.
The managed guest provides it at `/usr/local/bin/python3.13`; the distro's own
system Python is separate. A preprovisioned SSH host needs that same reviewed
helper/interpreter layout. Direct Linux connections explicitly select both paths.
Each RPC authenticates the helper before loading it and uses that same opened
file for imports. No shell program or project recipe is supplied by RPC data.

Source snapshots retain exact bytes, including CRLF. A second observation checks
the full selected tree before accepting a coherent snapshot. Absolute paths,
traversal, reparse points, symlinks, hardlinks, Windows device names, case and
Unicode aliases are rejected. `.git`, `.env`, `.ssh`, `.aws`, `.azure`, generated
output and dependency trees are excluded. Declared inputs are not a secret
scanner: authors must deliberately exclude any additional confidential files.

Initial bounds are eight workspaces, one active command/build per workspace,
2,048 source files, 16 MiB per source file, 64 MiB per source snapshot, four
retained snapshots, 256 KiB of supervisor logs, 32 retained operation receipts,
900 seconds per build and bounded command cleanup. Cancellation gives a Linux
language recipe six seconds to reap its nested process groups, then allows five
seconds for the outer group sweep. The transport allows twelve seconds for the
helper to finish that cleanup. Exceeding the grace period remains uncertain.
Four build attempts are retained, each monitored every 500 ms for a 32,768-entry,
2 GiB ceiling. This is an observed limit, not a filesystem quota: temporary
overshoot can occur before cancellation. Known failed or superseded attempts can
be removed; accepted, deployed and uncertain attempts stay protected. A full
cache of protected attempts rejects a new build. Package assembly shares the
original build deadline. Compiler timeout/output overflow is distinguished from
unconfirmed child cleanup, which requires inspection before purge.
Eight verified bundle directories bound the host cache, covering the Windows
frontend, WSL image and six language tool sets. Developer inventory documents
have a separate 2 MiB bound; ordinary protocol documents remain at 256 KiB. These are controller
limits, not a claim of hostile compiler or whole-process memory containment.

`latent.dev.scenarios.v1` keeps application inputs and results as exact bytes
and supports focused selections plus JUnit rendering. Tests must explicitly
choose `node` or `portable`; unsupported required checks fail coverage.
The current node runner requires an explicitly selected `test-` workspace.
The native portable host reuses the production component engine, WIT surface,
canonical value codec, fresh-store ownership and capability policy broker.
It executes prebuilt controlled development components without Linux. Its
initial exercised Windows subset is Rust typed success/declared error,
missing-import denial, cancellation, traps, fuel/memory/deadline interruption,
and subsequent fresh-state success. Additional actual Rust SDK capsules cover
random bytes and unsigned values, all four custom metric kinds, explicit policy
denials, and buffered HTTP through the production provider and an owned loopback
peer. C guests and real-node differential qualification remain required work.

The selected verified Windows bundle must contain the portable executable.
Use `dev test --environment portable --controlled-development --workspace NAME
--portable-bundle DIGEST --project PATH --artifacts PATH`. Artifact paths are the
descriptor's relative output paths beneath `--artifacts`. Execution uses exact
component/manifest/contract bytes, does not invoke a guest compiler, and never
falls back to Linux. Scenario `execution.grants` explicitly names the supported
imports; absent bindings fail before execution. `execution.deniedCapabilities`
selects explicit deny policies for otherwise bound imports, using the same
policy evaluator as the node. Optional decimal-string `fuel`
and `memoryBytes`, Boolean `cancelBeforeStart`, and `timeoutMillis` narrow the
selected component's limits. Required Linux-only checks remain failures.
The report states actual OS, architecture, Wasmtime version, component digest,
cleanup, system-clock nondeterminism and omitted node/security behavior.

The closed `latent.dev.portable-request.v1` import profile is:

| Import | Implementation and fixture boundary |
| --- | --- |
| `latent:context/context@0.1.0` | Production activation context, explicit per-call grant |
| `latent:log/log@0.1.0` | Production bounded activation log sink |
| `latent:clock/monotonic@0.1.0`, `latent:clock/wall@0.1.0` | Production system clocks; reported as nondeterministic |
| `latent:random/random@0.1.0` | Production provider; system entropy or an explicitly selected repeatable byte fixture |
| `latent:telemetry/custom@0.1.0` | Production metric provider, bounded declared metric/label sets and joined exporter |
| `latent:http/client@0.2.0` | Production HTTP provider, one owned IPv4 loopback peer, exact approved methods/paths and reply bytes |

No implicit WASI, filesystem, environment, other socket, secret or cloud import is
installed. Imported streaming/resource interfaces outside this table are rejected
before guest execution. Canonical arguments and results use the production value
codec, including decimal-string unsigned 64-bit values and explicit absent values.
One request runs at most 128 calls sequentially with fresh Stores, 16 MiB component
bytes, 1 MiB input per call, 64 MiB guest memory, ten billion fuel, five seconds per
call and 2 MiB aggregate results. Native compilation remains a controlled-workload
operation; these guest limits are not compiler or whole-process RSS containment.

A scenario fixture may include `configuration`, a relative project file, and its
exact `sha256:` digest in `identity`. A `test-adapter` file contains `entropy`
(base64 bytes, 1–4096 bytes) or `metrics` (up to 16 production metric descriptors).
A `controlled-peer` file contains `http`, with an explicit unprivileged `port` and
up to 16 `exchanges`. Each exchange declares `method`, `path`, base64 `requestBody`,
`status`, and base64 `responseBody` (each body at most 32 KiB). The host binds the
port before installing the provider; an occupied port fails the request. HTTP
redirects, ambient roots and credentials are disabled. Denied requests cannot
reach the peer. The receipt identifies selected fixtures and their digest.
Fixture changes start a separate owned helper, preserve scenario order and never
silently change an adjacent scenario's entropy or replies. At most eight such
groups run in one selection. Shared scenario assertions remain byte-exact.

## Editor tasks and compiler locations

After separately acquiring the frontend, connecting a workspace and selecting its
guest tool inventory, run `dev editor --workspace NAME --project PATH --frontend
ABSOLUTE_FRONTEND_PATH`. Tasks use the installed workspace compiler selection;
an explicit `--tool-root ABSOLUTE_LINUX_TOOL_PATH` can override it. This explicitly
writes a new `.vscode/tasks.json`; it preserves an existing task configuration.
The generated init, trust, build, up, watch, test, status, recovery, logs and down
tasks use process arguments and the same frontend as terminal commands. They do
not run on folder opening, provision a VM, acquire a tool or select credentials.

VS Code's [Workspace Trust](https://code.visualstudio.com/docs/editing/workspaces/workspace-trust)
still applies. Separately review the project recipe before using the explicit
trust task; editor trust does not satisfy the controller's recorded recipe trust.
The test task asks for an already provisioned isolated `test-` workspace. Other
editors can run the identical commands in a terminal; VS Code is optional.

With `--editor-diagnostics`, bounded compiler records also appear on stderr for
the maintained problem matcher. Rust JSON diagnostics and conventional
colon/parenthesis locations retain line/column numbers, remove terminal control
sequences, and map only declared source files back to the host. Paths outside the
captured project are not made into editor links. Spaces, Unicode names, drive
letters and CRLF messages are covered by the controller tests. A real failing
subprocess test confirms that diagnostics do not replace the last accepted build.
Source bytes and generated bindings are checked again after successful compile.

Interrupt watch to request owned shutdown. After a closed terminal or lost
connection, run status and, for a pending mutation, recover the original operation
before continuing. Closing an editor is not proof that the Linux node stopped.
These task contracts are tested; actual editor/newcomer qualification remains in
the acceptance table below.

`dev up` stays in the foreground until interruption or an explicit `dev down`
from another terminal. Its private WSL session remains open while the node is
running, so ordinary distro idle shutdown does not silently discard the node.
The session ends when the controller exits; it does not change `.wslconfig` or
create a Windows service. Status, invocation and down commands remain available
while the foreground controller waits. Use another terminal for those commands.

## Executed evidence and remaining acceptance

The developer-tools workflow builds nonpublishing Windows and WSL candidates.
The Windows bundle contains the standalone frontend, helper and release-mode
portable host, with the existing Rust SPDX/license inventory and the actual
Python/bootloader license texts. The Ubuntu image pins both OCI input digests and
additional Ubuntu package versions, retains its observed package licenses, and
disables automatic drive mounts and Windows executable interop. It does not
contain an LSF runtime, guest compiler, kernel or user credentials. Docker is a
contributor image-build tool; the end-user Windows backend uses WSL2 directly.

Candidate checksum inventories are attested only on branch/manual workflow runs.
Pull-request runs remain unsigned. Offline verification additionally requires an
independently approved exact-commit identity policy, independent Sigstore roots
and a pinned GitHub verifier. Attestation alone is not approval or qualification.

The first native Windows build ran `dev doctor` outside the checkout with Python
removed from `PATH`. Its receipt is an unsigned contributor build, not an
authenticated candidate or a clean-host application workflow. Focused Windows
tests cover protected state, exact-byte snapshots, command ownership, transport
contracts and one-shot recovery. The maintained workflow repeats these checks on
Windows and Linux and builds the Windows executable separately.

The observed host is Windows 11 build 26200.9448. With separate maintainer
consent, its Microsoft-signed WSL installer was updated from 2.5.10 to 2.7.14;
the actual guest then reported kernel 6.18.33.2. This host maintenance is not an
automatic controller action. The native runtime installer still requires Ubuntu
24.04 and kernel 6.8 or newer; no kernel version check, pressure observation or
execution profile was weakened. These observations are not a managed-node
qualification receipt.

The independently approved WSL candidate from commit
`64e589f28147f2662aadd9a4833e1eda5644e36d` authenticated and imported on this host.
Its first account-creation run failed: the ownership comment used a colon, which
Linux rejects. The account and home were absent. After checking the exact WSL
registration and those absent paths, the empty owned distribution was removed.
That candidate failed qualification. The corrected image builder now exercises
two actual accounts, private-home isolation, original-owner recovery and removal
in a disposable container before exporting a candidate. Container checks do not
replace the required repeated Windows/WSL run.

The subsequent local source image exposed a missing Ubuntu system interpreter
during native installation. The installer retained its original transaction;
after adding the pinned prerequisite in that disposable distro, explicit resume
completed installation of the approved runtime. Two unprivileged workspaces
then reached authenticated readiness on separate guest loopback ports with
distinct node IDs and credentials. One account was denied access to the other's
credential file. Stopping the first node reported a clean, reaped shutdown and
left the second ready. These are source-integration observations: the image was
locally built and modified for diagnosis, so they do not qualify a distribution.

The Rust and C tool candidates reuse the maintained #544/#545 project creators
and compiler recipes. Each supplies greeting, word-count and shipping templates
with the existing vendored SDK. The Rust Linux prefix includes Python
3.13.5, Rust 1.97.1 and its standard libraries, wasm-tools 1.254.0, wit-bindgen
0.62.0, and Zig 0.16.0 for the native linker. The linker targets the supported
glibc 2.39 userspace. Rustup and an ambient system compiler are not required in
the workspace. The C prefix supplies Python, Zig, the same binding/component
tools and the native contract helper, without a Rust compiler or registry.
Both authoring recipes emit validated component and package input
bytes; the controller then invokes the installed LSF CLI for package assembly.

The compiler inventory covers companion libraries, offline registry data and
recipe modules as well as executables. Every listed file is checked before and
after the build; unrecorded files below executable search roots are rejected.
The private build attempt receives its own writable dependency cache and bounded
temporary directories. Superseded builds can interrupt inventory verification.
Compiler output is retained within the same bounded attempt.

A local source-integration run used the Ubuntu rootfs as an unprivileged user,
with networking disabled and the staged tool prefix mounted read-only. All three
templates in each language compiled outside the runtime checkout. The greeting checks also
confirmed cache reuse, mapped diagnostics, retention of the previous accepted
build after invalid source, a new component after a fix, and reaped cleanup.
The developer workflow repeats these application builds and emits separately
attested compiler candidates on branch runs. This does not yet qualify an
authenticated Windows installation or the other four language integrations.

The actual native Windows C run executes the three compiled applications through
the common byte-exact success/declared-error scenarios. It also runs C probes for
context, log, clocks, random, metrics and buffered HTTP using the same assertions
as Rust. The C provider fixtures use the maintained SDK/compiler and generated
bindings from authoritative WIT. Fixed entropy covers the maximum unsigned
64-bit value; denied grants and the owned HTTP peer exercise production providers.
The host reports system clocks as nondeterministic. It reclaims all invocation
resources and the peer port, and keeps fixture selections separate between cases.

The first application run exposed a scenario deadline above its manifest's
wall-time ceiling. The adapter now limits invocation time to that ceiling while
retaining the scenario deadline. The first shared C random run exposed missing
probe cases for unsigned bytes and explicit denial; these now match the existing
Rust cases. Those failed attempts remain distinct from subsequent passing runs.
Native source execution does not qualify publisher identity or replace real-node
differential tests.

A later [Windows source observation](windows-developer-source-observation.json)
records an actual C watch cycle through the native frontend and WSL node.
Revision A passed success and declared-error scenarios. Editing to B published
new bytes and advanced the deployment generation; the unchanged success assertion
then failed visibly without rollback. An intentional compiler error retained B,
and a new invocation still returned B. Subsequent publication, deployment and
Invoke response-discard probes recovered each original operation identity through
a fresh frontend process. A separate actor advanced the generation, and the
controller rejected its conflicting deployment without overwriting that actor.
Restart preserved the selected publication. An excluded `.env` canary did not
enter the guest snapshot or invalidate its cached build. Snapshot, build and
operation counts remained within their declared bounds. Explicit down and purge
removed the owned node, account and distro while retaining the host source and
the unrelated Docker registration.

These runs found and corrected three controller problems: a failed foreground
lock could stop another build; a test could report the newest build while
invoking an older deployment; and a semantic UNKNOWN receipt was reported as
transport loss. Cleanup now requires that this foreground controller dispatched
start. Node tests require the accepted build to match the confirmed deployment,
observe its current scope and generation, and compare every returned invocation
revision. Unknown, uncertain-durability and transport outcomes retain separate
diagnostics and the same pending operation. Missing recipe trust also reports an
actionable trust error before tool selection. The observation retains the failed
attempts and identifies the updated source frontend/helper bytes used to verify
the fixes. It is not final authenticated distribution qualification.

`tools/dev_node_fault_probe.py` is a contributor fault-injection harness, separate
from the shipped helper. Run it only as the explicitly selected `test-` workspace's
unprivileged Linux owner, with its exact helper path and SHA-256. It requires the
local experimental profile and uses the installed operator and real node. Release,
deployment and Invoke modes discard one actual successful response before the
controller records it; recover with the normal frontend afterward. The concurrent
mode records a separate actor's intent and applies observed preconditions. The
unknown mode prepares an undispatched intent and tests honest non-replay; it does
not establish receipt expiration. The harness never marks qualification complete.

| Child | Remaining Windows acceptance |
| --- | --- |
| #560 | Independently approved exact-source developer policy; authenticated bundles; actual local/SSH lifecycle and failure receipts. |
| #561 | Independently authenticated WSL image; actual provisioning, workspace isolation, stop/restart and purge schedule. |
| #562 | Mac/native ARM64 requirements deferred by maintainer; no ARM64 support claim. |
| #563 | Authenticate/install Rust and C tools through the Windows workflow and integrate the other four language-owner recipes. |
| #564 | Complete malformed/admission failure, rapid edits, in-flight revision, revocation and expired-receipt cases; repeat the observed source watch/recovery schedule with final authenticated packages. |
| #565 | Complete provider fixtures and actual failure/cancellation/restart cases for all six languages. |
| #566 | Complete explicit clock fixtures, verified native distribution and real Linux differential execution; Windows CI includes the locally exercised Rust/C subsets. |
| #568 | Complete editor/devcontainer integration and exercised newcomer walkthrough. |
| #569 | Actual packaged Windows qualification and reviewed consolidated evidence. |

`latent.dev.qualification.v1` rejects missing entries, mocks, cross-builds,
wrong environments, unsupported required scenarios, incomplete language coverage
and unconfirmed cleanup. It intentionally cannot turn the checks above into epic
completion. No public release, tag, support expansion or Phase 3 closure is
authorized by this work.

## Contributor verification

```powershell
python -m unittest tools.tests.test_dev_workflow tools.tests.test_dev_contracts tools.tests.test_dev_build_cache tools.tests.test_dev_watch tools.tests.test_dev_tools tools.tests.test_dev_tool_install tools.tests.test_build_process
python tools/latent_dev.py dev doctor
python -m pip install --require-hashes -r tools/dev-frontend-windows.lock
python tools/build_dev_frontend.py --output target/dev-candidate
```

Use Python 3.13.5 for the reproducible Windows packaging environment. The
`--output` directory must be new. `build.json` records source dirtiness, actual
frontend/helper/lock digests and the precise smoke-test boundary. It never
asserts authenticated publication or managed-node qualification.
