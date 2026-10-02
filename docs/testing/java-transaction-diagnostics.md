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

Only this explicit diagnostic source assigns three unsigned `update.delta`
selectors: `4294967293` throws a fixed trap after staging, `4294967294`
enters a reachable loop after staging, and `4294967292` retains successive
64 KiB arrays in an `ArrayList` after staging. The memory selector uses the
same retained-array and volatile reachability mechanism as the maintained
Java recovery template. All three stage an ordinary delta of one
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

The source guard requires the one original awaited State put to precede the one
original awaited intent stage. Memory allocation then uses the original finite
64 MiB guest ceiling and one-billion fuel ceiling; no budget or import is added.
A new build must retain its new helper/source/component identities and the exact
original signed companion, limits and deferred-HTTP requirements. The five
original components and earlier diagnostic component remain immutable evidence.

Actual memory qualification requires the original activation's memory producer
diagnostic, nonzero staged write consumption and one intent, physical retirement,
the durable known-not-committed/abort fence, an unchanged fresh query and zero
recipient PUTs. Fuel exhaustion, deadline expiry or a generic guest trap cannot
be relabelled as a memory outcome. All source records retain memory qualification
as false until that actual campaign succeeds.

Crash before commit is a separate host campaign. It requires an actual common
native owner witness that the original write and intent were staged, before
killing and reaping that owned node. The existing loop does not emit a staging
marker. A Running observation, elapsed delay, closed socket or process exit is
insufficient. After restart, inspect the original attempt and durable fence under
current authority and check the fresh query and recipient independently. Without
that shared witness and recovery evidence, the crash case remains unqualified;
no guest retry, alternate persistence protocol or inferred abort is permitted.
