# Author a C capsule

This is the maintained **C guest** path: your C functions implement a WIT world
inside a Wasm component. It is not the C host/client SDK under `sdk/c`, and it
does not give a capsule sockets, files, credentials or a process. The initial
qualified host is Linux x86-64 with the repository's pinned toolchain.

## Start with source, not an ABI fixture

Work from the repository root. Install the exact versions in
[`tools/toolchain.toml`](../../tools/toolchain.toml): Python 3.13.5, Zig 0.16.0,
wasm-tools 1.254.0, and wit-bindgen 0.62.0. The Rust integration tests additionally
use Rust 1.97.1 and `wasm32-unknown-unknown`. The verified binding installer is:

```sh
python3 tools/install_guest_bindgen.py "$PWD/target/c-guest-tools"
export PATH="$PWD/target/c-guest-tools:$PATH"
python3 tools/c_guest_authoring.py new target/my-greeting --template greeting
```

`new` writes only `component.c`, `c-project.json` and `wit/world.wit`; it never
copies a component, signing key, deployment grant or an accepted binding lock.
The alternatives are `--template word-count` and `--template shipping`.
Output directories must be new, outside source inputs, and under `target/` when
inside this repository. Symlinks, traversal and existing output directories are
rejected. Use a different directory for each subsequent build.

Read the three files. Set `sourceRepository` in `c-project.json` to the explicit
HTTPS repository for **your** source before publishing. The template's value
identifies the repository supplying the example, not a discovered Git origin.
The observer labels this identity `operator-asserted`, records a digest of its
actual input inventory, and does not claim that digest is a Git commit.

Edit the WIT contract first, then implement its generated C exports. Generate
and explicitly review the initial binding identities:

```sh
python3 tools/c_guest_authoring.py bindings --project target/my-greeting --output target/my-greeting-bindings --update
python3 tools/c_guest_authoring.py build --project target/my-greeting --output target/my-greeting-build
```

Inspect `target/my-greeting-bindings/generated/bindings/probe.h` for the exact C
signature. `--rename-world probe` stabilizes the SDK helper include name; it does
not rename the package, interface or exported functions in WIT. Generated
`probe_aliases.h` only aliases names already present in the generated header
when current versions of one platform package coexist. It grants no imports.

Commit `c-bindings.lock.json` with your source. Later `bindings` and `build`
commands fail on drift unless a developer explicitly requests `--update` and
reviews the change. Ordinary builds and CI never update a lock implicitly.
Changing C bodies needs a new build, not a new binding lock. Changing WIT or the
generator requires review of both generated signatures and lock identities.

## Typed export profile

WIT, resolved by the pinned parser, is authoritative for contract descriptors,
including exact interface/package versions and recursively digest-bound types.
The initial user-project profile supports named interface exports, freestanding
functions, primitive values, strings, lists, tuples, options, results and named
records/variants. The full record/variant definition remains in the exact WIT
source lock, not just the legacy descriptor's named projection. The builder
walks nested types and rejects an unsupported type hidden behind an alias.

The initial metadata adapter requires one source file per versioned WIT package.
Exported resource methods, futures, streams, flags and enum types are not part
of this initial adapter profile. Unsupported shapes, unknown capabilities,
recursive/excessively nested types, unknown JSON fields, duplicate keys and
unresolved package associations fail explicitly. Resource-valued **platform
imports** are supported by the generated bindings and the ownership helpers;
that is distinct from allowing resource-valued application exports.

The templates exercise real application contracts:

| Project | Function | Successful call | Declared errors |
| --- | --- | --- | --- |
| greeting | `greet` | `["Kirils"]` yields `[{"ok":"Hello, Kirils!"}]`; UTF-8 is preserved | Empty/NUL-containing names or more than 128 UTF-8 bytes |
| word-count | `count` | `["one two\nthree"]` yields `[{"ok":"3"}]` | NUL-containing text or more than 4096 bytes |
| shipping | `price` | `[{"grams":"1000","express":false,"destination":"DE"}]` yields a EUR quote | Zero weight, unsupported destination or checked integer overflow |

Word count splits runs on ASCII space and ASCII tab/line controls, not on an
unspecified locale. Shipping supports DE/LV, charges 500 cents plus twice the
gram weight (1500 base for express), and returns five days (one for express).
These are teaching rules, not carrier rates. Full-width `u64` values use decimal
strings in `application/vnd.latent.wit-values.v1+json`; the shipping case above
JavaScript's exact integer range is checked without floating-point conversion.
Wrong argument counts and types are boundary failures, not declared domain
errors. The complete reusable cases are
[`projects/cases.json`](../../sdk/c-guest/projects/cases.json).

## From observed build to admitted package

A successful `build` writes:

- `compiled/component.wasm` and the actual generated binding inputs;
- `package-inputs/` containing the exact component, manifest, contracts, WIT lock,
  source packages and a normal `package-source.json`;
- `source-inputs.json`, an unsigned `build-observation.json`, and
  `BUILD-COMPLETE.json` tying the outputs together.

The component is compiled as a freestanding reactor with a 64 KiB stack and the
explicit page-aligned memory ceiling from the project (4 MiB in the templates).
The build checks exact tool versions and executable identities, bounds source
and process output, imposes a deadline, validates the actual component, rejects
ambient WASI, and detects changed observed inputs. Release builds omit debug
sections; those sections previously dominated these small C components.

