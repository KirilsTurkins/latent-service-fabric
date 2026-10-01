# Bounded external maintenance triggers

An operator-managed scheduler may initiate a finite authenticated invocation
through the [existing CLI or clients](../protocol/invocation-service.md). It runs
outside LSF; no guest stays alive between runs. The interim example here observes
expiry in synthetic records, performs no mutation and uses no persistence layer.
It is compatible with the stateless alpha.4/alpha.5 boundary, not transactional cleanup.

| Timing contract | Versioned support and owner |
| --- | --- |
| External authenticated trigger | Current bounded invocation API; schedule, missed-run and overlap policy belong to the operator. |
| Timer inside an active invocation | Planned [SDK runtime #736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736), language ports #741–#746; alpha.4 and a clock-read grant do not establish it. |
| Durable future application invocation | Phase 6 under [#379's roadmap handoff](https://github.com/KirilsTurkins/latent-service-fabric/issues/379); this guide and Phase 4 do not ship it. |

A root deadline interrupting a wait is cancellation, not successful timer expiry.
No recurring callback survives activation retirement. Use the qualified standard
language-runtime path when available, rather than a resident guest loop or a
per-library LSF executor. Maintenance network calls retain separate typed-HTTP
or explicitly approved stream authority; research alone does not enable sockets.

## Select the supported trigger and authority

Provision an invocation-only credential for the exact tenant and an application
principal authorized for the operation/entity scope. Keep its protected CLI
profile outside sources, build output, browser code and logs. The node's `invoke`
role denies management access but does not establish per-command business
authorization. The application must check current permissions on every call and
on recovery. Never forward a management token to a browser or trust a scheduler's
identity headers. Use finite tenant admission quotas and a finite external job deadline.

For a source-backed transport smoke check, deploy the maintained
[echo component](../../examples/echo-contract/README.md) with its explicit
context/log grants. An input file containing `["maintenance-observation"]` uses
the current positional [WIT payload](../protocol/wit-values.md):

```sh
"$Cli" --config "$InvokeProfile" --tenant "$Tenant" --connect-timeout-ms 1000 --rpc-timeout-ms 5000 --output json invoke --service "$EchoService" --contract examples:echo/api@0.1.0 --function echo --input "$ObservationPayload" --activation-id "$UniqueActivationId" --cpu-fuel 1000000 --memory-bytes 4194304 --wall-time-ms 4000 --log-bytes 4096
```

Policy, admission and remaining deadlines still narrow requested budgets. Echo
proves transport only; it performs no cleanup. Each read-only transport attempt
has its own activation identity. Bounded activation receipts do not provide
durable business deduplication. An unknown mutating outcome requires recovery
by its original durable command identity once the needed Phase 4 support is qualified.

One external scheduler entry may launch this finite job. Explicitly choose
bounded concurrency, overlap and cadence; a missed run may coalesce into one
later read-only sweep. Scheduler configuration alone proves neither successful
maintenance nor signed admission or durable recovery.

## Run and checkpoint the read-only example

The maintained [implementation](../../tools/maintenance_example.py) and
[synthetic input](../../examples/maintenance/read-only.json) use the repository's
Python 3.13 toolchain, no credentials, network, guest runtime or state store:

```sh
python tools/maintenance_example.py --fixture examples/maintenance/read-only.json --synthetic-now-millis 2000
python -m unittest tools.tests.test_maintenance_example
```

The observation labels `execution: synthetic-read-only`, `guestExecution: false`,
`durableSchedule: false` and zero mutations. At time 2000 the first two records
are expired and the third remains valid. Tests cover duplicate/overlapping
read-only triggers, a missed/late run, interruption after an observed prefix,
reconstruction from a valid cursor, stale/forged cursors and changed authority.
These establish the application algorithm, not an executed guest transaction.

Pages contain at most eight records and 2048 encoded bytes. Work is finite over
at most 64 immutable snapshot records. The 69-character opaque cursor binds
tenant, snapshot and progress; it is no authorization bearer. A changed snapshot
refuses the cursor instead of silently refreshing it. An interrupted page returns
the actual observed prefix and next cursor. After validating a complete response,
the operator may checkpoint read-only progress in its protected external job
journal. A lost response may repeat an observation, with no uncertain mutation
to replay. Transactional mutation progress must instead consume the platform's
qualified command/state guarantees, not an invented second store.

Access-time expiry remains mandatory if maintenance is late or never runs.
Use an independently authorized application clock; a scheduler-supplied time is
not authority. The fixture refuses regression below its retained trusted floor
and never deletes records. An expired application token does not authorize
deletion of command, effect, inbox or payload identities needed to resolve
uncertainty. Stateful cleanup consumes qualified [#397 retention](https://github.com/KirilsTurkins/latent-service-fabric/issues/397)
and [#399 restore/reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/issues/399).

The application enforces operation scope, cursor validity, finite pages and expiry.
LSF enforces authenticated tenants, explicit grants, bounded budgets/deadlines,
cancellation and physical cleanup. Neither guarantees external scheduler availability.
The synthetic runner creates no output directory or secrets. After a transport
smoke check, drain the owned test deployment and remove only its owned files;
preserve original recovery identities for unresolved durable work.

## Finite Phase 6 handoff

Before advertising durable platform schedules, their roadmap owner must define
and qualify:

- Stable tenant/namespace schedule and payload/version identities, creation,
  update, cancellation and result-read authority, with generation preconditions.
- Authorized due-time/clock semantics, restart floors, older-history restore,
  bounded expiry and linked retention.
- Explicit missed-run policy: skip, coalesce or finite catch-up; finite backlog.
- Duplicate/overlap policy and durable command linkage, including original-outcome
  recovery. Local timeout is insufficient authority for a second mutation.
- Bounded indexed due batches, fair tenant admission, aggregate byte/work quotas
  and shared node workers. Dormant schedules retain no guest heap, process,
  thread, listener, execution cell or per-application timer.
- Restart/restore reconciliation, cancellation racing accepted work, deletion,
  protected command/effect references and compatible format migration.

The future owner remains linked through [#719](https://github.com/KirilsTurkins/latent-service-fabric/issues/719)
and the [roadmap](../roadmap.md). Internal outbox retry is not a public scheduler.
Core Phase 4 does not wait for this future engine. Java transactional maintenance
consumes #718's actual support; the stateless adapter hop and an SDK runtime
planning ticket are insufficient evidence of durable maintenance.
