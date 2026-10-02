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

`update` reads the unsigned aggregate, checks overflow, stages its new value and an `approved-event` intent, and returns the staged version. The host commits the writes, intent and original result together after successful validated guest completion. With `reject` set, the same guest returns the declared `rejected` business error after staging; the host preserves that terminal rejection while discarding the business writes and intent. Host failures remain platform failures.

`query` acquires a fresh read-only view. `scan` opens a bounded page and pulls entries while retaining its original view; it returns the page view identity and optional continuation cursor. No query has a command key or a mutation API. Caller command identity, stale-edit preconditions and minimum read-after-commit version belong to ingress admission, and helpers never refresh them or repeat a guest invocation.

The shared representation uses namespace `transactional-aggregate`, key bytes `aggregate/count`, an eight-byte little-endian unsigned count, media type `application/vnd.lsf.aggregate-v1`, and empty metadata. An absent value means zero; malformed stored bytes are a declared `malformed-state` result. Opaque versions remain byte arrays, and optional values retain presence in every language.

The captured transaction template requests finite ceilings of 4 MiB of state reads, 2 MiB of state writes and 32 staged intents. The host also enforces individual key/value/page/intent limits and its shared staging ledger. These application budgets grant no access; namespace, command/query, result and intent binding authority still require explicit admission. Immediate outbound HTTP remains at a zero budget.

Transaction projects reserve at least 32 MiB of activation memory and 30 seconds of wall time. The original activation pays for the bounded 11 MiB state/session ledger and the 8 MiB plus 16 KiB response/frame envelope as well as guest memory. The captured Go and Java profiles retain their 64 MiB ceilings; TypeScript and .NET retain 128 MiB. A preparation cache can warm code before admission. A cold preparation that outlives the original state view must abort without refreshing that view or replaying the guest.

<!-- lsf-example: guest/transactional-aggregate capsule -->

Each facade retains the generated WIT types and the activation's host-issued owners. A command/query owner cannot close while an accepted call or child page remains live. Pages close before their original view. C callback frames retain argument buffers until physical retirement; Rust borrows enforce the same exclusion at compilation; the other facades enforce it through shared owner cells. Disposal releases access without asserting a durable abort or replacing accepted work.

The runtime's narrow clock, entropy, logging and GC imports remain separately authorized. Application HTTP calls and synchronous child calls are immediate effects and require explicit rejection inside strict commands. Exercise them through separately authored negative components, without adding those imports to the transaction profile.

The controlled `forbidden-http` variant adds an actual buffered HTTP import and call to `update`. It uses the same maintained creator, captured SDK, business API and transaction companion. Create it with `python tools/transaction_guest_variants.py --language rust --variant forbidden-http --project ../aggregate-forbidden-http`, substituting `c`, `typescript`, `go`, `java` or `dotnet` as needed. The supported HTTP signature prepares normally. After staging its aggregate value and intent, the controlled guest returns the declared `rejected` result only for the exact typed HTTP `permission-denied` error; success or another error traps. The native schedule sends `reject=false`, installs a real approved HTTP provider, requires its start counter to remain zero, and checks durable rejection, zero state/outbox rows, a fresh zero query and physical retirement. Its loopback URL is never contacted when the transaction gate works. A compiler receipt proves that the call survived compilation; it does not prove these execution cases.

The six maintained compiler jobs also run `tools/compile_transaction_guests.py` for both authored variants. With the required pinned tools installed, run `python tools/compile_transaction_guests.py --language rust --output ../transaction-compiler-results`; TypeScript and .NET require their existing `--tools` prefix, and Java requires its pinned `--wasi-sdk` directory. Each result retains the captured source archive, SDK lock, recipe digest, generated binding checks, component identity, actual imports and bounded failure logs. These receipts identify compilation separately from signed node execution and admission rejection; the latter fields remain false until those boundaries are exercised.

The native manager campaign requires complete observed packages, using the same full build owners as ordinary editable projects:

```bash
cargo build --locked -p latent-packaging --example capsule_contracts --example transaction_package
python tools/prepare_transaction_guest_packages.py --language rust \
  --output ../transaction-native-rust \
  --contracts-tool target/debug/examples/capsule_contracts \
  --packager target/debug/examples/transaction_package
LSF_TRANSACTION_GUEST_DIR=../transaction-native-rust LSF_GUEST_SDK_LANGUAGE=rust \
  LATENT_STATE_TEST_ROOT=/approved/private/ext4-directory \
  cargo test --locked -p latent-wasmtime --test transaction_guests -- --ignored --test-threads=1
```

Select the other language and its pinned tools in separate fresh output directories. TypeScript and .NET use `--tools`; Java uses `--wasi-sdk` and can select `--gradle-cache`; Go can select `--go-cache`. Rust and .NET support their maintained `--offline` option. The explicit `transaction_package` tool selects the frozen Phase 4 manifest profile; the existing `package` tool retains its stateless default. Source capture, compiler deadlines, independent build observations and package limits retain their original owners. Compatibility reports continue to leave initialization and retirement unproven after compilation.

The direct native fixture verifies the original completed observation, source files and package inputs again, embeds a truthful declared-input SBOM, and signs the resulting package with separately generated publisher and builder test keys. The enforced catalog checks those proofs against a scoped test operator policy and the actual detected runtime profile. Public policy, signature/provenance envelopes and original input identities are retained under `native-evidence`; private keys remain ephemeral. This campaign uses a fixed trusted test admission instant. Installed Standalone distribution, its production clock sampler and ordinary RPC transport require separate qualification, and no preparation or signing receipt marks those gates complete.

Source tool candidates select this template explicitly with `tools/build_dev_guest_tools.py --host-abi lsf-host-abi-phase4-v1`; omitting the option keeps the existing Phase 3 tutorials. The selected profile belongs to the captured compiler inventory, project trust and build receipt. A Phase 4 project requires `artifacts.transactionBinding`, and packaging checks that the bounded, linked declaration is included with identical bytes as a package asset. Installing those compiler inputs does not install a runtime provider or approve namespace access. Its node scenarios require explicit `transactional-state` fixture support, and the portable host rejects this profile.

The source-region manifest covers the six guest implementations. External RPC clients have separate contracts and qualification. The completion matrix must record each component digest, captured source and compiler identity, host/profile, actual signed-node cases, failures and cleanup. Definition feasibility and native type checks do not mark those execution cases passed; historical Phase 3 evidence remains unchanged.
