# Real-node stream management credential handoff

This is a contributor qualification command for the protected
[stream operator](../runtime/outbound-stream-operator.md#recovery-after-management-token-expiry).
It exercises real standalone management RPCs, durable policy receipts and
protected local recovery state. It does **not** install an outbound stream
provider, publish a signed component, invoke a guest, or open a guest socket.
The provider descriptor and publication ID are deliberately policy-metadata
fixtures. Their acceptance does not establish provider readiness or authority.

## Run the scenario

Use the repository's Python 3.13 environment and explicitly selected Linux
x86-64 `latentd` and `latent` executables. The CLI must support the current
policy commands and the opened-configuration digest check; an older binary
without that option refuses the operator's requests. From the source checkout, choose a **new**
work directory under an owner-controlled private parent:

```sh
python3.13 -m tools.outbound_stream_credential_scenario \
  --node /path/to/latentd --cli /path/to/latent \
  --work-dir /private/qualification/new-stream-handoff
```

The command is source-only; it is not a new `latent-dev` subcommand or a claim
about older published toolkits. It creates private configuration, client,
operator and catalog files without overwriting an existing work directory.
The real node checks the protected configuration before startup. A writable
ancestor, unsafe link, unsupported binary or rejected configuration fails the
scenario; there is no broader fallback.

Keep this directory private. It contains randomly generated, test-only bearer
credentials and durable journals. The command retains it for owner inspection
on success or failure, rather than deleting unresolved operations. Never use
production credentials, an existing node directory or a production listener.
A completed scenario leaves its actual policy grants durably denied and its
owned node processes stopped. A failed scenario makes no cleanup or remote
outcome claim merely because the command exited. It still attempts process-group
cleanup through the existing owner, and retains the private journal for review.

## What executes

Three independent cases cover an interrupted first provider-binding grant,
first policy grant and policy revocation. Each starts a local-experimental
standalone node with its normal durable audit and capability-policy owners.
The helper calls the actual CLI. Immediately after one selected successful
native apply, the controller deliberately withholds the response from the
operator. This is an explicit **post-success confirmation-loss injection**, not
a simulated server response, a network-failure experiment or a replay.

Each case then stops and reaps the node, replaces its management bearer in the
protected configuration, and restarts the same catalogs on the same loopback
endpoint. The old client file remains byte exact. The real authenticator must
reject its removed bearer. Recovery with that client must remain unresolved.
An authenticated foreign-tenant client must also be unable to adopt the owner.
A node operator may inspect global node identity; that does not entitle its
foreign tenant to the original policy receipt. An unavailable receipt stays
unknown, not permission to replay.

The intended replacement performs exactly four read-only handoff calls. The
scenario checks that the pending journal and retained receipts remain
byte-for-byte unchanged and that no handoff mutation occurs. It then runs the
actual source `recover` command as a separate owned process, using the selected
native CLI. Recovery must return the original operation identity and settle
only that retained intent. The original request is never resubmitted. Fresh
operator construction, completion of interrupted grant setup, durable deny and
idempotent repeated deny are checked before both node processes are reported
cleanly stopped and reaped.

The controller uses the existing process owners and a shared 90-second work
deadline. Startup observation is capped at 15 seconds; source recovery at 30
seconds; each observed client is capped at 64 calls. Existing separate bounded
shutdown and process-cleanup deadlines still apply. Executable inputs are capped
at 256 MiB each and their SHA-256/size identities are rechecked after execution.
The public result excludes credentials, raw native output and private paths.
The source-recovery output is checked for leakage before it is accepted.

## Readiness and evidence limits

Authenticated management reachability is not activation readiness. The result
retains each actual `nodeReadyAtInspection` boolean, including `false`, and
always reports `productionReadiness: false`, `installedStreamProvider: false`
and `streamExecution: false`. Workload readiness is not silently inferred from
successful policy mutations or a clean process exit.

The [8 November 2026 observation](evidence/stream-credential-handoff-2026-11-08.json)
records three passing native cases and six clean node stops on Linux/Python
3.13.5. Its selected binaries came from CI run `42493744737`, artifact
`13624015987`, at tested merge `0e99b2b7303b6540d45c447c8593defebb947bf7`.
The archive and executable hashes were checked. The Python controller and every
executing helper have separate Git blob identities in the receipt; these are
not newly rebuilt native binaries from the later continuation commit.

All six node health observations were not ready. A separate authenticated
inspection reported `load-unavailable` in this container. The initial campaign
that required workload readiness failed; the final command explicitly measures
management recovery only and preserves the false readiness observations. A
foreign tenant's receipt lookup returned `not-found` with `outcomeKnown: false`,
whereas the removed bearer returned a typed `unauthenticated` platform error.
Neither is relabelled as a successful recovery or a definite mutation rollback.

A separate [ready-node follow-up](evidence/stream-credential-handoff-ready-2026-11-08.json)
used the same authenticated older native binaries with the revised controller.
All three cases and six clean stops passed with `ready: true` at both inspections.
The original controller rejected the node's valid `ready` startup event before
management checks; the revised controller accepts `ready` and `started` only
when each agrees with the boolean readiness field. The source and binary
identities, local environment, negative result and limits are recorded separately.
This does not qualify an installed stream provider or signed guest.

The additional controller unit tests use explicit protocol doubles to check
response-loss selection, failure preservation, finite calls, readiness typing,
new-directory protection and public-error redaction. Run them separately:

```sh
python3.13 -m unittest tools.tests.test_outbound_stream_credential_scenario
```

This observation does not qualify a frozen frontend, Windows, live bearer
expiry/reload, TLS credentials, DNS/address enforcement, signed standard-library
networking, provider quotas, quarantined physical owners or live stream
rotation/revocation/drain. Those remain required under
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739) and its
provider/security prerequisites. No production gate or whole acceptance
criterion is closed by this management-only scenario.
