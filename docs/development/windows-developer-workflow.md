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
  authenticated node readiness.
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
- `dev connect` selects a preprovisioned direct Linux or explicit SSH backend.
  SSH requires a selected identity file and known-hosts file, strict host-key
  checking and no agent forwarding, proxy command or connection multiplexing.
- `dev trust` records the exact project recipe/tool/ABI selection outside the
  repository. Recipe changes invalidate trust. `dev init` only materializes
  authenticated language-owned templates into a new destination.
- `dev install` delegates to the maintained [native installer](../../packaging/linux/INSTALL.md).
  `up` runs its real configuration and authenticated readiness checks. Profile
  changes and runtime upgrades are never automatic.
- Build, immutable source transfer, deployment and watch use bounded resources.
  A persisted mutation intent contains the original operation identity and
  observed preconditions. Recovery looks up that identity and does not replay
  an Invoke, publication or deployment. Unknown/expired receipts remain unknown.
- `down` addresses the workspace supervisor and retains data. `purge` requires
  the exact workspace name and delegates runtime removal to the existing
  installation owner before removing owned snapshots.

These implementations still need the packaged integration runs below. An
adapter unit test is not a WSL provisioning receipt.

## Project, transfer and test boundaries

`latent.dev.project.v1` is closed and versioned. It identifies the language
owner (#544–#549), immutable template revision, ABI, build host, pinned tools,
explicit input roots, exclusions, output paths and application scenarios.
It integrates supplied language artifacts; it does not ship parallel SDKs or
claim the pending language-owner PRs are delivered.

Source snapshots retain exact bytes, including CRLF. A second observation checks
the full selected tree before accepting a coherent snapshot. Absolute paths,
traversal, reparse points, symlinks, hardlinks, Windows device names, case and
Unicode aliases are rejected. `.git`, `.env`, `.ssh`, `.aws`, `.azure`, generated
output and dependency trees are excluded. Declared inputs are not a secret
scanner: authors must deliberately exclude any additional confidential files.

Initial bounds are eight workspaces, one active command/build per workspace,
2,048 source files, 16 MiB per source file, 64 MiB per source snapshot, four
retained snapshots, 256 KiB of supervisor logs, 32 retained operation receipts,
900 seconds per build and five additional seconds for command cleanup.
Two verified bundle directories bound the host cache. These are controller
limits, not a claim of hostile compiler or whole-process memory containment.

`latent.dev.scenarios.v1` keeps application inputs and results as exact bytes
and supports focused selections plus JUnit rendering. Tests must explicitly
choose `node` or `portable`; unsupported required checks fail coverage.
The current node runner requires an explicitly selected `test-` workspace.
The portable runtime and capability fixture set are still pending and cannot
count as passing node evidence.

## Executed evidence and remaining acceptance

The first native Windows build ran `dev doctor` outside the checkout with Python
removed from `PATH`. Its receipt is an unsigned contributor build, not an
authenticated candidate or a clean-host application workflow. Focused Windows
tests cover protected state, exact-byte snapshots, command ownership, transport
contracts and one-shot recovery. The maintained workflow repeats these checks on
Windows and Linux and builds the Windows executable separately.

The observed host is Windows 11 build 26200.9448, WSL 2.5.10 and kernel
6.6.87.2. Actual CPU and memory PSI files exist. The currently qualified native
runtime installer requires Ubuntu 24.04 and kernel 6.8 or newer; no kernel
version check, pressure observation or execution profile was weakened.

| Child | Remaining Windows acceptance |
| --- | --- |
| #560 | Independently approved exact-source developer policy; authenticated bundles; actual local/SSH lifecycle and failure receipts. |
| #561 | Verified WSL guest image with documented prerequisites; actual provisioning, workspace isolation, stop/restart and purge schedule. |
| #562 | Mac/native ARM64 requirements deferred by maintainer; no ARM64 support claim. |
| #563 | Integrate and execute all six merged language-owner recipes; authenticated template/tool bundles. |
| #564 | Actual A/B redeploy, compile/admission failure, concurrent generation and lost-response injection on a real node. |
| #565 | Complete provider fixtures and actual failure/cancellation/restart cases for all six languages. |
| #566 | Native portable host, minimum capability subset and real Linux differential execution. |
| #568 | Complete editor/devcontainer integration and exercised newcomer walkthrough. |
| #569 | Actual packaged Windows qualification and reviewed consolidated evidence. |

`latent.dev.qualification.v1` rejects missing entries, mocks, cross-builds,
wrong environments, unsupported required scenarios, incomplete language coverage
and unconfirmed cleanup. It intentionally cannot turn the checks above into epic
completion. No public release, tag, support expansion or Phase 3 closure is
authorized by this work.

## Contributor verification

```powershell
python -m unittest tools.tests.test_dev_workflow tools.tests.test_dev_contracts tools.tests.test_build_process
python tools/latent_dev.py dev doctor
python -m pip install --require-hashes -r tools/dev-frontend-windows.lock
python tools/build_dev_frontend.py --output target/dev-candidate
```

Use Python 3.13.5 for the reproducible Windows packaging environment. The
`--output` directory must be new. `build.json` records source dirtiness, actual
frontend/helper/lock digests and the precise smoke-test boundary. It never
asserts authenticated publication or managed-node qualification.
