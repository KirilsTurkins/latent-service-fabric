# Packaged developer qualification

The `Packaged developer qualification` workflow stages a small test conductor on
a fresh Windows x86-64 runner and a disconnected Linux OS container. The Windows application runs the authenticated native
frontend, WSL image, native Linux runtime and six language tool bundles. The
Windows job does not check out LSF or compile its runtime. The runner image has
preinstalled development tools; the frontend receives a restricted environment
whose PATH contains only Windows System32. Python runs the separate conductor.

This lane is manual. Its inputs are the complete, independently approved
developer/runtime publisher policies and their successful exact-source candidate
workflow run IDs. The maintainer must approve those policies before selecting
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

For the first Rust deployment, a separately staged and digest-checked conductor
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

The retained Rust workspace also runs the packaged watch command. The conductor
edits the greeting from A to B, waits for B's real deployment and focused test,
then introduces a compiler error and invokes the still-selected B publication.
It explicitly restores valid B source, reuses its checked build, and restarts
the retained B deployment. This author action is recorded separately from any
automatic rollback, which the controller does not perform.

The conductor exports only the three public build files in bounded chunks from
their exact owned build attempt, rechecking each complete file's recorded
digest. After all nodes and the owned WSL distribution are purged, it executes
the same six greeting applications with the native Windows portable host. It
compares case identities, outcomes and payload digests with the Linux-node
results. This export is an explicitly labeled read-only qualification observer;
it does not compile, deploy or invoke an application in place of the frontend.

Two further Rust workspaces use the same authored failure and clock cases as
the maintained source probes. Their stimulus writers use only the standard
library and produce byte-identical source, WIT, fixture and scenario files.
The packaged frontend builds and signs each project in its own WSL user and
node. The failure schedule covers cold/warm fresh state, declared error, trap,
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
including real build/deploy/test, retained restart, repeated stop/purge and
source preservation. Direct Linux also executes watch A/B and compiler failure.
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
builds/deploys/tests over SSH, generates the same editor process tasks, runs
watch and compiler failure, restarts retained state and explicitly purges the
node workspace. Both exact containers are stopped and inspected; authored
source and the private home volume remain until runner teardown. The extra
client schedule is bounded to 1,800 seconds and its peer to 3,600 seconds.
This tests the terminal container path on Linux; it is separate from a rendered
editor walkthrough and from the earlier Windows Docker Desktop source receipt.

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

The Linux container has an 8 GiB memory limit, two CPUs and 512 processes.
Its outer schedule wait is bounded to 1,800 seconds after a 1,200-second OS image
build allowance; its internal emergency ceiling is 7,200 seconds. On failure,
the conductor verifies the original container identity, attempts its bounded
stop, and inspects the result. Private state remains until runner teardown;
an unconfirmed container stop is reported as unconfirmed.

This is qualification scaffolding until a completed run is linked. Its receipt
deliberately keeps `qualificationComplete: false`: the full watch, transport-loss,
security/failure, full portable subset, direct Linux, SSH, devcontainer and rendered
newcomer/editor schedules still need their actual packaged evidence before
issue #569 or epic #559 can close. The successful
[hosted WSL preflight](hosted-wsl-preflight-observation.json) proves that the
Windows runner can execute WSL2; it does not supply those missing receipts.
The [final source campaign](final-source-campaign-observation.json) records the
separate successful isolation, watch and recovery source probes and their failed
predecessors. Those observations likewise do not replace installed-candidate runs.

The eleven fast conductor regressions exercise archive traversal/alias/device/link
rejection, modified member bytes, output flooding, finite process deadlines and
bounded stdin with receipt redaction, plus the actual Windows DACL of the newly
created conductor directory. A required unsupported-case report must retain its
non-success exit and cannot be accepted by an ordinary passing-test call. They also
require the correct native entrypoint and private executable modes on Linux.
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