Use the existing [packaging](packaging.md), [SBOM](sbom.md),
[publisher signing](../reference/publisher-trust.md),
[build provenance](../reference/build-provenance.md), and
[catalog admission](../reference/package-admission.md) interfaces. For an
unsigned structural package inspection:

```sh
cargo run -p latent-packaging --example package --locked -- build target/my-greeting-build/package-inputs/package-source.json target/my-greeting-build/package-inputs target/my-greeting-package
cargo run -p latent-packaging --example package --locked -- inspect target/my-greeting-package
```

This is **not** execution authorization. Add a truthful normalized dependency
inventory, assemble the normal SBOM-bearing package, authenticate the package
under publisher policy, and attest the exact C observation under separately
approved builder policy before publishing. The C build type is
`https://latent.dev/build/c-guest/v1`; the user-project recipe is `compiler:
zig-cc`, `fixture: application`, `target: wasm32-wasi`, `optimization: O2`.
An operator must explicitly approve that profile and the source identity. An
approved Rust builder does not automatically approve a C builder. The recipe
keeps the existing field name `fixture` for compatibility; `application` does
not mean a precompiled fixture was substituted for source.

The observation deliberately reports non-hermetic execution, incomplete
declared dependency inventory and reproducibility not checked. It is unsigned
local evidence until a builder independently authenticates it. The authoring
command never loads production signing credentials, mints a grant, changes a
node policy or runs the component.

## Reproduce the complete local node walkthrough

This qualification uses three newly copied and compiled projects, exact public
packages, fresh ephemeral test signing identities, enforced publisher/builder
and SBOM checks, and distinct CLI/node processes. It has no production keys and
no trusted-local bypass. Native ownership qualification requires `clang` with
AddressSanitizer and UndefinedBehaviorSanitizer.

Use fresh output paths and run:

```sh
python3 -m unittest tools.tests.test_c_guest_authoring
python3 -m tools.c_guest.qualify --output "$PWD/target/c-authoring-projects"
cargo build -p latent -p latentd --all-features --locked
LSF_C_AUTHORING_BUILD_ROOT="$PWD/target/c-authoring-projects" LSF_C_AUTHORING_FIXTURE_ROOT="$PWD/target/c-authoring-fixture" cargo test --locked -p latent-wasmtime --test c_guest_authoring -- --ignored --nocapture
python3 -m tools.c_guest.node --cli "$PWD/target/debug/latent" --node "$PWD/target/debug/latentd" --fixture "$PWD/target/c-authoring-fixture" --output "$PWD/target/c-authoring-node"
```

The exporter reads the actual completion markers, source inventory, component
and observation before normal package assembly/signing/verification. The CLI
then inspects, verifies and publishes those packages, selects the exact returned
publication, applies a finite-budget deployment with compare-and-swap state,
invokes good/domain-error/malformed calls, proves successful reuse after errors,
and removes each deployment. The owned node must shut down cleanly and be
reaped. A missing receipt is a failure, not permission to claim success.

`target/c-authoring-node/receipt.json` records actual component sizes, startup,
deployment-apply and invocation end-to-end timings, owned-process RSS/high-water
observations when `/proc` exposes them, quota return, cell return and cache and
topology ownership. Timings include CLI/control transport, not just guest CPU.
RSS describes the whole node, not the guest's configured memory ceiling. Missing
kernel counters are reported unavailable, never zero. A shared compiled cache
may remain after deployment removal; retained cache ownership is reported
separately rather than being called an activation leak.

## Use a platform capability

Import only the exact interfaces your WIT implementation needs. See the
[guest SDK capability matrix](guest-sdk.md) and the real
[`examples/http.c`](../../sdk/c-guest/examples/http.c) plus its shared
[WIT/profile](../../tools/toolchain-smoke/examples/guest_http/world.wit).
It retains a bounded URL/request/result frame across `latent:http/client@0.2.0`
and returns the response status and body length, or a typed permission/uncertain
outcome. The production-provider test grants the local test origin's `/allowed`
path and separately exercises denial outside it. C code does not turn a URL
into authority, widen a grant, or retry an uncertain request.

Execute that maintained capability pair (and all the others) through signed
admission and the real Wasmtime provider boundary:

```sh
python3 tools/build_guest_capsules.py --output "$PWD/target/c-authoring-capabilities"
LSF_GUEST_CAPSULES="$PWD/target/c-authoring-capabilities" cargo test --locked -p latent-wasmtime --test guest_sdk -- --ignored --test-threads=1
```

The capability tests include both C and Rust against the same WIT and assertions.
Most exercise the actual backend/provider directly; service invocation also
uses the real node activation manager and catalog. The separate-process
walkthrough above is an additional boundary, not a label attached to these
in-process tests. The event test is a bounded TLS protocol peer, not a live
external-broker availability or performance claim.

## Ownership checklist

Read [the C ownership contract](c-ownership.md) before introducing async calls or
resource imports. No helper can make copying a C struct into a valid ownership
transfer. Scopes charge explicitly adopted allocations, not every byte the
canonical ABI or application allocates. The host's linear-memory, fuel, deadline,
capability and activation budgets remain independent and authoritative.

A newcomer review is a merge gate: a reviewer should run the fresh-directory
walkthrough, modify one WIT signature and implement the regenerated C export,
observe the intentional stale-lock failure, and explain the publication/grant
and retained-frame lifetime boundaries. Record that review on the PR; an
automated receipt is not a fabricated human sign-off. The
[implementation journal](../development/c-capsule-authoring-journal.md) records
observed failures and the remaining profile limits.
