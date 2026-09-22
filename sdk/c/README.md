# Native C client

The C11 client implements the eight-operation
[common profile](../profile/README.md) over one reusable, bounded, numeric-loopback
HTTP/2/protobuf connection per owner. All RPCs use `latent_profile_client_vtable`;
the obsolete invocation-only vtable and compatibility header have been removed.

## Support matrix

| Surface | Delivery / qualification |
| --- | --- |
| `<latent/profile.h>` | Existing complete eight-operation DTOs and callback interface; unchanged by this transport |
| `<latent/types.h>` | Shared length-delimited strings, bytes and key/value pairs |
| `<latent/transport.h>` | Constructor, explicit configuration, event-loop polling, usage and physical stop/shutdown |
| Invoke / Cancel / GetActivation | HTTP/2 unary RPCs, three invocation outcomes, three cancellation dispositions and original-ID recovery |
| GetPolicy / ListPolicies / ListCapabilities | Policy and redacted provider inspection; bounded single-page requests |
| ApplyPolicy / GetPolicyOperation | Explicit generation and operation identity, observed receipt and manual replay recovery |
| Native platform | Linux x86-64; tested with Debian GCC 12.2.0 and glibc 2.36, including ASan/UBSan |
| Other platforms | Windows, macOS, other architectures and TLS/remote endpoints are not qualified; the build rejects non-Linux/non-x86-64 hosts |
| Real-node participant | Native `provider-workflow` implements the shared 18-assertion protocol; execution evidence is separate from focused peer tests |
| Guest bindings | Separate [C guest SDK/fixtures](../c-guest/README.md); this library runs outside the node |

See [evidence](EVIDENCE.md) for executed checks and the separate-node qualification
boundary. The shared SDK runner and top-level support matrix are integration-owned;
the C-only validation entry point below does not edit or replace them.

## Build and link

Use a Linux x86-64 development environment with a C11 compiler, binutils (`ar`),
GNU make, POSIX build utilities and Python 3.12 or newer. The exercised environment
uses Python 3.13.5. No system packages, Python environment or host toolchain are
modified by the C build.

From the repository root:

```sh
python3 sdk/c/tools/validate.py --build-dir target/c-sdk
python3 sdk/c/tools/validate.py --build-dir target/c-sdk-asan --sanitize
```

`validate.py` runs C tooling tests, builds the library/examples, regenerates the
official bindings into a second temporary directory and compares them, then runs
the semantic, wire, private-config and controlled TCP tests. All subprocess waits
are finite. First build requires HTTPS access to the hash-pinned artifacts in
[`dependencies.lock.json`](dependencies.lock.json). Later builds verify the cached
archives. Use a fresh build directory when changing dependency pins. `CC` may name
an explicit compiler executable; no compiler installation is attempted.

The outputs are `liblatent.a`, `libnghttp2.a`, `provider-client`, and
`provider-workflow`. The public headers have no nghttp2/nanopb dependency. Link a
consumer with:

```sh
cc -std=c11 -Isdk/c/include your_client.c \
  target/c-sdk/liblatent.a target/c-sdk/libnghttp2.a -o your_client
```

Only libc and the normal ELF loader are dynamic dependencies of the exercised
non-sanitized example. The client needs no Python, Rust, C++, Node, nghttp2 command
line application or Protobuf C++ runtime. nghttp2 is built `--enable-lib-only` as
static C; nanopb's three C runtime files are included in `liblatent.a`.
See [dependency review](DEPENDENCIES.md) for exact versions, source bindings,
licenses and advisory coverage limitations.

Generation is private to `target/c-sdk/generated`: pinned official `protoc`
produces descriptors from the selected authoritative `.proto` files, and pinned
official nanopb produces C message descriptors. The C generator derives field
offsets, presence, oneof validation and RPC paths from those descriptors and the
common profile. It does not regenerate or edit the public profile models.
All fields use bounded callback storage, oneofs use separate storage, and enum
wire values use compatible signed i32 storage. Generation and runtime share the
same nanopb pin and `PB_MESSAGE_NESTING_MAX=16` configuration.

For focused iteration after a build:

```sh
python3 sdk/c/tools/test.py --build-dir target/c-sdk
python3 sdk/c/tools/audit_dependencies.py \
  --graph target/c-sdk/dependency-graph.cdx.json \
  --report target/c-sdk/dependency-audit.json
```

## Calling the client

