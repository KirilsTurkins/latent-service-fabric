# Windows developer workflow qualification

The Windows developer workflow is qualified for the scoped developer workloads
at source `8b6dc33fc64fee1e04519c4c0ab6fb55632d58a4`, using independently approved,
authenticated nonpublishing candidates. [Run 36236145313](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36236145313)
supplies all five required packaged entries. The
[schema-validated report](windows-qualification-report.json) and
[exact artifact and receipt inventory](windows-qualification-evidence.json)
retain source, policy, frontend, runtime, helper, compiler, host, guest and cleanup
identities. These complete #559's scoped qualification; they do not approve a
public release or close the broader Phase 3 gates.

## Supported matrix

The Windows host reported `10.0.26100.33438` on AMD64, WSL 2.7.14 and
Ubuntu 24.04.5 with kernel `6.18.33.2-microsoft-standard-WSL2`. The direct,
SSH and devcontainer environments used Ubuntu 24.04.5 x86-64 with kernel
`6.17.0-1022-azure`; the generated container used Dev Container CLI 0.89.0.
The Windows/native schedule took 2,465.009 seconds, dedicated recovery
377.481 seconds, direct/SSH 2,570.441 seconds and devcontainer 1,767.815 seconds.

| Entry | Qualified path | Boundary |
| --- | --- | --- |
| Windows x86-64 / WSL2 | Native frontend, owned WSL distro, private Linux node users and guest compilers; all six languages | Linux executes the node and builds components; no Windows production runtime |
| Native Windows x86-64 | The exported components run after the owned WSL distro is purged | Controlled portable subset; no Linux admission/isolation or running-node cancellation claim |
| Direct Linux x86-64 | Installed frontend and helper on the qualified Ubuntu host | Explicit owned workspace and development security profile |
| Explicit SSH to Linux x86-64 | Pinned host key and helper, separate unprivileged account | No ambient agent forwarding or implicit remote target |
| Optional devcontainer | Generated terminal client with a separately selected Linux SSH peer | No privileged container, host-root/socket mount or default container requirement |

Mac, Lima, ARM64, unqualified guest distributions and production Windows nodes
are excluded. The selected node profile is `local-experimental-v1`; application
fixtures record their signed or trusted-local admission explicitly. This does
not certify `external-capsule-v1`, hostile multitenancy, production performance
or a general host/compiler RSS limit. Required unsupported portable cases fail
before execution; they never substitute for a Linux node result.

## Executed acceptance

| Requirement | Evidence |
| --- | --- |
| Authentic installation and offline reuse | Approved exact-source policies and all ten verified candidate bundles; explicit online artifact acquisition followed by offline authentication, including genuinely disconnected Linux application execution |
| Create, build, deploy, invoke and test | Maintained Rust, C, TypeScript, Go, Java and C# recipes; actual node results and same-component native comparisons; no LSF checkout or runtime compiler used by the application |
| Edit, watch and failure recovery | Revision replacement, in-flight old-revision retention, latest-edit coalescing, compiler/malformed-input last-good behavior, bounded build retention, visible focused-test failure and revoked-restore rejection |
| Lost responses and authority | Original publication/deployment/Invoke identities reconciled without effect replay; real expired UNKNOWN intent retained and concurrent deployment generation protected |
| Retention and lifecycle | Down retains data, restart invokes the retained deployment, owned WSL termination/resume reports the new guest identity and unclean prior shutdown, explicit purge preserves authored sources and other workspaces |
| Isolation and cleanup | Distinct Linux users, private credentials, excluded source secrets, cross-home/credential denial, another workspace remaining callable, reaped owned node/compiler/native processes |
| Failures and fixtures | Real trap, fuel, memory, deadline, cancellation, post-failure success and scoped clock/provider cases; closed fixture substitutions are identified in the receipts |

The actual platform lifecycle was owned WSL terminate/resume. The physical
Windows host was not suspended. The clean-host Windows runner's SDKs and Python
were absent from the application's PATH; Python ran only the separate conductor.
Linux application containers recorded absent host compilers and a disconnected
network. OS/package prerequisites were provisioned before that disconnected run.
The native cancellation case is cancellation before start; running cancellation
is separately established by the Linux node.

The existing manual qualification lane retains command, time, output, process,
cache and log bounds. The eleven source-built capability/lifecycle campaigns at
the same candidate commit are recorded separately from installed-package proof.
The NATS fixture is an authenticated bounded protocol peer, not a live-broker
certification. No new always-on browser/runtime pipeline was introduced.

## Newcomer and editor review

The packaged Windows run executes the reviewed greeting walkthrough: three typed
node cases, Hello-to-Welcome source/test edit, live watch replacement, deliberate
compiler failure while Welcome stays callable, correctly mapped source diagnostics,
restored focused test, explicit recovery, retained restart, down and owned purge.
Credentials are generated by the controller and never authored by the newcomer.
The guide and conductor hashes are retained with the actual package identities.

The [editor review](editor-task-integration.md) separately records actual generated
VS Code tasks, live diagnostics, clearing after a fix, cancellation and untrusted
workspace behavior. Its source frontend is not relabeled an authenticated package.
The editor implementation is unchanged by the later supervisor shutdown correction.
The [guide validation](application-guide-validation.md) retains the native Rust
business-logic test and rendered desktop/mobile guide checks using the existing
documentation jobs. That native test's Rust source digest is unchanged in the
final approved greeting bundle (`sha256:c1649b27484ef80cc2f51eca819af450bbb23672b1624f2439c8eff4cb62e2c9`).
The clean-host packaged walkthrough is automated and reviewed;
it does not claim an interactive human editor session on the hosted runner.

## Failure history and handoff

Original failures remain linked from [packaged qualification](packaged-developer-qualification.md)
and in the final report. In particular, run 36227800146's successful Linux/SSH/
devcontainer results did not erase its failed Windows shutdown. #603 corrected
the reproduced socket-reset path without retrying a request or assuming cleanup.
Replacement candidate results establish the final supported bytes.

This handoff supplies developer-platform evidence to #201/#240, distribution #308
and documentation #345/#237. A later public release still needs independent release
approval and qualification of its exact bytes. Broader production/security and
Phase 3 acceptance remain with their existing owners.
