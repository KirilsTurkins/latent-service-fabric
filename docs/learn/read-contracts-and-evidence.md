# Read contracts, security limits and retained evidence

## Outcome and supported version

Trace an operator action to its authoritative contract, check a retained
six-client result, and distinguish a measured resource observation from a
configured limit or a future architecture decision. You finish with a source
identity, the relevant contract, the original execution record and a clear
statement of what that record establishes.

This is a development guide. Select the matching documentation version before
following a released API; development providers and publication fields are not
retroactively part of the source-only alpha.3 release. The
[API map](../api-surface.md), [SDK support matrix](../../sdk/README.md) and
[runtime identities](runtime-identities.md) provide the detailed contracts.

## Prerequisites and full source

Use a complete checkout of the reviewed development source and Python 3.13.5.
Run these commands from the repository root in the documented Linux contributor
environment. The dependency file pins the existing validator prerequisites:

```bash
git rev-parse HEAD
git status --short
python3 -m pip install --requirement tools/requirements.lock
```

Retain the commit and any existing edits with your result. The commands below
read repository contracts and previously captured evidence. They do not build
or start an LSF node, install a server, contact a provider account, or repeat a
resource campaign. Real runtime qualification stays with the linked original
owners and runs.

## 1. Follow an operation to the contract that owns it

Suppose a deployment response is lost. Start with the operation's retained
identity and the matching CLI family; an activation ID is not a replacement
for a deployment operation ID. Follow the contract before deciding whether
another request is safe.

| Question | Authoritative starting point | What to check |
| --- | --- | --- |
| Which CLI command reads the original outcome? | [Operator CLI](../reference/operator-cli.md) | Command family, actor/tenant scope, operation identity and finite retention. |
| Which service or error value crosses the network? | [API surface](../api-surface.md), [API source](../../api), [platform errors](../protocol/platform-errors.md) | Required fields, presence, full-width numeric values, declared errors versus platform/transport failure. |
| Which configuration or document shape is supported? | [Schema inventory](../../schemas/README.md), [node reference](../reference/standalone-node.md) | Exact schema/profile and unknown-field handling; syntactic validity does not grant authority. |
| Which interface does the guest import? | [WIT source](../../wit), [capability bindings](../runtime/capability-bindings.md) | Versioned host ABI, imported operation and the activation's actual grant. A network client SDK is not a guest binding. |
| Which source implements the client behavior? | [Six-client support](../../sdk/README.md), [shared provider workflow](../testing/sdk-provider-workflow.md) | The specific language's cancellation, ownership, pagination and shutdown semantics. |

Check the repository and documentation contracts:

```bash
python3 tools/validate_repository.py
python3 tools/validate_docs.py
```

The first command reports the validated source-file count and exits successfully
when its repository checks pass. The second reports document/link/anchor counts
with an empty `errors` array. Counts change as reviewed sources grow; zero exit
status and no reported errors are the checks, not a copied historical count.
These validators do not prove that a guest ran or that a mutation committed.

For the lost response, use the
[delivery and recovery guide](deliver-and-recover-a-capsule.md). Preserve the
original request, tenant and preconditions. A missing or evicted receipt remains
unknown; generating a new operation identity would be another mutation.

## 2. Verify a complete retained client result

The [six-client guide bundle](../evidence/phase3-sdk-guides-35509915448/README.md)
names its original CI run, tested merge and displayed-source identities. Read
that provenance before interpreting the JSON files, then run the maintained
validator over that exact directory:

```bash
python3 tools/verify_sdk_provider_matrix.py docs/evidence/phase3-sdk-guides-35509915448
```

Expect `passed: true`, six languages and `assertionsPerLanguage: 18`. The
[validator source](../../tools/verify_sdk_provider_matrix.py) checks the actual
receipt set, common node/CLI/fixture identities, assertion results, held-request
closure and node/client cleanup. It reports the current hashes of the retained
language files. Compare those identities with the original bundle and source;
validation of JSON consistency is neither a signature nor a new execution of
the original client tests.

The original run observed native clients against separate authenticated nodes
and actual HTTP/blob guests. It does not certify an installed release bundle,
a browser management client, production latency or newcomer pedagogy. In
particular, a transport cancellation does not establish server cancellation;
the original workflow separately observes the explicit cancellation path.

