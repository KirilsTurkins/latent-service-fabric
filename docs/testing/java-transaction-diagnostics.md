# Java transaction fault capsule

The separate maintained diagnostic capsule is captured with:

```sh
python tools/java_transaction_diagnostics.py --project /tmp/java-transaction-diagnostics
```

The maintained compiler has a separate explicit single-component plan:

```sh
python tools/compile_transaction_guests.py --language java \
  --java-post-stage-diagnostic --wasi-sdk /path/to/pinned/wasi-sdk \
  --output /tmp/java-transaction-diagnostic-compiler
```

Its original default aggregate/forbidden-HTTP plan and explicit three-schema
put-once plan retain their existing component sets. The diagnostic flag is
Java-only and cannot be combined with the three-schema flag. Its unsigned
receipt captures the original source, SDK, helper, requirements and compiler
inputs separately; it does not qualify admission or execution.

It retains the aggregate's `update`, `query` and `scan` WIT, State resources,
opaque original NV2/SV2 observations, exact companion and captured 27-byte
put-once intent requirements. It declares the same finite budgets, no child
calls and no immediate outbound request. Its new source and helper identities
are recorded separately from the five immutable compiler-qualified components.
The authoring record grants no authority and claims no execution.

Only this explicit diagnostic source assigns two unsigned `update.delta`
selectors: `4294967293` throws a fixed trap after staging, and `4294967294`
enters a reachable loop after staging. Both stage an ordinary delta of one
through the same actual State put and captured intent call first. Cancellation
uses the same loop with the original grant. All exports check a per-instance
static invocation counter; successive successful real activations must each
receive a fresh guest instance. The counter has no reset or persistence API.

The JVM vectors exercise only helper behavior. The actual signed node campaign
must discover the original activation through authorized roots/tree, and cancel
that exact root once. `Running` alone is insufficient. Final original
consumption must show nonzero state write bytes and one staged intent, followed
by the native known-not-committed/abort fence, an unchanged fresh query and zero
recipient PUTs. The fuel case must retain its actual producer diagnostic. A
cancelled activation that never reached staging remains a failed qualification
attempt. No write is retried, no result is inferred from a timeout, and no
provider, credential, effect rule or namespace grant is installed by this helper.

The separate actual diagnostic TeaVM/C/WASI compilation is recorded in
[compiler R1](../evidence/java-transaction-diagnostic-compiler-r1/README.md).
Its original process succeeded, but a subsequent Docker engine provisioning
failure left the original component export unavailable. The retained measured
identity is distinct from artifact availability and from the still-required
signed runtime campaign.
