# Controlled canary promotion

A [durable rollout](phase-2-rollouts.md) can declare an immutable canary policy.
Operators explicitly evaluate and promote it through its declared weight stages.
One shared coordinator uses the node's actual activation observations; no timer,
automatic promotion loop or service-specific execution instance is created.

## Explicit policy

The optional `canaryPolicy` on Start has these required fields. Omission preserves
the existing manual Advance workflow. A canary plan requires at least two stages;
the first is below 10,000 basis points and the last is 10,000.

| Field | Accepted values |
| --- | --- |
| `formatVersion` | `1` |
| `observationMillis` | 1 through 3,600,000 |
| `minimumCandidateSamples` | 1 through 1,000,000, within configured per-window and total sample ceilings |
| `maximumFailureBasisPoints` | 0 through 9,999 |
| `latencyThresholdMicros` | 100; 1,000; 5,000; 10,000; 50,000; 100,000; 1,000,000; 10,000,000 |
| `maximumSlowBasisPoints` | 0 through 10,000 |

These are operator-selected acceptance criteria. They do not promise a universal
latency SLO. Latency covers the existing acceptance-relative host observation,
including selected admission failures. Each histogram edge is inclusive; an
elapsed duration one nanosecond above the edge belongs to the next bucket.

The denominator is all selected **candidate** terminal outcomes. Domain errors,
platform failures, deadlines and cancellations count as failures; selected
admission failures remain included. Candidate minimums cannot be satisfied with
baseline successes. At least one admitted terminal and one successful candidate
call are also required. Exact integer cross-products compare failure and slow
counts with their declared basis-point limits, accepting equality. Reports retain
both revisions' individual outcome counts, admission counts and nine buckets.

## Evaluation and promotion

`EvaluateRollout` requires the exact tenant and rollout revision. It may register
a missing fresh window and return Collecting; it never changes weights. Get/List
remain reads. A completed observation can be Healthy, Failed, NoData,
Insufficient or Incomplete; a window with live terminal owners is Draining.
Unavailable observation is explicit and cannot be treated as zero failures.

`Promote` requires an operation ID, exact rollout revision and the exact next
stage. Ordinary Advance is rejected for a policy-backed rollout, including at the
catalog boundary. A copied report, window ID or healthy flag cannot authorize
promotion. The coordinator obtains an affine sealed window from the configured
node owner. The catalog verifies its exact owner, policy, tenant/service,
rollout revision, stage, route generation and compiled component/package/revision
cohort, then evaluates its counters itself.

Sealing requires the entire monotonic observation interval to have elapsed,
closed membership, all entered capture attempts accounted for, and no live
samples, abandonment, missing selection or capture loss. A window closed early
never becomes eligible by waiting longer. Capture attempts retain their existing
ownership until any loss is published, including a failed registry acquisition.
The sealed counters remain fixed after this completed interval; later unrelated
loss still conservatively downgrades diagnostic snapshots.

Promotion compiles the next weights using current release eligibility and
compatibility, then commits routes, progress and its evidence-bound receipt in
one transaction. A concurrent route mutation, rollout command or authority change
can reject the prepared operation. Existing invocation pins retain their original
revision and budget. Success does not override execution-time revocation fences.

Both a possible success response and a known rejection are size-checked before
durable critical audit acceptance. A healthy evaluation is diagnostic;
`PromotionAccepted` requires an actual committed stage. Rejected promotion has an
inspectable fixed audit reason and no committed catalog receipt. Receipt lookup
therefore retains the existing Unknown semantics for uncommitted attempts.

## Observation ownership and restart

Enable the optional `rollouts.canary` resource settings alongside manual rollout
management and durable audit; see the [node reference](reference/standalone-node.md).
The repository, coordinator and activation manager share one hub and trusted
clock. Window, sample and snapshot limits are listed in the
[observation contract](phase-2-canary-observation.md). The coordinator preallocates
at most the configured number of window slots and retains at most 8 KiB of cohort
metadata per slot. All evaluation uses its existing bounded command and response
owners.

A new interval begins at successful registration after Start, Promote or Resume.
The commit-to-registration gap is outside the interval. Registration pressure
cannot undo a committed receipt: the response separately reports unavailable
observation, and a later explicit evaluation can try to register a missing window.
Existing failed observations are not silently replaced with repeated trials;
Pause/Resume explicitly starts a fresh observation interval.

Pause and Abort retire observation ownership without waiting for late samples.
Actual retained samples and proofs keep their quota until Drop. Abort preserves
current routes; restoration is the separate rollback workflow. Resume refreshes
the same weights and starts a new window when canary capture is enabled.

Restart retains the policy, stage and committed receipts, but discards elapsed
time, windows and healthy decisions. The next explicit evaluation requires a full
fresh interval. An exact retained promotion retry returns its original receipt
without requiring a live window, including after restart. Omitting canary settings
preserves reads, Pause/Abort and same-weight Resume, while denying new canary
Start or promotion. Omitting rollout settings disables all rollout RPCs and keeps
the existing bounded history recovery and audit reconciliation.
