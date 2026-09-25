# Packaged developer qualification

The [five-platform handoff](packaged-platform-handoff.md) records the complete
passing packaged schedule and dedicated Windows recovery campaign at approved
source `0cb5cf08`. It retains the remaining editor/newcomer and final review gates.

The [native Windows qualification](native-windows-qualification.md) records the
completed Windows/WSL and native schedule at approved source `0cb5cf08`, including
all six languages and the closed failure/clock differential. It supplies #566's
evidence while the remaining epic gates stay separately tracked.

The `Packaged developer qualification` workflow stages a small test conductor on
a fresh Windows x86-64 runner and a disconnected Linux OS container. The Windows application runs the authenticated native
frontend, WSL image, native Linux runtime and six language tool bundles. The
Windows job does not check out LSF or compile its runtime. The runner image has
preinstalled development tools; the frontend receives a restricted environment
whose PATH contains only Windows System32. Python runs the separate conductor.

This lane is manual. Its inputs are the complete, independently approved
developer/runtime publisher policies and their successful exact-source candidate
workflow run IDs. A platform selector permits a fresh Windows or Linux attempt
without repeating the other platform; skipped entries never count as qualified.
The maintainer must approve those policies before selecting
`policy_approved`. The conductor does not grant publishing authority. Its support
job rejects unsuccessful, unfinished, wrong-workflow or wrong-source candidate
runs. Candidate signatures and inventories are still verified before use.