Include `<latent/transport.h>`. Start with `latent_transport_defaults()`, then set
all of `endpoint`, `tenant`, and `bearer_token` explicitly. For example, use a
numeric endpoint of the form `http://127.0.0.1:PORT` or `http://[::1]:PORT` and read
the client token from a private file. There is no environment, home-directory,
anonymous-authentication or provider-credential fallback.

1. Call `latent_transport_create(&config, &owner, &failure)`; it copies endpoint,
   tenant and token before returning and opens no socket yet.
2. Obtain `latent_transport_profile(owner)` and
   `latent_transport_profile_vtable()`. Zero-initialize request/result records;
   populate every required `has_*` flag explicitly.
3. Call any of the eight methods with a valid callback and live user data. Inputs
   and nested data are copied/encoded before return. A NULL handle means its
   failure callback has already run; otherwise retain the local handle.
4. Drive `latent_transport_poll(owner, wait_millis)` from the same serialized
   caller thread. `wait_millis` is at most 1000 and is shortened to the original
   deadline. Copy response values inside the callback, then release the handle
   with `release_call` **after the callback returns**.
5. Use `cancel_local(handle)` to stop a local wait, not to issue a remote Cancel.
   An explicit Cancel request uses the activation ID and its own finite budget.
6. Call `latent_transport_shutdown(owner, timeout_millis)`, release every remaining
   completed handle, and require `latent_transport_destroy(owner)` to return true.

Callbacks may run inline, including admission/allocation failure and stop. They
must return promptly. Getters return borrowed views of one owner, not separately
owned clients. Every returned call handle requires explicit release after its
callback returns. [Transport contracts](TRANSPORT.md) describe reentrancy, exact bounds,
deadlines, collateral connection retirement and all lifetime preconditions.

## Clean-checkout authorized HTTP/blob example

The example requires the repository's
[pinned node/guest toolchain](../../docs/development/toolchain.md), including the
guest build tools. This is deliberately a controlled local development workflow,
not an installed-node or production credential bootstrap. It uses three actual
signed Rust HTTP/blob/callee guest components. The C process receives only a
private **client** credential and exact deployment targets; it never reads the
upstream credential, provider bootstrap, signing keys or node state.

Run from a clean checkout on the supported Linux environment:

```sh
set -eu
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/target}"
python3 sdk/c/tools/validate.py --build-dir "$PWD/target/c-sdk"
python3 tools/build_guest_capsules.py --output "$CARGO_TARGET_DIR/guest-capsules"
cargo build -p latent -p latentd --locked
fixture_parent="$(mktemp -d)"
LSF_GUEST_CAPSULES="$CARGO_TARGET_DIR/guest-capsules" \
LSF_PHASE3_WORKFLOW_FIXTURE_ROOT="$fixture_parent/inputs" \
  cargo test -p latentd --test phase3_workflow_fixture --locked -- \
    export_signed_provider_workflow_fixtures --exact --ignored --nocapture
python3 tools/run_sdk_provider_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$fixture_parent/inputs" --language c \
  -- "$PWD/target/c-sdk/provider-workflow"
```

The shared harness prepares and owns the real node, separate controlled upstream,
authenticated operator setup and private 0700/0600 input. It appends
`--config /absolute/private/input.json` to the **native C executable**. The C
participant makes every SDK RPC through this library; setup CLI use is not a
transport implementation. Fresh signing evidence expires: export immediately
before running. The harness stops/reaps its processes and private working
directories even on failure. The explicitly selected `fixture_parent` remains
for inspection and can be removed after no run uses it.

`examples/provider_client.c` is the smaller two-call embedding example. For an
already prepared controlled node, supply a private input with the same
[input schema](../../docs/testing/sdk-provider-workflow.md#participant-input):

```sh
target/c-sdk/provider-client --config /absolute/private/input.json
```

On checked HTTP/blob success it emits `{"http":"2201","blob":"4"}`. It is not
an 18-assertion harness participant. Both examples preserve the supported WIT
argument framing (`[0, URL, "0"]`, `[0, "", "0"]`) and parse returned u64 decimal
strings without floating-point or lossy JSON integer conversion. The general
library treats payload bytes as opaque.

The full participant uses at most 5000 ms RPC deadlines, 3000 ms held calls and
a 500 ms explicit deadline case. Four distinct held invocations must reach the
upstream's started marker, physically closed marker and retained terminal
activation status. No local cancellation is reported as proven guest cleanup.
All current policy acknowledgements must be absent, so its result contains
`auditAttempt:null`. It prints the 18 true flags only after executing their
checks; compilation or controlled-peer success is not real-node evidence.
