# Core learning-path validation

This is the implementation and evidence handoff for
[#357](https://github.com/KirilsTurkins/latent-service-fabric/issues/357), not
acceptance of the complete documentation launch or Phase 3. Current prose stays
in `docs/`; examples stay with their existing source owners. The existing
[operator guide handoff](operator-guide-acceptance.md) retains its historical
source/evidence distinctions and is not relabelled by this change.

## Coverage and ownership

| Existing outcome | Learning path | Execution owner / boundary |
| --- | --- | --- |
| `evaluate-boundary` | [Choose a path](../start/index.md) | Resource/profile references and native installer status, not an unqualified performance claim. |
| `install-auth-readiness` | [First node](../start/first-node.md), [native installation](../installation.md) | New finite source-based runner reusing the existing process owner; native bundle/VM and publisher verification remain the installer owner's separate work. |
| `contributor-checks` | [Operate and contribute](../how-to/operate-and-contribute.md) | Existing docs/website/CI classifier and selected product suites. |
| `author-capsule` | [Author a capsule](../learn/author-your-first-capsule.md) | Existing Rust echo source, WIT, builder and registry; no second copied program. |
| `package-sign-publish` | [Author a capsule](../learn/author-your-first-capsule.md), [delivery](../learn/deliver-and-recover-a-capsule.md) | Existing package/operator/registry owners; explicit synthetic signatures versus actual observed-build evidence. |
| `rollout-uncertain-recovery` | [Delivery/recovery](../learn/deliver-and-recover-a-capsule.md), [operations](../how-to/operate-and-contribute.md) | Existing canary/publication/offline workflows and exact retained operation identities. |

The [coverage inventory](../../website/content/coverage.json) adds guide entries
to these six existing rows. It does not change the finite required outcome set,
other guide owners, historical evidence or review status. All six human reviews
remain pending until the reviewer checks the actual rendered paths at an exact
commit. Passing synthetic tests cannot supply an `execution-receipt` for LSF.

## First-node runner contract

[run_first_node_guide.py](../../tools/run_first_node_guide.py) accepts explicit
prebuilt CLI/node paths, the echo builder's five generated inputs and a full
caller-supplied build commit. It never compiles, downloads, executes prose,
adopts an installed service, relaxes an existing catalog profile or retries a
mutation. [first_node_guide.py](../../tools/first_node_guide.py) supplies the small
scenario, using the maintained [operator process owner](../../tools/phase2_operator_process.py)
and its cancellation/unreaped-process-group cleanup.

Each run has a 180-second useful-work bound, bounded capture, bounded input and
receipt sizes, private temporary directories and freshly generated file-only
credentials. It copies only the named generated public artifacts, checks component
and deployment identities, validates before startup, waits for authenticated
readiness, invokes under known identities, and checks retained deployment after
restart. Wrong credentials, invalid configuration/capsule, declared error and a
stopped-node read must all exhibit their expected failure classes. Cleanup must
finish before `passed:true`; source inputs and artifact/collector hashes are
rechecked before the temporary tree is removed. An error yields a fixed failure
receipt, not raw child output or a fabricated successful observation.

The source commit remains explicitly **caller-supplied**. Hashes bind the actual
files exercised, but do not prove they were built from the asserted commit.
Retain the clean build's own source/toolchain record alongside the receipt.
Neither synthetic test executables nor a renamed binary establish node identity.

## Reproduce the focused and native checks

From the repository root, under the pinned Python toolchain:

```bash
python3 -m unittest tools.tests.test_first_node_guide tools.tests.test_core_guides
python3 tools/validate_docs.py
git diff --check
```

The tests are automatically discoverable by the existing repository Python test
owner; no issue-numbered workflow is introduced. The subprocess fixtures are
labelled synthetic: they check sequencing, bounded ownership, refusal/redaction
and cleanup, not the RPC protocol or LSF guest execution. Guide tests also check
coverage mapping, source-backed snippet usage and the Bash/Python command syntax.

For **real execution**, use the build and exact runner command in
[First node](../start/first-node.md). After a contract build already produced the
same native binaries and generated echo inputs, that runner can be invoked
without rebuilding or generating another protocol fixture. Keep its receipt
separate from the existing [CLI integration tests](../../apps/latent/tests/standalone_cli.rs).
The latter own trap/deadline/cancellation and broader transport tests that the echo
walkthrough does not claim to cover. The existing delivery guide owns its
registry/publication/canary workflows and independently pinned historical source.

From `website/`, under the pinned website Node/npm toolchain:

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npm run build
npm run build:root
npm run browser:install
npm run test:build
```

These production checks must validate the new Start/first-node/authoring links,
rendered snippet, explicit version/profile notices and both base paths. The site
build only reads reviewed content and never runs the first-node scenario.
The added sidebar regression uses the real source index, not a standalone list
that can drift away from published routes.

## Recorded check and acceptance limits

The real source-based walkthrough passes on Linux x86-64 on 2026-09-20.
The [unaltered native receipt](../evidence/phase3-357-first-node.json) has SHA-256
`685e99f8a14db878c2f3f29f7c15b21195cee78e5f168b9ba30b70277c2f53f4`.
The runner and freshly built echo inputs come from guide source
`04fbd3159d2effe5579662db87334cb7778de05e`; the prebuilt CLI/node are the separately
qualified `3e4c4692e31ac6a62bc615f6435e417bb769a855` binaries, mounted read-only
from their owner's artifact volume. The receipt binds those exact binaries and
all six collector modules by SHA-256 instead of claiming they were rebuilt from
the guide commit. The echo component digest is
`sha256:5ed2ad25572df7b223de80feadfa350b13bdca2cc1d41b31e59df4f03a8f7dd2`.

The execution uses 19 CLI processes, two successful invocations, one declared
error, five explicit failure checks and three retained activation identities.
The deployment survives restart and is invoked without republishing. Both node
processes report clean, reaped shutdown and the private temporary outputs are
removed. The owned `lsf-phase3-core-guides` container uses one CPU, 3 GiB and
256 PIDs. This establishes the source evaluation walkthrough, not installation
from a signed native bundle or a reproducible guest build.

The authoring base is development
`320f56a7ddaabd733433ffe839442939cfcbaeed`. Local focused tests run with Linux
Python 3.13.5 against byte-verified copies of the unchanged process-owner modules.
The retained local output distinguishes synthetic subprocess execution from
native LSF. No historical receipt, release artifact, guest implementation or
product resource budget is changed by this guide work.

The original authoring environment had no built LSF artifacts and could not resolve the
GitHub/npm hosts needed to obtain the full repository/dependency graph. The new
real-node runner was therefore initially unverified; the later execution above
supplies that evidence. Complete pinned website builds/browser checks, the
native installed bundle and the human newcomer walkthrough remain separate
acceptance checks. The original Node 22 host is not the pinned website Node
24.19.0 qualification.

Before accepting #357, retain a successful real runner receipt with the matching
build source/toolchain/artifact hashes, recheck changed instructions against the
applicable delivery/native workflows, then have a maintainer walk the rendered
paths. Record the reviewer, source, expected/failure observations and cleanup.
Keep the coverage reviews pending until that evidence exists; do not close #357,
#237 or #345 merely because the pages and runner are present. A failing,
interrupted, skipped or unexecuted check remains visible as such.
