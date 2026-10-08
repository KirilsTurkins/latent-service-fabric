# Transactional aggregate guest

The `transactional-aggregate` template extends each maintained guest authoring recipe with the same transaction, fresh query and deferred intent contract. Its source is an independent application project. The captured `transaction-profile.json`, WIT dependencies, `state-schema.json` and `transaction-binding.json` are build inputs; installing a template grants no namespace or provider authority.

The explicit profile is `lsf-host-abi-phase4-v1`, using `latent:state/key-value@0.2.0` and `latent:intents/staging@0.1.0`. Existing stateless templates retain their Phase 3 profile. A node must support and authorize the selected transaction profile and each operation before executing this example. The checked companion links its capsule, deployment and binding exactly; it cannot request an early guest commit.

Create a project using the selected language's source authoring command:

```bash
python tools/rust_capsule.py new ../aggregate-rust --template transactional-aggregate
python tools/c_capsule.py new ../aggregate-c --template transactional-aggregate
python tools/typescript_capsule.py new ../aggregate-typescript --template transactional-aggregate
python tools/go_capsule.py new ../aggregate-go --template transactional-aggregate
python tools/java_capsule.py new ../aggregate-java --template transactional-aggregate
python tools/dotnet_capsule.py new ../aggregate-dotnet --template transactional-aggregate
```

Build the resulting project with that language's existing `build` command and pinned toolchain. The [Rust](rust-authoring.md), [C](c-authoring.md), [TypeScript](typescript-authoring.md), [Go](go-authoring.md), [Java](java-authoring.md) and [.NET](dotnet-authoring.md) authoring guides describe the compiler installation and captured-source packaging flow. Package and admit the component through the authorized node workflow. Compilation, a package digest and signature each describe their own boundary; executed transaction evidence requires the actual Linux node.

`update` reads the unsigned aggregate, checks overflow, stages its new value and an `approved-event` intent, and returns the new count with its original observations. `view-version` is the original namespace view (NV2); optional `key-version` is the original key version (SV2) returned by that same read, absent when the key was absent. These fields describe the pre-write snapshot, never a committed token. The host commits the writes, intent and original result together after successful validated guest completion. With `reject` set, the same guest returns the declared `rejected` business error after staging; the host preserves that terminal rejection while discarding the business writes and intent. Host failures remain platform failures.

`query` acquires a fresh read-only view. `scan` opens a bounded page and pulls entries while retaining its original view; it returns the page view identity and optional continuation cursor. No query has a command key or a mutation API. Caller command identity, stale-edit preconditions and minimum read-after-commit version belong to ingress admission, and helpers never refresh them or repeat a guest invocation.

An Aggregate query returns `view-version` from that retained view and optional
`key-version` from its single `get(aggregate/count)` observation. Keep both tokens
opaque and distinct. Use the returned original key version for HTTP `If-Match`
and its absence for the explicit absent-key precondition; the namespace view is
not a key precondition. A successful update does not make its original key token
current. Obtain a new authorized query before choosing a new edit, and preserve
the original command and preconditions when recovering an existing operation.

The shared representation uses namespace `transactional-aggregate`, key bytes `aggregate/count`, an eight-byte little-endian unsigned count, media type `application/vnd.lsf.aggregate-v1`, and empty metadata. An absent value means zero; malformed stored bytes are a declared `malformed-state` result. Opaque versions remain byte arrays, and optional values retain presence in every language.

The captured transaction template requests finite ceilings of 4 MiB of state reads, 2 MiB of state writes and 32 staged intents. The host also enforces individual key/value/page/intent limits and its shared staging ledger. These application budgets grant no access; namespace, command/query, result and intent binding authority still require explicit admission. Immediate outbound HTTP remains at a zero budget.

<!-- lsf-example: guest/transactional-aggregate capsule -->

Each facade retains the generated WIT types and the activation's host-issued owners. A command/query owner cannot close while an accepted call or child page remains live. Pages close before their original view. C callback frames retain argument buffers until physical retirement; Rust borrows enforce the same exclusion at compilation; the other facades enforce it through shared owner cells. Disposal releases access without asserting a durable abort or replacing accepted work.

The runtime's narrow clock, entropy, logging and GC imports remain separately authorized. Application HTTP calls and synchronous child calls are immediate effects and require explicit rejection inside strict commands. Exercise them through separately authored negative components, without adding those imports to the transaction profile.

The controlled `forbidden-http` variant adds an actual buffered HTTP import and call to `update`. It uses the same maintained creator, captured SDK, business API and transaction companion. Create it with `python tools/transaction_guest_variants.py --language rust --variant forbidden-http --project ../aggregate-forbidden-http`, substituting `c`, `typescript`, `go`, `java` or `dotnet` as needed. Build and sign it using that language's ordinary recipe, then assert that strict transaction preparation/admission rejects it before application execution. Its loopback URL is synthetic and its HTTP budget remains zero. A compiler receipt proves that the call survived compilation; it does not prove the host rejection or transaction behavior.

The six maintained compiler jobs also run `tools/compile_transaction_guests.py` for both authored variants. With the required pinned tools installed, run `python tools/compile_transaction_guests.py --language rust --output ../transaction-compiler-results`; TypeScript and .NET require their existing `--tools` prefix, and Java requires its pinned `--wasi-sdk` directory. Each result retains the captured source archive, SDK lock, recipe digest, generated binding checks, component identity, actual imports and bounded failure logs. These receipts identify compilation separately from signed node execution and admission rejection; the latter fields remain false until those boundaries are exercised.

Source tool candidates select this template explicitly with `tools/build_dev_guest_tools.py --host-abi lsf-host-abi-phase4-v1`; omitting the option keeps the existing Phase 3 tutorials. The selected profile belongs to the captured compiler inventory, project trust and build receipt. A Phase 4 project requires `artifacts.transactionBinding`, and packaging checks that the bounded, linked declaration is included with identical bytes as a package asset. Installing those compiler inputs does not install a runtime provider or approve namespace access. Its node scenarios require explicit `transactional-state` fixture support, and the portable host rejects this profile.

The source-region manifest covers the six guest implementations. External RPC clients have separate contracts and qualification. The completion matrix must record each component digest, captured source and compiler identity, host/profile, actual signed-node cases, failures and cleanup. Definition feasibility and native type checks do not mark those execution cases passed; historical Phase 3 evidence remains unchanged.
