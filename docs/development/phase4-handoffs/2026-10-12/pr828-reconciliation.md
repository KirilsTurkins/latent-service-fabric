# PR #828 reconciliation

PR: <https://github.com/KirilsTurkins/latent-service-fabric/pull/828>

The original `1b7a8073` branch is reconciled through a normal merge with
development `ae29f464`, including PR #823's installed transaction runtime.
Current State, Effects, activation, native completion, provider and RPC owners
remain the foundation of the shared HTTP implementation.

## Issue and snapshot context

Read the bodies and comments of #409 and #718, with the previously reviewed
transaction foundations #387, #388, #400, #408, #389 and #401. #409 owns the
reusable transactional HTTP integration. #718 owns its signed Java consumer
qualification. This PR has no closing reference and closes no ticket.

Snapshot #974's installed runtime is already incorporated through #823.
#879 preserves a failed signed Java query and its continuation collector;
#968 preserves compiler/source captures. Neither supplies successful current
runtime qualification. #861's networking checkpoint overlaps the current
foundation and supplies no additional HTTP correction to transplant.
The old put-once HTTP protocol is replaced by the maintained qualified HTTP
effect adapter and its actual installed provider configuration.

## Delivered behavior

- Closed signed transaction routes use the existing shared listener. Commands
  canonicalize input with the prepared component's actual parameter types before
  durable claim, preserving the original activation budget, deadline and code
  owner. GET/HEAD queries execute against a fresh native view without command
  rows. Explicit result reads use the existing prepaid recovery lane and current
  read permission, without executing an old guest generation.
- Commands validate the bounded HTTP representation before the shared native
  completion commits. Host-owned cell metadata remains trusted completion
  metadata and is omitted from application JSON. Arbitrary guest metadata,
  cookies and headers cannot enter replay. Cleanup failure remains a delivery
  diagnostic alongside the durable receipt. Every write and flush poll retains
  the current delivery fence and original physical capacity.
- The existing signed transaction-asset capture optionally accepts the exact
  bounded `deferred-http-requirements.json` asset on its original recovery worker.
  Configuration, companion, deployment, provider, endpoint, credential reference
  and profile associations remain checked. Resident metadata and document bytes
  remain charged to their original owners.
- Deferred HTTP uses the actual installed provider, shared protected clock and
  existing effect dispatcher. Staging and dispatch have separate current policy
  bindings. Every real GET, POST and lookup poll checks current dispatch authority;
  lookup cannot fall through to POST. Dispatch resumes only after all signed
  installations and readiness checks succeed.
- Retry attempts use the coordinator's canonical decimal identities. The CI
  registry adds the actual new cases while preserving existing cases, ignore
  guards, execution contracts and command coverage.

## Verification

The eleven native library suites passed 1,886 ordinary cases. All 26 maintained
real Rust transaction cases passed separately. The real signed package/component
fixture passed a query over the shared HTTP socket and refused another caller
before guest activation. The signed optional-document limit test and real TLS
dispatch-policy test passed; the latter verifies refusal before recipient POST.
Foundation, documentation and CI command coverage checks passed. A scoped pinned
Gitleaks scan found zero findings and used zero exceptions.

The locked all-feature workspace/all-target build passed. Exact discovery
recognized all 191 registered targets and 4,130 active cases; discovery does not
claim they all executed. All 25 HTTP integration cases and all 9 real deferred
NATS cases passed, including the seven that failed on the old PR head.
The Python run executed 3,861 cases with the 18 existing environment skips.
One unchanged 100 ms process-start timing test observed prerequisite refusal
under concurrent build load; its isolated rerun passed with unchanged assertions.
All changed Python checks passed. Workspace Clippy, strict application/admission/
testkit Clippy and formatting are recorded in the final PR description.
Local failed fixture and validation attempts remain under `target/pr828`;
they are not qualification receipts.

## Remaining qualification

The signed native fixture establishes installed host composition, not signed Java
guest or packaged consumer qualification. #409 and #718 retain their current Java
application, full browser/cancellation/replay/retention and six-language consumer
acceptance matrices. Historical snapshot receipts do not qualify this source.
Configured live installation replacement and additional delegated/shared
recovery bindings still require their explicit current-owner integration.

Protocol documentation: [transaction HTTP](../../transaction-http-v1.md) and
[signed deferred HTTP installation](../../deferred-http-installation.md).
