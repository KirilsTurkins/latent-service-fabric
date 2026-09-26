# Windows developer controller implementation

This work implements the Windows portion of [epic #559](https://github.com/KirilsTurkins/latent-service-fabric/issues/559).
On September 24, 2026, the maintainer removed Mac, Lima and Apple Silicon requirements
from the epic and its children. The active scope is Windows x86-64/WSL2, native
Windows tests, Linux x86-64/direct, explicit SSH, and opt-in devcontainer tooling.
Issue #562 was removed and closed as not planned; it is not an implemented feature.
The [packaged platform handoff](packaged-platform-handoff.md) records the passing
five-entry schedule. Build/watch/native children #563/#564/#566 are closed;
editor/newcomer work and final combined review remain open under #568/#569.

`latent-dev` is a separate executable. It does not replace `latent`, change the
operator CLI's single-operation behavior, or enable a production Windows node.
The Windows and Linux executables include their Python interpreter; application developers
do not need Python, Rust, or an LSF checkout to run that executable. Guest
compilers remain separate, explicitly selected build inputs.

The Linux frontend is packaged by the same build and distribution owners as the
Windows frontend. The existing Linux portable-host CI job produces its
`linux-x86_64` candidate, including the helper, portable host, dependency inventory,
licenses and exact-source provenance. Linux build inputs have a separate hashed
wheel lock. The build records its glibc version as a conservative minimum for
that artifact and observes the package owners and license texts of every
redistributed native library. All frontend files, including shared libraries,
are checked again before candidate assembly.

An actual local source package ran as an unprivileged user in the pinned Ubuntu
24.04 image, with no Python or LSF checkout in that image, no network and a
non-ASCII installation path containing spaces. Its `dev doctor` result reported
Linux without claiming node readiness. This establishes packaged frontend
startup only. The later authenticated direct-Linux/SSH installation and lifecycle
runs are recorded in the platform handoff. The helper's selected interpreter
requirements are described below.

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
  verifier. Transfers use 1 MiB chunks, at most 16 files/1,152 MiB per selection,
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

The packaged platform handoff supplies the later installed-artifact runs. The
historical source observations below remain separately labeled; an adapter unit
test is not a WSL provisioning receipt.

## Project, transfer and test boundaries

`latent.dev.project.v1` is closed and versioned. It identifies the language
owner (#544–#549), immutable template revision, ABI, build host, pinned tools,
explicit input roots, exclusions, output paths and application scenarios.
It integrates the six merged language owners' artifacts and build recipes.

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
4 GiB ceiling. This is an observed limit, not a filesystem quota: temporary
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
An optional `nodeTimeoutMillis` selects a separate bounded node deadline, up to
120 seconds. Managed-language templates use their maintained 120-second node
ceiling because a cold node charges compilation to the activation. Their portable
guest deadline remains five seconds, with separate native preparation. Each
result records the selected deadline; output comparisons do not claim identical
cold-start timing. The complete selection remains bounded to five minutes.
The current node runner requires an explicitly selected `test-` workspace.
After building its first project, stop that workspace and run
`dev prepare-test --workspace test-NAME --consent-test-fixtures --admission
signed-fixture` before its first deployment. This uses the workspace's installed
tool selection; `--tool-root ABSOLUTE_LINUX_TOOL_PATH` explicitly overrides it.
This selects the language's bounded memory/engine profile and, when
needed, installs its maintained clock/random providers. It preserves the private
operator credentials and refuses existing provider configuration, a running node,
a pending operation, another project or changed configuration bytes. The command
does not grant capabilities. Each scenario's explicit grants become scoped
policies through the public operator API and a confirmed deployment generation.
Policy recovery looks up the original operation and checks the current policy's
scope, document and receipt; unknown or changed policies never trigger replay.
An explicit `localService` fixture builds one additional project from beneath the
caller's source snapshot. Its closed selection contains `project` (relative
directory), `recipeSha256` (the exact `project.trust_identity` of that project's
descriptor), `service`, `deployment` and exported `contract`. Review that recipe
before passing it to `prepare-test --fixtures`: fixture consent authorizes this
additional pinned build. Preparation allows at most 900 seconds for that build
and 150 seconds for verification/signing/configuration, with one fixed callee and
the same bounded build-cache limits as the caller.

The caller and callee are signed together under one private short-lived policy,
then published and deployed separately through the ordinary operator APIs. Both
run on the same node with two cells, one live child per parent and depth two.
Declare `real-provider`, bind the fixture configuration digest and require
`local-service-fixture`. A scenario grant permits only the callee's exact
service/publication. The fixture is unavailable on the portable host. Status
reports a pending callee operation separately; `dev recover` queries that
original operation if the caller has none pending. It never repeats publication,
deployment or Invoke after an unknown result. Cleanup requires the owned node
to stop and refuses callee build attempts with unconfirmed process cleanup.

The runner compares each invocation with the generation selected for that case.
The `signed-fixture` option calls the pinned language bundle's maintained
`capsule-test-signer` utility. It verifies the actual build observation, produces
a signed package and scoped evidence, and creates a private, 30-minute test
policy. The utility holds signing keys only in memory. Deployment then uses the
normal public `release publish-package` API and enforced package admission.
The report distinguishes the original compiled package from the signed fixture's
package, which also contains its SBOM. An expired fixture or a changed accepted
build requires a new test workspace; the controller never silently re-signs it.
`--admission trusted-local` remains available for templates without provider
imports. Go, Java and C# require signed package admission for their runtime
capability bindings. These test profiles require `local-experimental-v1` and do
not qualify the external-capsule profile.

The controller joins a completed compiler observation with its separately
completed packaging step, preserving the original compiler bytes. This unsigned
local observation becomes authenticated test evidence only through the explicit
fixture signer. It grants no production builder approval. After a confirmed
shutdown, an enforced restart waits five seconds for the runtime's persisted
clock lease before opening the same catalogs. It neither edits the ledger nor
retries a rejected mutation. Lost Invoke results use bounded status queries for
the original activation ID. A terminal status without the original typed result
still fails the scenario; an unknown status retains the pending operation.
Retained status reports the last lifecycle phase (such as `running`) separately
from its terminal state. Recovery requires a coherent terminal state/outcome,
completion timestamp and final accounting; a lifecycle phase alone cannot settle
the original invocation. The [recovery source observation](recovery-source-observation.json)
records actual lost signed-publication, deployment and Invoke responses recovered
by fresh helper processes, with one original mutation each. It also covers wrong
token/tenant invocation denial, retained restart and concurrent-deployment rejection.
The explicit never-dispatched unknown-intent case remains private and unreplayed;
it is not evidence of an expired receipt. Run `tools/dev_recovery_fixture_probe.py`
with the installed source-observation kit for this focused contributor check.

An explicit `execution.cancelWhenRunning: true` requires
`requires: ["running-cancellation"]`. The node adapter starts one Invoke, polls
that original activation at most 64 times within five seconds, and sends one
public Cancel only after observing `running`. It persists the cancellation intent
before dispatch. An accepted Cancel is insufficient: the original invocation
must return `cancelled` with its confirmed revision. Lost responses remain
uncertain and never cause a second Invoke or Cancel. This node-only requirement
blocks portable execution; portable `cancelBeforeStart` remains a separate test.

Resource-failure scenarios may explicitly declare
`expect.platformCodes: {"node": "resource-exhausted", "portable": "fuel-exhausted"}`
or the corresponding `memory-exhausted` portable detail. Both environments must
return the declared platform-failure category and their exact declared code.
Comparison retains both codes and recognizes only these reviewed public-node
versus engine-detail mappings. Typed values, errors, component bytes and node
revisions keep their existing exact comparisons.
The [failure source observation](failure-fixture-source-observation.json) records
13 signed real-node scenarios, a retained restart, and 12 shared cases on each
portable host. The separate native `after-cancel` case checks a fresh Store;
running cancellation itself is evidenced only by the node's explicit receipt.
The probe is `tools/dev_failure_fixture_probe.py`; the Windows comparison is
`tools/run_dev_failure_portable.py`. Both preserve failed reports and run within
the existing Rust/Windows CI owners. These source observations do not qualify
an authenticated final installation or a clean Windows host.

The native portable host reuses the production component engine, WIT surface,
canonical value codec, fresh-store ownership and capability policy broker.
It executes prebuilt controlled development components without Linux. Its
initial exercised Windows subset is Rust typed success/declared error,
missing-import denial, cancellation, traps, fuel/memory/deadline interruption,
and subsequent fresh-state success. Additional actual Rust SDK capsules cover
random bytes and unsigned values, all four custom metric kinds, explicit policy
denials, and buffered HTTP through the production provider and an owned loopback
peer. The C provider subset and all six languages' tutorial applications are also
exercised below; real-node differential qualification remains required work.

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
cleanup, explicit guest clock/entropy fixtures and omitted node/security behavior.

The closed `latent.dev.portable-request.v1` import profile is:

| Import | Implementation and fixture boundary |
| --- | --- |
| `latent:context/context@0.1.0` | Production activation context, explicit per-call grant |
| `latent:log/log@0.1.0` | Production bounded activation log sink |
| `latent:clock/monotonic@0.1.0`, `latent:clock/wall@0.1.0` | Production authorization and accounting; system readings or explicit fixed guest readings |
| `latent:random/random@0.1.0` | Production provider; system entropy or an explicitly selected repeatable byte fixture |
| `latent:telemetry/custom@0.1.0` | Production metric provider, bounded declared metric/label sets and joined exporter |
| `latent:http/client@0.2.0` | Production HTTP provider, one owned authenticated IPv4 loopback peer, exact approved methods/paths and reply bytes |

No implicit WASI, filesystem, environment, other socket, secret or cloud import is
installed. Imported streaming/resource interfaces outside this table are rejected
before guest execution. Canonical arguments and results use the production value
codec, including decimal-string unsigned 64-bit values and explicit absent values.
One request runs at most 128 calls sequentially with fresh Stores, 16 MiB component
bytes, 1 MiB input per call, 64 MiB guest memory (128 MiB for the explicitly
selected .NET NativeAOT or TypeScript SpiderMonkey profile), ten billion fuel, five seconds per
call and 2 MiB aggregate results. Native compilation remains a controlled-workload
operation; these guest limits are not compiler or whole-process RSS containment.

A scenario fixture may include `configuration`, a relative project file, and its
exact `sha256:` digest in `identity`. A `test-adapter` file contains `clock`, `entropy`
(base64 bytes, 1–4096 bytes) or `metrics` (up to 16 production metric descriptors).
A shared node/native metrics dependency uses `real-provider` with only `metrics`.
A `controlled-peer` file contains `http`, with an explicit unprivileged `port` and
up to 16 `exchanges`. Each exchange declares `method`, `path`, base64 `requestBody`,
`status`, and base64 `responseBody` (each body at most 32 KiB). The host binds the
port before installing the provider; an occupied port fails the request. HTTP
redirects and ambient roots/credentials are disabled. A fresh private credential
authenticates the owned peer; the production provider injects it for the exact
fixture origin. Guest arguments and public reports contain no credential value.
Denied requests cannot reach the peer. The receipt identifies selected fixtures,
their digest, authenticated exchanges and completed provider cleanup.
Fixture changes start a separate owned helper, preserve scenario order and never
silently change an adjacent scenario's entropy or replies. At most eight such
groups run in one selection. Shared scenario assertions remain byte-exact.

The optional `clock` object has exactly `monotonicNanos` and `wallUnixMillis`,
both canonical decimal strings from `"0"` through `"18446744073709551615"`.
Each guest clock import returns its selected constant after the ordinary
capability authorization and budget charge. The report labels these as
`fixed-guest-readings-fixture`; `controlClock` remains the real system clock.
The `development-clock-fixture` Cargo feature is disabled by default and cannot
be selected with an external-capsule profile. It does not change admission,
certificate validity, provider currentness, scheduler time, activation deadlines,
fuel or cancellation. Without a clock fixture, guest readings use the system
clock.

For a stopped, disposable `test-` node, add `--fixtures path/to/clock.json` to
`dev prepare-test --consent-test-fixtures --admission signed-fixture`. The JSON
file contains `{"clock":{"monotonicNanos":"0","wallUnixMillis":"0"}}`.
The node must come from an explicitly selected development-test runtime
candidate. Ordinary runtime builds reject this configuration. The controller
checks the installed executable against the proposed configuration before
replacing the workspace's configuration. Existing configuration, consent,
fixture identity and signed-test scope remain checked on recovery. Each node
keeps one fixture selection; another selection requires another disposable
workspace. Scenario files must reference the same fixture bytes and digest.

The native candidate workflow's explicit `development_test_node` dispatch input
builds this artifact with `latentd/development-test-node`, which is disabled by
default. Its authenticated manifest marks it as a disposable test candidate.
Verification rejects release authority for that artifact, and installation
rejects system-wide, ordinary development and external-capsule destinations.
Use a local directory such as `.lsf-dev/test-clock/runtime`. This does not
authorize publication or supply an independently approved publisher policy.

An HTTP fixture uses the same `prepare-test` command with a file containing
`{"http":{"port":43127,"exchanges":[{"method":"GET","path":"/fixture","requestBody":"","status":200,"responseBody":"b2s="}]}}`.
Choose an available unprivileged loopback port explicitly. Each node workspace
keeps its own private provider credential and immutable fixture selection;
changing the selection requires another disposable workspace. The node uses
the production HTTP provider and local secret store. HTTP alone works with an
ordinary compatible runtime; fixed clocks still require the development-test
runtime. The capsule must declare a nonzero `outboundRequests` budget and the
scenario must grant `latent:http/client@0.2.0` explicitly.

The node supervisor binds the peer before node startup, checks its readiness,
and owns all its sockets. It accepts at most four simultaneous connections and
128 total connections, with a two-second request deadline and a 900-second
lifetime per node start. Header storage is bounded to 8 KiB/32 headers, each
request/reply body to 32 KiB, and the complete fixture to 192 KiB. A live listener
on the selected port causes startup failure. Node shutdown closes the owned
listener/connections; retained restart uses the same scoped credential. The
native host owns one sequential peer with the same request count and time
bounds. Its credential comes from system entropy independently of any guest
entropy fixture and uses zeroizing storage for its owned secret value.

Declare this dependency as `controlled-peer` with its configuration file and
digest, and require `buffered-http-fixture`. The common runner accepts it only
after the actual node reports the matching authenticated peer ready. Reports
record request counts before and after execution. Comparisons require identical
public fixture data and completed exchanges on both hosts; they do not equate a
controlled loopback peer with an external-service qualification.

An event fixture uses the same explicit setup command with a file such as
`{"events":{"port":43128,"exchanges":[{"topic":"dev.example","payload":"b2s=","mode":"ack"}]}}`.
Declare `controlled-peer`, bind its configuration digest and require
`immediate-event-fixture`. The capsule must declare outbound operations and
grant `latent:events/publisher@0.2.0`. The production NATS publisher connects
through TLS to an owned loopback protocol peer. This fixture does not establish
live JetStream broker or consumer-processing qualification.

The pinned bundle's fixture utility generates a private TLS key and certificate;
setup generates a separate private token. Both remain in the owned workspace,
are checked on retained restart and are removed by explicit owned purge.
No ambient OpenSSL executable, broker, network discovery or user credential is
needed. Public receipts exclude private key/token bytes and their value digests.

Select at most sixteen exact topic/payload exchanges, with modes `ack`,
`duplicate`, `drop-ack`, `wrong-stream`, `malformed-ack` or `no-responders`.
Payloads are canonical base64, at most 32 KiB each; the fixture is at most
192 KiB. Peer ownership is bounded to four simultaneous connections, 128 total
connections and publishes, 128 commands per connection, two seconds per partial
frame and 900 seconds per start. TLS and authentication precede publication.
The supervisor owns and closes every socket. The guest's production provider
returns `uncertain` after a lost or invalid acknowledgement and never resends it.
Before/after per-topic receive counts expose accidental duplicate sends.
Portable hosts reject required event fixtures before running selected cases.

A blob fixture selects `{"blob":{"namespace":"dev-blobs"}}` through the same
explicit `prepare-test` command. Declare its dependency as `real-provider`, bind
the configuration digest and require `immutable-blob-fixture`. This installs the
production Linux immutable-blob provider in the private test workspace, with a
separate provider service identity and a policy restricted to this namespace.
The capsule must explicitly budget outbound operations and blob read/write
bytes. Fixture configuration supplies no host path, ambient files or grants.

Use guest APIs to create and seal test data. Blobs persist across a retained
node restart. Writer/reader handles and component chunks retain their normal
activation ownership; abandoning a writer does not publish its bytes. The
provider bounds durable stages at 16 and reclaims a retired stage when admitting
another writer at capacity. Charged durable stages may remain after a clean
shutdown, while live handles and work must be zero. Explicit owned-workspace
purge removes that retained test data. Portable hosts reject required blob cases
before executing any selected scenario.

A secret fixture selects only public development references, for example
`{"secrets":{"references":[{"name":"dev-allowed"},{"name":"dev-expired","expired":true}]}}`.
The explicit test setup generates a separate private 64-byte value for each
reference and workspace. Values, file paths and environment sources cannot be
supplied in the fixture. Existing values are never silently rotated or replaced;
a changed selection or value fails closed. Declare `real-provider` with the
configuration digest and require `scoped-secret-fixture`. The production local
secret provider receives named, protected files and exact reference policies.
An `expired` entry uses a past system-clock deadline; it does not change any
clock. Public receipts carry references and outcomes, with no secret bytes or
secret-value digests. Shutdown observes released in-memory generations and
references; retained private files follow the owned-workspace purge lifecycle.

Explicit `purge` also removes the owned HTTP authorization file, event TLS key
and authorization material, and generated secret fixture files. Before removing
runtime or build state, it checks every fixture directory for private ownership,
recognized bounded files and safe paths. Unknown files, links, changed inputs or
an unrelated owner stop cleanup. Interrupted fixture preparation is covered by
the same checks. `down` retains these files for a later restart; purge returns
the names of removed fixture directories and preserves author sources and other
workspaces.
Required secret fixtures cannot execute on the portable host.

A metrics fixture selects `{"metrics":[{"name":"dev.calls","kind":"counter","unit":"1","labels":[{"key":"region","values":["east"]}],"histogramUpperBounds":[]}]}`.
Declare `real-provider`, bind the configuration digest and require `metrics`.
The stopped test node installs the production metric provider with its existing
shared telemetry exporter. Actual startup must report the matching provider;
declaring a fixture cannot count as initialization. Each scenario needs an
explicit grant, with a policy restricted to the selected metric names and the
actual per-call cost, including one Boolean output byte. The provider separately
bounds cumulative observations and record bytes per activation; a per-call
policy ceiling is not a cumulative activation limit.

`dev down` returns bounded actual metric exports after the exporter joins: name,
unit and exact floating-point value bits, with no source or guest labels. The
exported name starts with `latent.application.`. Queue bytes, accepted/captured
counts, truncation and sink-loss counters make missing data visible. Node/native
comparison requires the same descriptor bytes, typed results, exact exports and
confirmed exporter/queue cleanup. A truncated observation cannot pass this
comparison. Runtime catalog series remain bounded metadata until owner drop.

## Editor tasks and compiler locations

The [optional terminal devcontainer](../component-development/devcontainer.md)
uses the same packaged frontend and explicit SSH backend. Its generated files
require an authenticated Linux bundle and explicit consent; building and
starting remain separate terminal actions. See the guide for the pinned inputs,
private ownership locations, networking boundaries and exercised environment.

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
The [executed Windows editor integration](editor-task-integration.md) covers
actual task execution, live compiler diagnostics, last-good deployment, task
termination, explicit down, retained restart and untrusted folder opening.
Watch uses build start/end markers to flush and clear its background problem
matcher while the task remains running. The separate clean-machine newcomer
walkthrough and final authenticated package qualification remain open.

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
additional Ubuntu package versions against the
[Ubuntu snapshot](https://snapshot.ubuntu.com/) `20260924T120000Z`, retains its observed package licenses, and
disables automatic drive mounts and Windows executable interop. It does not
contain an LSF runtime, guest compiler, kernel or user credentials. Docker is a
contributor image-build tool; the end-user Windows backend uses WSL2 directly.
The image receipt records the snapshot ID. Package signatures remain verified
with Ubuntu's archive keyring; updating the snapshot is an explicit recipe change.

Candidate checksum inventories are attested only on branch/manual workflow runs.
Pull-request runs remain unsigned. Offline verification additionally requires an
independently approved exact-commit identity policy, independent Sigstore roots
and a pinned GitHub verifier. Attestation alone is not approval or qualification.

The manual [platform preflight](../../.github/workflows/developer-platform-preflight.yml)
checks a fresh Windows 2025 runner's actual WSL2 environment and kernel using an
exactly named disposable Ubuntu distribution, pinned to Canonical's published
SHA-256. It validates registry ownership before stopping and unregistering it.
It uses no source checkout, compiler or LSF candidate and retains bounded failed
observations. The first attempt found WSL installed but no registered distribution,
so starting the system environment alone could not observe an actual kernel.
Its only automatic trigger is the explicitly named qualification
branch when that workflow changes. A successful preflight identifies a possible
host for the packaged schedule; it does not count as application qualification.
Documentation, CI inventory and preflight-only pushes do not rebuild every guest
bundle; explicit candidate dispatch and application-source changes retain their
existing build lanes.

An [actual hosted preflight](./hosted-wsl-preflight-observation.json) passed on
September 25: Windows Server 2025 build 26100.33296, WSL 2.7.13 and the booted
`6.18.33.2-microsoft-standard-WSL2` x86-64 kernel. Its pinned Ubuntu image was
imported, observed, stopped and unregistered after exact registry/path checks.
The first failed attempt is retained. This supplies an available fresh Windows
runner for further testing, without claiming LSF package qualification or general
support guarantees for nested virtualization.

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
authenticated Windows installation or all six language integrations.

The Java and C# integrations now reuse the merged #548/#549 creators and recipes.
Their compiler bundles capture the pinned JDK/Gradle or .NET SDK, WASI SDK and
locked dependency files. Each build verifies the captured files and extracts a
private writable copy; Gradle uses offline mode and NuGet has no enabled feeds.
The minimal WSL image includes the pinned ICU library required by .NET.
Source locations map back to the original author directory, including spaces and
Unicode. Guest staging uses the separately generated workspace paths: the pinned
MSBuild cannot execute its temporary scripts when its own temporary root contains
spaces. This does not constrain the Windows author folder.

The [managed-language source observation](managed-developer-source-observation.json)
records actual unprivileged, network-disabled builds of all three Java and C#
templates. Cache reuse, mapped compiler failures, last-good artifact retention,
changed-source output and cleanup passed. The same components then passed all
nine shared tutorial cases on each native Windows and Linux host, with matching
typed result bytes. Java selects its maintained linear-memory engine profile;
C# selects its bounded NativeAOT memory profile. Required clock grants are explicit
in the scenarios. CI repeats native comparisons for all six languages.
These are source-integration and native-host comparisons; they do not qualify
publisher identity, managed WSL installation or real Linux-node differential tests.

The [Go and TypeScript source observation](go-typescript-developer-source-observation.json)
records all three maintained templates building with pinned offline compiler
bundles, an unprivileged Linux account and no network. Both languages passed
cache reuse, mapped compiler failures, last-good retention, changed-source output
and cleanup. Go retains its reviewed module graph; TypeScript retains its npm
lock and gives Wizer private compiler configuration/cache paths. Both languages
also passed all nine common tutorial cases on native Windows and Linux hosts,
with identical typed results. TypeScript used release-mode hosts. CI now builds
and compares all six languages on native Windows and Linux. Native preparation
has a separate 120-second allowance, each activation retains its declared
deadline, and one scenario run is bounded to five minutes. The observation retains
the earlier failed preparation attempts alongside the passing release-host runs.

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

The [node source observation](node-developer-source-observation.json) records
Go, TypeScript and Java greeting builds followed by signed package publication,
enforced admission and all three typed application scenarios on a real node.
All three retained the exact deployment through shutdown and restart, then passed
the selected success scenario without republishing or redeploying. Go's scoped
runtime grants were applied through public policy and deployment APIs. The runs
used offline source-built artifacts and private Linux container workspaces on
the Windows WSL kernel. They establish neither authenticated artifact
installation nor clean-host or external-profile qualification. The exact Go and
TypeScript component, capsule and contract bytes also passed the same three cases
on native Windows. `tools/compare_dev_node_portable.py` checks artifact identities,
typed result bytes, selected node revisions, environment labels and cleanup. This
comparison covers the selected tutorial values; deterministic provider fixtures
and the broader failure/ownership differential remain required work.

The existing six-language compiler-bundle CI owner now also stages a separate
source-built node and runs each of the three compiled tutorials through
`tools/dev_node_application_probe.py`. Each application uses a private disposable
workspace, explicit signed-test admission, public publication/deployment APIs,
the shared scenarios, and a retained restart without redeployment. The node and
compiler test must use the same observed packager. Interrupted or uncertain
cleanup retains the private workspace and fails the report. These source checks
do not authenticate a candidate or establish clean-host qualification.
The node build uses the existing `.cargo/managed-guest.toml` compiler-library
optimization overrides, records their digest and retains host debug assertions.
An earlier unoptimized TypeScript node exhausted its cold activation deadline;
the test retains the same finite activation budget with the reviewed build profile.
Publication and deployment share a 300-second controller deadline. TypeScript
uses its language owner's explicit 125-second operator wait for package/control
preparation, within that overall deadline and the node's configured server limit.
The frontend and watch transport allow 15 additional seconds for owned cleanup.
A timeout retains the original operation identity and a bounded observation of
its error code and result digest; it never starts another publication attempt.
Workspace startup has a 180-second overall bound, including preflight and up to
120 seconds of authenticated readiness polling. Repeated immediate connection
refusals consume that time allowance instead of exhausting ten attempts in five
seconds. The transport reserves 15 seconds for owned cleanup. A failed startup
retains its lifecycle error and must be inspected before another operation.

The Windows native owner consumes the exact compiled bytes and node reports with
`--require-node-parity`. It compares typed values, platform errors, the explicit
execution controls and each case's confirmed deployment generation. Managed
language cases explicitly deny their required clock/entropy policies, then
restore the allowed policies and invoke fresh state. A runtime unable to
initialize under that denial reports a guest trap; missing-grant admission
failures and declared application errors are separate outcomes. The existing
native Linux owner compares the same applications with Windows. A required
Linux-only scenario prevents any portable execution; selecting only the common
case is an explicit separate run.

The later [common source observation](common-node-source-observation.json)
records all six languages and all 18 tutorials: 72 shared node scenarios matched
the exact component bytes on native Windows, and 18 retained restarts invoked
without republishing or redeploying. This includes explicit runtime-policy denial
and fresh-state recovery for Go, Java and C#. Compiler failure, cache reuse and
changed-source checks ran in the same application-build owner. The receipt
retains earlier assertion failures and the unoptimized TypeScript CI failure.
These are source observations with the actual runtime and report identities;
authenticated installation and clean-host qualification remain open.

The later native clock-fixture checks execute the actual Rust and C capability
components on Windows and the Rust component on Linux. Both extreme `u64`
readings (`0` and `18446744073709551615`) retain their exact typed bytes in
separate shared-scenario fixture groups. A frozen guest clock does not prevent
the real deadline or cancellation from interrupting execution, and the next
invocation starts with fresh state. The Windows executable digest is
`sha256:6674ca8ada67edeeba1d8ec19c6dad376f3277ebecdaaf8305d4a66de70c1e3d`;
the Linux executable digest is
`sha256:22c207e081de73115ed4510d10db736b1ab23db4a256015394ec747ac46b1603`.
These earlier portable-host runs alone do not establish the
required node/portable deterministic-provider comparison.

The later [shared clock observation](./clock-fixture-source-observation.json)
records an authored Rust capsule built through the installed standalone recipe,
signed with the existing ephemeral test utility and admitted by the actual
Linux node. Eight shared cases cover zero and the maximum unsigned 64-bit value,
cold/warm execution, explicit policy denial and fresh success. The same component
and scenario bytes pass on the Linux portable host and native Windows host.
Both test nodes also invoke the retained deployment after a clean restart,
without republishing. Owned node and portable processes are confirmed reaped.
These source observations retain failed attempts and identify their exact
runtime/helper/host bytes. Final authenticated candidates, clean Windows/WSL
execution and the remaining provider/failure matrix are still required.

The focused contributor command is `python tools/dev_clock_fixture_probe.py
--payload TOOL_PREFIX --source-node SOURCE_NODE --portable-host NATIVE_HOST
--output NEW_DIRECTORY` on Linux. Its exported public project and node receipts
feed `python tools/run_dev_clock_portable.py --host NATIVE_WINDOWS_HOST
--inputs EXPORTED_DIRECTORY --output NEW_REPORT`. The existing developer-tools
Rust and Windows jobs execute these commands; no separate full workspace campaign
is added.

The [HTTP source observation](./http-fixture-source-observation.json) records six
shared cases on a signed/enforced Linux node, Linux portable host and native
Windows host: cold/warm GET, HEAD, denied path, denied policy and subsequent
success. Four allowed requests reach each peer; denied requests do not. The
node also invokes its retained deployment after restart. All 19 invocations
completed with owned process/peer cleanup. The initial authored fixture declared
zero outbound requests; the node correctly prevented all network calls. Its
failed attempt is retained in the observation. These source runs do not qualify
authenticated final packages or clean Windows/WSL installation.

Run `python tools/dev_http_fixture_probe.py --payload TOOL_PREFIX --source-node
SOURCE_NODE --portable-host NATIVE_HOST --output NEW_DIRECTORY` on Linux, then
`python tools/run_dev_http_portable.py --host NATIVE_WINDOWS_HOST --inputs
EXPORTED_DIRECTORY --output NEW_REPORT` on Windows. Both commands execute the
same public scenario format and component bytes outside the checkout.

The [blob source observation](./blob-fixture-source-observation.json) records 27
authored cases on the signed/enforced Linux node and a retained read after
restart without writing the object again. Cases cover cold seal, warm read,
denial, closed handles, dropped/abandoned chunks, abandoned writers and admission
beyond the 16-stage limit. Both shutdowns reported zero live provider resources;
16 bounded durable stages remained charged until the owned test workspace was
purged. The first attempt passed its ten invocations but failed an incorrect
probe assertion that durable stages must be zero; that failed attempt and its
retained private workspace are recorded separately. This is source integration,
with no portable-blob, authenticated final-candidate or clean-host claim.

Run `python tools/dev_blob_fixture_probe.py --payload TOOL_PREFIX --source-node
SOURCE_NODE --output NEW_DIRECTORY` as the Linux test owner. It uses the same
maintained Rust application tool bundle, public scenario contract and enforced
admission path as the other application probes. Existing Rust developer CI owns
the run and retains its public receipts.

The [secret source observation](./secret-fixture-source-observation.json) records
nine authored cases and a retained restart on the signed/enforced Linux node.
Cold/warm reads return only the generated value's length. Expired and ungranted
references return typed errors, an abandoned value is followed by fresh-state
success, and denied policy is followed by a successful read. Both shutdowns
reported zero retained secret generations, references and live provider
resources. The owned successful workspace was purged. The run does not claim
access to another workspace or an existing provider credential: its ungranted
reference cases test the narrower configured reference restriction.
The same rebuilt node also passed the six HTTP cases, retained restart and six
Linux portable comparisons with zero retained HTTP credential generations.
An earlier regression setup exceeded the existing Unix socket path bound and
failed before node-start dispatch; a new workspace under a shorter private home
completed the run. That failed setup remains recorded with its private data.

Run `python tools/dev_secret_fixture_probe.py --payload TOOL_PREFIX --source-node
SOURCE_NODE --output NEW_DIRECTORY` as the Linux test owner. The existing Rust
developer job executes it. Public source receipts contain no secret values or
value digests; final authenticated Windows qualification remains separate.

The [metric source observation](./metric-fixture-source-observation.json) records
nine shared authored cases on the signed/enforced node, Linux portable host and
native Windows host, plus a retained-node invocation: 28 invocations and 19
captured metric records. Cold/warm emissions, invalid name/label/kind, denied
policy, subsequent success and two observations in one fresh activation retain
exact typed values and metric value bits. Both node shutdowns and native hosts
joined their exporter and drained queued bytes, without truncation or sink loss.

The first run exposed rejection of the node's canonical revision IDs by the
production metrics registry; source validation now preserves those exact IDs.
Two further failed attempts retain a zero-output-byte fixture policy and an
incorrect probe assumption about per-call ceilings. These records are distinct
from the passing run. This bounded comparison does not qualify queue saturation,
rate pressure, final authenticated packages or a clean Windows host.

Run `python tools/dev_metric_fixture_probe.py --payload TOOL_PREFIX --source-node
SOURCE_NODE --portable-host NATIVE_HOST --output NEW_DIRECTORY` on Linux, then
`python tools/run_dev_metric_portable.py --host NATIVE_WINDOWS_HOST --inputs
EXPORTED_DIRECTORY --output NEW_REPORT` on Windows. Existing Rust and Windows
developer jobs execute the probes and retain the public component and receipts.

`tools/dev_node_fault_probe.py` is a contributor fault-injection harness, separate
from the shipped helper. Run it only as the explicitly selected `test-` workspace's
unprivileged Linux owner, with its exact helper path and SHA-256. It requires the
local experimental profile and uses the installed operator and real node. Release,
deployment and Invoke modes discard one actual successful response before the
controller records it; recover with the normal frontend afterward. The concurrent
mode records a separate actor's intent and applies observed preconditions. The
unknown mode prepares an undispatched intent and tests honest non-replay; it does
not establish receipt expiration. The harness never marks qualification complete.

The [local-service source observation](./local-service-fixture-source-observation.json)
records fourteen authored caller scenarios and one retained-restart invocation.
The distinct caller and callee packages were built outside the checkout, signed
together and deployed through public APIs to one Linux node. Calls covered
cold/warm state, declared errors, denied service/tenant/contract/route/function,
denied policy, a child trap, recovery and two fresh child activations. The callee
publication and deployment survived restart unchanged. Both shutdowns released
all live provider resources, the callee compiler was confirmed reaped and the
successful private workspace was purged.

The initial zero-child-call-budget attempt retained an original Invoke after a
transport failure and UNKNOWN lookup. Its workspace and uncertain operation are
preserved without replay. A later successful run preceded the final compiler
status/cancellation integration; both that run and the final source identities
are recorded. These observations do not qualify cross-workspace access, the
portable host, authenticated final candidates or a clean Windows host.

The [event source observation](./event-fixture-source-observation.json) records
sixteen authored scenarios and one retained-restart invocation through the
production NATS provider and an authenticated TLS protocol peer. Cases cover
cold/warm success, duplicate receipts, unknown/invalid topics, invalid events,
policy denial, lost acknowledgement, wrong stream, malformed acknowledgement,
no responders and recovery with a new permitted event. Each uncertain case
reached the peer exactly once. Both shutdowns closed every peer socket and
released provider work and secret generations. The private workspace was purged.

Two source-tool preparation failures were rejected before compilation or node
startup and remain recorded. The final receipt identifies the actual node,
helper, signer and tool inventory. Run `tools/dev_event_fixture_probe.py` for
this contributor check; the existing Rust CI owner retains its receipts. This
does not qualify a live broker, native portable events, final authenticated
candidates or a clean Windows host.

The focused contributor command is `python tools/dev_local_service_fixture_probe.py
--payload TOOL_PREFIX --source-node SOURCE_NODE --output NEW_DIRECTORY` as the
Linux test owner. The existing Rust developer job executes the same command and
retains its public receipts.

The [workspace isolation observation](./workspace-isolation-source-observation.json)
records 22 actual invocations across two overlapping signed/enforced nodes owned
by one unprivileged Linux account. Distinct guest results, publications,
credentials, activation catalogs and generated secret files remained separate.
Each node denied the other workspace's credentials and secret reference. A
stopped and restarted workspace left the other node callable with its deployment
unchanged. Excluded author credentials never entered the source snapshots.

An actual completed activation was observed before and after its configured
three-second receipt retention expired. Recovery retained the original intent
and rejected a new mutation; the other workspace remained usable. Neither the
clock nor the receipt store was edited. Both nodes stopped cleanly with all live
provider/secret counters zero. The private workspaces and expired intent remain
available for inspection. The first run's incorrect newline in expected public
result bytes is preserved alongside the successful run.

Run `tools/dev_workspace_isolation_probe.py` with the same payload, source-node
and new-output arguments for this maintained CI check. It does not qualify
separate WSL users, owned purge or final authenticated clean-host installation.

The first combined CI run correctly rejected GitHub's inherited runner-home ACLs
before starting the isolation node. Installed-helper probes now reuse the existing
dedicated-account CI wrapper: it creates a private passwd home on the ephemeral
runner, leaves runner ACLs and installer policy unchanged, and exports only bounded
public receipts. Actual local runs through this wrapper passed both isolation and
watch; their private accounts remain retained with the disposable test container.

The [watch failure observation](./watch-failure-source-observation.json) records
the real controller handling three committed revisions. An invocation selected
on A remained running after B committed and returned a cancellation receipt
pinned to A; subsequent calls returned B with fresh guest state. B's exact build
was prepared before A started and revalidated from the source/tool/recipe cache
when the edit was observed. Compiler failure and malformed component output left
B callable and correctly identified it as the current deployment.

Two rapid edits during a deliberately slow owned recipe cancelled and reaped
only that original build and its child. The watcher deployed the latest edit,
then exposed an intentionally failed focused test while keeping that new
deployment live. Four retained build attempts stayed within the declared bound.
An explicit public-API revocation of A followed by one generation-checked restore
attempt returned `permission-denied`; the current deployment remained callable.
The node and recipe/Invoke processes were reaped. Private state and the first
run's incorrect expectation of a shortened cleanup reason remain retained.

The [fuel regression observation](./watch-fuel-regression-observation.json)
retains a later CI failure: the CPU-spinning A invocation consumed its full
10 billion fuel allowance in 19 seconds, before B committed. The fixture now
uses the supported component executor's cooperative async yield. Its complete
189-second source run observed A running on both sides of B's commit, then
cancelled A once with its original revision and 25,397,392 fuel consumed. Fuel,
wall-time and process limits are unchanged. The intermediate bare-pending-future
experiment trapped and remains recorded as a failed attempt.

The Rust CI job runs `tools/dev_watch_fixture_probe.py` with the same payload,
source-node and new-output arguments. These are source observations through the
direct Linux helper, with explicitly trusted local admission. They still require
repetition through final authenticated Windows/WSL packages and do not claim a
clean host, VM-disconnect recovery or rendered newcomer/editor review.

| Child | Current acceptance handoff |
| --- | --- |
| #560 | [Packaged schedule passed](packaged-platform-handoff.md): independent policy, authenticated bundles, actual direct/SSH lifecycle, rejection and recovery. |
| #561 | [Packaged WSL schedule passed](packaged-platform-handoff.md): authenticated image, isolated users, exact source bytes, actual owned-VM interruption, retained restart and purge. |
| #563 | Closed: all six authenticated owner recipes, node/native results and applicable capability denial/recovery passed. |
| #564 | Closed: packaged watch ordering, compiler failure, in-flight revision, cancellation, revoked restore and expired/UNKNOWN/concurrent-actor recovery passed. |
| #565 | [Packaged and source campaigns passed](packaged-platform-handoff.md): all six node templates, closed failures, real capability fixtures and isolated cleanup, with execution classes kept separate. |
| #566 | [Native Windows scope passed](native-windows-qualification.md): authenticated distribution, six languages, closed failures/clock, unsupported-required rejection and exact-source provider/node comparisons. |
| #568 | Devcontainer passed; finish final editor-fix candidate qualification and the clean-machine newcomer walkthrough. |
| #569 | Five packaged entries passed; finish the editor/newcomer evidence and reviewed aggregate for the selected final identities. |

`latent.dev.qualification.v1` rejects missing entries, mocks, cross-builds,
wrong environments, unsupported required scenarios, incomplete language coverage
and unconfirmed cleanup. It intentionally cannot turn the checks above into epic
completion. No public release, tag, support expansion or Phase 3 closure is
authorized by this work.

## Contributor verification

```powershell
python -m unittest tools.tests.test_dev_workflow tools.tests.test_dev_contracts tools.tests.test_dev_build_cache tools.tests.test_dev_watch tools.tests.test_dev_tools tools.tests.test_dev_tool_install tools.tests.test_dev_node_policies tools.tests.test_dev_http_fixture tools.tests.test_dev_blob_fixture tools.tests.test_dev_secret_fixture tools.tests.test_dev_metric_fixture tools.tests.test_dev_local_service_fixture tools.tests.test_dev_event_fixture tools.tests.test_dev_fixture_cleanup tools.tests.test_build_process
python tools/latent_dev.py dev doctor
python -m pip install --require-hashes -r tools/dev-frontend-windows.lock
python tools/build_dev_frontend.py --output target/dev-candidate
```

Use Python 3.13.5 for the reproducible Windows packaging environment. The
`--output` directory must be new. `build.json` records source dirtiness, actual
frontend/helper/lock digests and the precise smoke-test boundary. It never
asserts authenticated publication or managed-node qualification.