## 3. Read the resource population and its limits

Validate the unchanged successful provider-campaign receipt and its checksum:

```bash
python3 tools/phase3_resource_campaign.py --validate docs/testing/phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-campaign.json
```

Expect `valid: true` and the retained `ticketAcceptance: pending` field. The
receipt was a bounded checkpoint when written; later review does not edit that
historical status. The [recovery report](../testing/phase3-resource-recovery.md)
separates the successful provider profiles from the later setup failure in
their combined matrix and the separately successful web matrix.

Read `build`, `profile`, `configuration`, `samples`, `cycles`, `checks` and
`shutdown` together. For this provider population the fixed observations have
one process, eight threads, one listener, 34 descriptors and 58,589,184 bytes of
RSS. The same process/thread/listener/descriptor counts remain at 4, 16 and 32
added dormant deployments, while metadata and RSS grow. This supports the
bounded ownership observation; it does not mean zero idle memory or a universal
memory saving.

Retain every offered and unfinished arrival when reading latency or throughput.
A configured memory ceiling is not RSS, summing invocation peaks is not a
simultaneous-memory measurement, and an unavailable counter is not zero. The
[renderer report](../testing/phase3-resource-renderer.md) distinguishes Wasm
linear-memory peaks from live JavaScript allocator bytes and explains absent
cancelled-status consumption. The [OCI report](../testing/phase3-resource-oci.md)
labels reservations as accounting charges rather than process-memory readings.
Use the [retention contract](../testing/benchmark-retention.md) before comparing
another source, machine, profile or warmed cache with these observations.

## 4. Separate decisions, enforced authority and future work

Use the [architecture overview](../architecture/overview.md) to locate an owner,
the [decision records](../../adr/README.md) to understand a choice, and the
[security matrix](../testing/phase3-security.md) to find the exact executed
negative cases. An architecture diagram or accepted decision is not execution
evidence. A cached component or a historical operation receipt is not current
tenant/publication authority.

The [execution-profile contract](../runtime/execution-security-profiles.md)
distinguishes trusted local evaluation, enforced external-capsule admission and
unsupported profiles. Protected native compilation does not itself isolate a
running guest in another process. Refusal of a required profile or protected
configuration is an actionable boundary, not a reason to remove that setting.

The [state/effect architecture](../architecture/state-and-effects.md) separates
immediate capability effects from later transactions and an outbox. A completed
HTTP request or event publication does not provide universal exactly-once
execution. The [cluster freshness handoff](../architecture/cluster-freshness-handoff.md)
is a design boundary for later placement/routing work, not a running cluster.
Use the [roadmap](../roadmap.md) and the concrete implementation ticket together
when assessing those capabilities.

## Deliberate failure and contributor checks

Point the client validator at the parent evidence directory, which is not a
complete six-language bundle:

```bash
python3 tools/verify_sdk_provider_matrix.py docs/evidence
```

This command must exit with status 1 and
`sdk-provider-matrix-incomplete-or-invalid`. Correct the selected directory;
do not fill missing results with another language's receipt or treat incomplete
evidence as a pass. A real checksum mismatch similarly requires investigation
of source and bytes, not an edited checksum to silence the validator.

For the introductory contributor path, run its existing small owner tests:

```bash
python3 -m unittest tools.tests.test_first_node_guide
git diff --check
```

Expected test success establishes runner sequencing, redaction and cleanup
contracts. The [first-node execution receipt](../evidence/first-node-guide-2026-09-21.json)
is the separate evidence that an actual node was used. The
[operate and contribute guide](../how-to/operate-and-contribute.md) connects
these checks to readiness, cancellation and safe retained-result inspection.

## Cleanup and review record

These validation commands leave the retained evidence unchanged and own no
server or provider account. The small test owner reaps its temporary processes
and cleans its private fixture directories. Preserve your command results,
source revision and expected negative result; do not remove a real catalog or
rewrite a historical receipt as guide cleanup.

The [core guide validation handoff](../development/core-guide-validation.md)
records which commands were actually executed and their scope. Rendered-path
and human review remain separate. Next, follow the matching client, capsule or
provider guide with the version and owner you identified here.