The support artifact contains only the qualification scripts and independent
verification inputs. GitHub CLI 2.96.0 archives are pinned to the digests recorded
by the official [GitHub CLI release](https://github.com/cli/cli/releases/tag/v2.96.0).
The separately provisioned Sigstore trusted root is retained in
`packaging/dev/qualification-trusted-root.jsonl`, SHA-256
`65ca537f6ed8a47fd0e560c421baa1f6c1efb8b25fc200d8c5c02c0e92eb2b9c`.
It is the independent root used for the earlier approved candidate verification;
it is not selected from a candidate archive. Changing this input requires review.

The current schedule verifies the frontend before executing it, rejects a wrong
target and a tampered archive, imports only its owned WSL image, and creates
separate Linux users for the six language-owned greeting projects. It installs
the selected runtime and compiler tools, rejects an untrusted build recipe,
builds real components, starts signed/enforced test nodes, deploys and executes
the common success and declared-error cases. A retained Rust workspace remains
callable while subsequent workspaces stop and purge. Actual guest observations
check private credential permissions, rejection of the other workspace's home,
and exclusion of an authored `.env` file from synchronized snapshots. Restart
uses the retained deployment without a new publication. Purge preserves every
recorded authored file by digest.

Before each backend's initial Rust build, the installed frontend rejects an
unknown descriptor field, incompatible ABI and a traversal input root. After
explicit recipe trust it rejects two distinct Unicode-equivalent source names
and an actual hard-linked source file; Unix clients also exercise an actual
symbolic link. The conductor restores the exact descriptor bytes and removes
only its individually created path fixtures before the valid build proceeds.
The initial Rust source uses CRLF line endings. After the actual build, a bounded
read-only guest observation must match its host digest and retain those line
endings exactly; normalized or stale source cannot satisfy the transfer check.

For each backend's first Rust deployment, a separately staged and digest-checked conductor
discards one actual successful release response, then one deployment response.
It imports the authenticated installed helper and calls the actual operator CLI.
The packaged `recover` command must resolve each original journal identity
exactly once. The same schedule discards one successful invocation response and
requires its original terminal receipt. It never repeats the accepted effect.
The observer reads only journal identities and kinds, not credential contents.

After the other five workspaces are stopped and purged, the conductor verifies
the retained distribution's Windows registry identity, terminates only that
owned distribution, and joins its original foreground controller. Resuming it
must observe a changed guest namespace, confirmed process reaping and an
unclean shutdown. Restart must retain the existing deployment and execute it.
The schedule never shuts down WSL globally.

An additional provider-free Rust workspace runs the packaged watch command.
It explicitly selects the documented `trusted-local` admission mode before its
first deployment. The greeting and provider-fixture workspaces retain their
separately selected signed admission for their entire lifetimes. The short-lived
signing fixture is bound to one build and cannot authorize an edited component;
watch never changes that policy or silently signs new source. The conductor
uses the same authored numeric revisions as the source qualification. It warms
B's exact build before starting A, observes a real A invocation running, edits
to B and requires the watch controller to revalidate the cached B build. The
original invocation must remain running across the committed switch and retain
A's publication when explicitly cancelled once. New focused tests and invocations
must select B.

Compiler errors and malformed output must leave B callable. A slow recipe
exposes its owned child identity; rapid edits must cancel and reap that child,
then deploy only the latest revision. A deliberately wrong test expectation
must produce a visible focused failure while that latest revision remains live.
The conductor then revokes A and attempts one preconditioned restore, requiring
known rejection and unchanged current deployment. Retained restart must invoke
the latest revision again. It leaves the deliberate author edits intact and
purges only its own workspace. Build retention and deployment order are checked.

The small guest observers verify the installed helper's digest and protected
path before importing it. Reviewed invocation and revocation probes have
separate source hashes bound to the conductor selection; their imports resolve
to that installed helper. The host controller drives the public packaged watch
command, and original invocation/revocation intents prevent automatic replay.
These extended cases require a fresh installed-package result before they count
as completed qualification.

The conductor exports only the three public build files in bounded chunks from
their exact owned build attempt, rechecking each complete file's recorded
digest. After all nodes and the owned WSL distribution are purged, it executes
the same six greeting applications with the native Windows portable host. It
compares case identities, outcomes and payload digests with the Linux-node
results. This export is an explicitly labeled read-only qualification observer;
it does not compile, deploy or invoke an application in place of the frontend.

Two further Rust workspaces on each node backend use the same authored failure and clock cases as
the maintained source probes. Their stimulus writers use only the standard
library and produce byte-identical source, WIT, fixture and scenario files.
The packaged frontend builds and signs each project in its own node and, on WSL,
its own Linux user. The failure schedule covers cold/warm fresh state, declared error, trap,
fuel and memory exhaustion, deadline, actual running cancellation, recovery
after each failure, and retained restart. The explicit zero-clock fixture
covers cold/warm readings, denied capability and fresh recovery.

After WSL purge, the native Windows host executes the same exported component
bytes and shared scenarios, including the documented node/native resource-code
differences. A required live-node cancellation scenario must reject the portable
selection before any native invocation. A separate native cancellation-before-
start case exercises the portable host's declared support; it is never counted
as running-node cancellation. These additional workspaces are purged separately
and their original authored sources remain intact.

A separate manual Linux lane uses a fresh Ubuntu 24.04 OS container with the
same pinned OS/Python inputs as the managed image, plus pinned OpenSSH packages.
It checks that host compilers and SDKs are absent before installing any guest
tools. Independently authenticated frontend/helper files are copied into the
image without executing them during image construction. The running schedule
has Docker network mode `none`; all runtime/tool inputs are preprovisioned and
the explicit SSH connection uses loopback, a dedicated second Linux account,
and a newly generated host key provisioned through the conductor. Neither its
management RPC listener nor SSH is published on the Docker host.

That lane exercises one maintained Rust project through direct Linux and SSH,
including real build/deploy/test, lost-response recovery, retained restart,
repeated stop/purge and source preservation. Both execute watch A/B and compiler failure.
The two initial nodes overlap under distinct Unix users with the same service
name. Each user must be denied access to the other home, and the direct node's
original deployment must remain callable after the SSH workspace is purged.
Each Linux frontend, including the devcontainer, rejects wrong-target and
tampered archives and a mismatched publisher identity before admitting a bundle.
SSH rejects a wrong host key and helper digest, then checks that a concurrent
start cannot replace or stop the existing node. The Windows/WSL lane owns the
six-language matrix. This Linux OS-container observation is distinct from the
Windows WSL2 host and the opt-in editor devcontainer path.

The Linux job then generates the opt-in devcontainer through the authenticated
frontend and starts it with the independently pinned Dev Container CLI 0.89.0
and host Node.js 24.19.0. It retains the generated configuration and separately
records two explicit qualification additions: the disconnected SSH peer's
network namespace and a read-only pinned Python mount for the conductor. The
application continues to use its own embedded Python; guest compilers and the
node run only on the separate SSH peer. No host directory containing credentials,
Docker socket, root mount, port publication or agent forwarding is supplied.

The container must run as the declared UID 10001 with all capabilities dropped,
no new privileges, 2 GiB memory and two CPUs. The peer provisions fresh SSH keys
only in the generated private home volume and checks the helper's digest before
serving requests. The schedule creates a real Rust project in the source mount,
builds/deploys/tests and recovers original lost-response identities over SSH, generates the same editor process tasks, runs
watch and compiler failure, restarts retained state and explicitly purges the
node workspace. Both exact containers are stopped and inspected; authored
source and the private home volume remain until runner teardown. The extra
client schedule is bounded to 2,400 seconds and its peer to 4,800 seconds.
The peer exposes two explicitly selected SSH users. The client runs a second
installed Rust node while the first remains ready, verifies mutual home-directory
denial and distinct node identities, and invokes the first node's original
deployment after the companion stops and is purged. The five-workspace client
schedule preserves the individual application/build deadlines. The Linux job's
160-minute ceiling also includes its separate direct/SSH campaign and OS image
builds; it is an emergency bound, not a performance claim.
The [two-user OS setup observation](devcontainer-isolation-os-observation.json)
confirms both actual SSH logins and mutual home denial using an unexecuted
helper placeholder. It records setup only; the installed-node assertions still
require the independently approved candidate campaign.
This tests the terminal container path on Linux; it is separate from a rendered
editor walkthrough and from the earlier Windows Docker Desktop source receipt.

The `windows-recovery` selection runs a separate installed-package campaign in
a fresh owned WSL distribution. Its two Rust workspaces have distinct Linux
users and node identities. One configures the node's supported three-second
terminal retention before its first start, discards one real successful Invoke
response, observes its original terminal receipt, and waits for actual expiry.
The other rejects wrong-token and wrong-tenant requests and observes a separate
actor's committed deployment. The public frontend must preserve that actor's
generation and retain the original UNKNOWN operation intent. Both unresolved
workspaces must reject new mutations without replay. While the first workspace
is unresolved, the second must still invoke its original deployment.

The expiry observer verifies the installed helper's digest before importing it
and uses the separately hashed response-loss conductor. It does not change the
host clock or edit receipt storage. Recovery still exits with an uncertain
result; a successful qualification receipt means the expected uncertainty and
no-replay assertions passed. The public shutdown reaps both owned nodes, then
only the recorded owned distribution is stopped and its registration checked.
Private original intents remain until runner teardown. The `all` selection
includes this campaign after the ordinary Windows/WSL and native schedule.
Ordinary lost-response recovery additionally checks blocked new mutations and
a second public recovery with no journal change. These assertions require a
completed installed-package run before being counted as qualification evidence.

Each command has bounded output and a deadline. The schedule admits at most
360 completed commands per backend, reserving the last 24 for status, recovery
and cleanup, 4 MiB stdout and 256 KiB stderr per command, 1,800 seconds
per command, and 7,200 seconds for the schedule. A public receipt is at most
16 MiB. Optional stdin is bounded to 2 MiB and never copied into command
arguments or receipts. Public component exports are at most 16 MiB, with
capsule and contract documents at most 1 MiB each. Only the public observation
and selected input identities are uploaded;
private workspace credentials and uncertain intent are not artifact inputs.
Failures stop the schedule without replaying a mutation or invocation. Cleanup
uses the recorded public workspace API, and an unconfirmed remote termination
remains explicitly unconfirmed. Private failed state remains until the ephemeral
runner is discarded.
When an installation loses its backend response, a separate read-only observer
may retain input-file sizes and completion markers from that owned guest user.
It reads no credential contents and never changes the original uncertain result
or repeats the installation. Failed startup events and controller exit status
are retained separately from a subsequent confirmed node-reaping result.

The Linux container has an 8 GiB memory limit, two CPUs and 512 processes.
Its eight independently installed node workspaces share a 3,600-second outer
schedule after a 1,200-second OS image build allowance; its internal emergency
ceiling is 7,200 seconds. At most 384 host commands poll and revalidate the exact
container identity, with each inspection bounded to 15 seconds. Application
command and build deadlines are unchanged. On failure,
the conductor verifies the original container identity, attempts its bounded
stop, and inspects the result. Private state remains until runner teardown;
an unconfirmed container stop is reported as unconfirmed.

The receipt deliberately keeps `qualificationComplete: false` even when an
individual schedule passes. The full watch, transport-loss, security/failure,
portable subset, devcontainer and rendered newcomer/editor requirements still
need their actual packaged evidence before issue #569 or epic #559 can close.
Completed stages and failed attempts are recorded separately below. The successful
[hosted WSL preflight](hosted-wsl-preflight-observation.json) proves that the
Windows runner can execute WSL2; it does not supply those missing receipts.
The [final source campaign](final-source-campaign-observation.json) records the
separate successful isolation, watch and recovery source probes and their failed
predecessors. Those observations likewise do not replace installed-candidate runs.
The [candidate source campaign](candidate-source-campaign-observation.json)
retains 34 passing probe, comparison and tutorial receipt identities from the
complete candidate build at `f5d556d3`. It includes the corrected actual watch
campaign, all provider cases, and native Windows/Linux comparisons, with their
cleanup dispositions and original artifact references.

The [first installed-candidate attempt](packaged-candidate-attempt-observation.json)
retains the actual failed run of the independently approved f5 candidates.
Windows authenticated and installed the frontend, owned WSL image, runtime and
Rust tools; built and executed success/declared-error cases; and recovered the
original release, deployment and invocation identities. The original conductor
then tried to edit that signed fixture, which correctly rejected the new build.
Its owned node was reaped and private failed state retained. The corrected
schedule selects a distinct provider-free watch workspace from the outset.
The same attempt's disconnected Linux lane authenticated and installed its
inputs, exercised path/trust rejections, and reached the unchanged 900-second
build deadline. Its exact container stopped. This failure is retained for
diagnosis and is not counted as a passing Linux build or complete qualification.

The [second Windows attempt](packaged-candidate-c-install-attempt-observation.json)
again passed the signed Rust build, tests and original operation recovery. With
that node still running, it created a distinct C user and installed its runtime,
then lost the backend connection during C tool installation after 36.49 seconds.
The frontend preserved an uncertain outcome; the operation was not replayed.
The original Rust node stopped cleanly. The C installation's private state
remained on the disposable runner until teardown. The cause is under
investigation, and this receipt does not count as a successful C installation.

A [local Windows diagnostic](packaged-c-install-local-observation.json) subsequently
installed the unchanged approved C tools while its signed Rust node remained
ready, then reaped the Rust node with a clean shutdown. This attempt did not
reproduce the hosted transport loss; it is not a clean-host or complete language
qualification. Its first local setup hit the Windows path-length limit in a
deeply nested custom controller directory. A fresh, shorter state path succeeded
without changing the host's global path setting or reusing the partial cache.

The [monitor-fix candidate attempt](packaged-monitor-candidate-attempt-observation.json)
used all ten independently approved `0cb5cf08` bundles. Every language passed
its signed WSL node cases and its Windows portable cases, with the owned WSL
distribution removed before native execution. The direct Linux and explicit
SSH schedules both passed, including simultaneous workspace isolation, retained
restart, basic watch, closed-profile failures and exact-owner cleanup.

That run remained incomplete in two later conductor stages. The Windows
closed-profile comparison incorrectly compared node-only deployment, evidence
and package-source metadata with the portable record. All three exported
artifact hashes and every completed typed result matched. The comparison now
requires exactly the shared component, capsule and contracts, while rejecting
any missing or changed artifact. Clock parity and the remaining native
cancellation checks were not reached in that attempt.

The devcontainer CLI rejected the conductor's `qualification.json` filename
before creating its client container; the owned SSH peer stopped. The reviewed
CLI reproduced that rejection locally. The conductor now uses the accepted
`.devcontainer.json` name beside the generated configuration, preserving relative
Dockerfile paths, and retains bounded structured CLI failures. Configuration
parsing succeeded locally; a fresh installed devcontainer campaign is still
required. Neither correction replaces the original failed receipt.

The seventeen fast conductor regressions exercise archive traversal/alias/device/link
rejection, modified member bytes, output flooding, finite process deadlines and
bounded stdin with receipt redaction, plus the actual Windows DACL of the newly
created conductor directory. A required unsupported-case report must retain its
non-success exit and cannot be accepted by an ordinary passing-test call. They also
require the correct native entrypoint and private executable modes on Linux.
The exact staged conductor inventory must import in an isolated interpreter
outside the checkout, without loading an LSF source package.
They run on Windows and Linux and do not count as installed-product evidence.
The [OS setup observation](qualification-os-smoke-observation.json) additionally
records an actual disconnected-container SSH handshake between UIDs 23001 and
23002 with host compilers absent. It uses a harmless helper placeholder and runs
no LSF candidate, so it validates provisioning only.
The [terminal devcontainer OS observation](terminal-devcontainer-os-observation.json)
also records the actual pinned CLI starting the generated unprivileged image,
the read-only conductor interpreter running there, and a separate SSH handshake
from UID 10001 to UID 23002. Its application/helper placeholders were never
executed. The first server-only smoke lacked the client account; that failed
attempt and both successful cleanup results are retained.
