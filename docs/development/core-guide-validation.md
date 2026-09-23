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

The documented seven-target [provider embedding command](../evidence/provider-libraries-2026-09-21.json)
also passed 79 cases plus one isolated environment child execution at `061cad14`.
The [raw log](../evidence/provider-libraries-2026-09-21.log) and receipt retain
all selected case names and seven executable hashes. This includes local-call
authority and descendant cleanup, bounded randomness and custom metrics; it
leaves rendered human walkthrough review pending.

## Current integration and native installation

[CI 35818046307](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35818046307)
passed after the obsolete alpha API removals. The
[retained integration set](../evidence/phase3-integration-35818046307/README.md)
binds actual checkout `58965f399a116eb713dd4a5fc966f682167204f7` to the identical
tree of selected source `193d52c37635026de416feffd4a2dfd57d082451`. It supplies
current operator/publication/offline/security, six-client, provider, Angular,
static-site and bounded-resource receipts with their exact scope limits.
The coverage inventory links those observations alongside the earlier dedicated
guide runs below; it does not rewrite their original source identities.

Native installation has separate
[alpha.4 rehearsal evidence](../evidence/native-upgrade-35821200294/README.md):
both packaged-artifact VM profiles passed complete compatible-upgrade acceptance,
including actual reboot and retained invocation; the local profile also passed
rootless evaluation. Protected publication and all human reviews remain pending.

## First-node runner contract

The [HTTP/blob execution](../evidence/guide-management-2026-09-21.json) records
31 CLI commands, nine guest activations, four authorized HTTP requests and no
unexpected requests. Grant revocation denies subsequent execution; selected
revisions survive restart and both node processes report clean shutdown.
The [capability-policy execution](../evidence/guide-capability-policy-2026-09-21.json)
adds 15 real CLI calls for policy CRUD, replay and persisted revocation. It has
no guest invocations; the paired management receipt supplies that coverage.
Both collectors ran from `55ba1c30` with the separately identified runtime
binaries used by the first-node run. Neither receipt supplies human review.

The [21 September execution receipt](../evidence/first-node-guide-2026-09-21.json)
records 19 actual CLI commands: two successful invocations, a declared error,
invalid configuration/capsule, wrong credentials, a stopped-node read and
retained deployment after restart. Both owned node processes were reaped cleanly
and all temporary outputs were removed. The [fresh echo build](../evidence/first-node-build-2026-09-21.json)
records the component/WIT/toolchain inputs. Runtime build source `21e03395` and
the later collector/build source `55ba1c30` retain separate byte identities.
This source-based execution leaves native-bundle installation under #308 and
human newcomer review pending.

The earlier maintained tree also has successful CI receipts for
[operator delivery and recovery](../evidence/guide-operator-2026-09-21.json),
[managed publication](../evidence/guide-publication-2026-09-21.json),
[offline transfer](../evidence/guide-offline-2026-09-21.json), and
[protected native execution](../evidence/guide-security-profile-2026-09-21.json).
These receipts identify synthetic signing fixtures explicitly. The
[provider summary](../evidence/provider-guide-2026-09-21.json) binds their CI
source tree and records the separate Angular failure without treating the
whole workflow as passed.

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


## Reference and contributor commands, 2026-09-21

The [contract and evidence guide](../learn/read-contracts-and-evidence.md),
[Start route](../start/index.md) and [contributor route](../how-to/operate-and-contribute.md)
were exercised from clean source `bb2062afeeea8561c1403202a87b6ad4c63ddf83` on Linux with Python 3.13.5.
The [unaltered command receipt](../evidence/reference-guides-2026-09-21.json)
has SHA-256 `79cd77d86d1c2d77f69b1fdbb2d82adc9e77f6ffc45c5321fdea782ab99b8881`; it binds the exact guide and validator files,
commands, expected and actual exits, output hashes and observed output.
The guide files remain byte-identical to the tested source in this evidence update.

Pinned Python prerequisites, repository/documentation validators, the retained
six-language SDK matrix, the retained provider resource campaign and contributor
checks all passed. Selecting the parent evidence directory deliberately exited
1 with `sdk-provider-matrix-incomplete-or-invalid`. The first-node guide suite
and all 27 resource collector regressions passed on Linux. The checksum validator
accepts the collector's typed digest and a standard sha256sum record naming the
exact retained file; this execution leaves the historical receipt unchanged.

This is execution of static contract and retained-evidence validation commands.
It does not rerun the historic SDK or resource workloads, build an installed
bundle, measure performance, or supply a human newcomer review. All six affected
coverage rows keep their human review pending. The installed-native prerequisite
and the complete 27-topic maintainer review remain required for gate acceptance.

## Check an automated first-node receipt

The user walkthrough now contains manual steps. Maintainers can still inspect
the automated companion receipt with this bounded reader:

```bash
python3 - "$RESULTS/receipt.json" <<'PY'
import json, sys
with open(sys.argv[1], "rb") as source:
    raw = source.read(65537)
if len(raw) > 65536:
    raise SystemExit("Receipt is too large")
record = json.loads(raw)
if record.get("schemaVersion") != "latent.first-node-guide.v1" or record.get("passed") is not True:
    raise SystemExit("The first-node walkthrough did not pass")
if (record["successfulInvocations"] != 2 or record["declaredErrors"] != 1
        or not record["retainedDeploymentInvokedAfterRestart"]
        or not record["temporaryOutputsRemoved"]
        or len(record["shutdowns"]) != 2
        or not all(item["clean"] and item["reaped"] for item in record["shutdowns"])):
    raise SystemExit("Missing invocation, recovery or cleanup evidence")
print("Two successful invocations, one declared error, retained restart, two clean stops.")
PY
```
