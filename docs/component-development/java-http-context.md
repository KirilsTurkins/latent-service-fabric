# Context and budgets through a Java HTTP composition

The maintained [Java HTTP example](java-http-composition.md) uses an ordinary
signed Java adapter and an independently signed Java domain capsule. Its clock
imports and local-service call need explicit installed bindings and current
grants. The adapter omits `latent:context/context@0.1.0`; this installed standalone
profile does not supply an ordinary context provider. Exporting `handle` does
not select a sealed web publication or grant core context authority.

The versioned [installation table](../../contracts/guest-context/installation-v1.json)
records the supported publication/import/provider combinations. The released
`0.1.0-alpha.4` tag resolves to
`2d6cc2eafc0a17dfe573be4252fa49835bebbbd6`. That source already limits implicit
broker context to a verified native `CheckedWebLayout` renderer projection. The current development
profile preserves that authority boundary. Its per-component transfer limits,
diagnostic tree and generated example are development changes; this guide does
not identify a released binary containing them. The historical private Java
application's failed receipt remains historical evidence and is not overwritten
by a new successful fixture run.

| Publication and installed profile | Context import | Result |
| --- | --- | --- |
| Ordinary capsule, installed clocks and local service | Omitted | Supported composition; authorized operator inspection exposes actual lineage and admitted budgets. |
| Ordinary capsule, same profile | Present | Requires an explicit context binding and grant; this standalone profile has no context provider installer. The maintained separately signed `context-required` component exercises rejection. |
| Verified native `CheckedWebLayout` renderer projection | Present | Core host context is available; unrelated provider imports still require their own exact bindings and grants. |
| Trusted embedding with a broker session | Present | Explicit ordinary binding and grant, or a verified native `CheckedWebLayout` renderer projection. |
| Trusted embedding without a broker session | Present | The trusted embedding supplies the bounded execution request and host state. This is not a standalone capsule or caller-selected authority mode. |

The ordinary pair still receives host-derived authority internally. An actual
HTTP request creates a Trigger principal with no caller service. The local
service broker derives a Service principal whose caller service is the adapter;
it records the actual parent and root activation IDs. An operator invocation of
the adapter has an Administrator root and a Service child. A child never acquires
the original HTTP trigger or administrator principal from its parent's metadata.
The qualifier proves this with a trigger-only grant that rejects the operator
path, a missing service grant, and a wrong child-principal clock grant.
The domain's `status` operation actually calls the declared monotonic provider;
an unused import cannot prove grant denial. The wrong-principal case requires the
actual child's bounded Binding/GrantDenied diagnostic and failed outcome,
alongside the adapter's HTTP failure. A guest trap while calling a denied clock
can produce HTTP 500 through the existing platform-failure mapping.

## Run and inspect the actual example

Use the exact Linux toolchain and source-build prerequisites from
[Java authoring](java-authoring.md). Build the CLI and node from the same source,
including the explicit disposable former-profile reproduction feature:

```sh
cargo --config .cargo/managed-guest.toml build --locked -p latent -p latentd --bins --features latentd/development-test-node -p latent-packaging --example package --example capsule_contracts -p latent-policy --example capsule_authoring
python3 tools/qualify_java_http_composition.py --output "$NewQualificationDirectory" --wasi-sdk "$WasiSdk" --target "$CargoTargetDirectory"
```

The command captures, compiles and signs the ordinary pair and the context-import
negative component. It starts owned loopback nodes with ephemeral demo trust,
creates exact publications and pinned triggers through the real operator CLI,
executes normal typed HTTP calls, and retains every control response. This
qualification requires the actual Java/TeaVM components and a running node.
WIT generation or JVM compilation alone does not satisfy it.

On a running equivalent node, use your configured tenant-scoped operator profile
and the published service name:

```sh
"$Cli" --output json --config "$ClientConfig" --profile "$OperatorProfile" activation roots --service examples/java-http-adapter --from-unix-millis "$ObservedFromUnixMillis" --page-size 32
"$Cli" --output json --config "$ClientConfig" --profile "$OperatorProfile" activation tree "$ActualRootActivationId" --page-size 8
```

Read the actual root ID from the first command and follow its continuation token
when present. Discovery is bounded retained history, with a frozen pagination
horizon; it can report an empty page and a continuation. Root IDs are not guessed
from counters or copied from browser responses. The tree reports trusted
`principalKind` and `callerService`, admitted `grantedBudget`, the effective
deadline, real parent/root IDs, finite diagnostics and terminal state. The guest
and public HTTP response do not receive this privileged diagnostic contract.

The `http/context.json` receipt contains the exact parent and child grants.
Child admission uses unspent capacity after work already performed by the
adapter. The fixture checks CPU fuel, memory, wall time, child-call reservation,
and every remaining finite budget dimension against the actual grants. Its
smaller-parent case demonstrates further narrowing; it does not hard-code a
claim that a deployment ceiling equals the amount eventually granted.

The selected `/api/status` route uses `None` for an additional child deadline.
`/api/status-deadline` uses `Some(host clock + 2000 ms)` and
`/api/status-expired` uses `Some(host clock)`. Route configuration permits only
an explicit integer offset from zero through 60,000 ms; HTTP headers and typed
arguments cannot select a deadline. The broker intersects any explicit ceiling
with the parent's effective monotonic deadline, including time spent queued.
An expired child call fails before accepted work. The qualifier then observes
physical cleanup and executes a fresh normal request.

It also sends forged forwarding, principal, deadline and lineage headers,
caller-supplied lineage and oversized context metadata. Accepted HTTP requests
must retain the real Trigger/Service identities and lineage; rejected requests
must leave a fresh request usable. A real two-cell cancellation records the
actual child, waits until stores/cells/quotas are retired, and then runs a fresh
composition. No accepted child or provider operation is retried automatically.

## Application observations and unavailable values

The ordinary Java guest has no context import, so it cannot observe a trusted
peer address, end-user subject, root identity, trace baggage, claims or live
budget through a fabricated Java object. Use the supported operator tree for
privileged troubleshooting and the broker-enforced grant/deadline for execution.
Application authentication can establish an explicit application actor and
rate-limit key in the domain protocol; those data remain application inputs and
must be validated there. Use ingress connection/exchange limits for transport
capacity. The platform does not silently delegate an end-user actor across this
service hop or treat forwarding headers as trusted client identity.

Where a supported context publication or trusted embedding is selected, default
disclosure exposes only the `guest.` metadata namespace. Claim and baggage
allowlists are empty; each configured allowlist is limited to 32 keys of at most
256 UTF-8 bytes. Fixed principal, trace and activation fields remain independent
of those allowlists. An absent optional deadline means no additional ceiling;
it is distinct from an unknown diagnostic measurement and from an admitted
finite effective deadline.
