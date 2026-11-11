# Standard outbound contract comparison

This work belongs to [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737)
and [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md), separate from
the immutable [#696 investigation](../outbound-streams/README.md).
The [finite profile](../../docs/runtime/outbound-stream-profile.md) proposes
standard runtime networking beneath unchanged dependencies. Production remains
disabled until review and implementation-backed qualification.

Parse/encode the exact comparison WIT with the pinned `wasm-tools`:

```powershell
New-Item -ItemType Directory -Force target/outbound-comparison | Out-Null
wasm-tools component wit research/standard-outbound --wasm --output target/outbound-comparison/profile.wasm
wasm-tools validate --features all target/outbound-comparison/profile.wasm
```

The generated type-only component is ABI evidence, not executing library/socket
evidence. `outbound_proposal_and_wasi_sockets_are_not_ambient_authority` checks the
uninstalled LSF candidate and unknown WASI namespace. Its WASI instance is empty;
that case alone does not compare real socket operation/resource types.

The [original WASI sockets v0.2.0 declarations](wasi-sockets-v0.2.0/UPSTREAM.json)
retain all 15 WIT files and two dependency records from the exact upstream tree,
with original Git blob, SHA-256 and size identities. They are comparison inputs,
not installed adapters or replacements for the LSF contract.

`exact_wasi_tcp_poll_and_stream_resource_types_do_not_install_ambient_ports`
parses that complete package and its own dependencies. It encodes five real
imported interfaces: TCP, network, name lookup, streams and poll. The original TCP
start-connect, finish-connect, subscribe and shutdown methods are required. Each
resulting component must be denied before Store creation or cache installation.
The case preserves unknown-namespace denial while exposing the real resource and
operation signatures; it does not claim adaptation, contact or library execution.

The remaining adaptation gaps are concrete: WASI start/finish/poll owns an
intermediate socket, returns separate input/output streams and borrows pollables;
LSF connect suspends one sealed endpoint attempt and returns a charged connection.
WASI stream/poll resources require their own affine lifetime and partial-transfer
mapping. WASI shutdown has three directions; LSF currently specifies only TCP
send-half-close. Ambient network instances, listen/bind/accept and unsupported
options cannot acquire authority through name substitution. The language ports
and #738 own those mappings and explicit unsupported-operation behavior.

Positive provider evidence belongs to #738. All-six ordinary library execution
belongs to the language ports and #740/#694. Production installation remains
disabled pending architecture/security review and implementation qualification.

## Nonblocking companion proposal

The [owner-decision proposal](nonblocking-v2-decision.md) and its
[companion WIT](nonblocking-v2/package.wit) remain unapproved and uninstalled.
The companion has a different package identity and therefore lives in its own
parse directory. Do not move its WIT back alongside `streams.wit`: parsing this
comparison directory must continue to select only the original v1 package.

From the repository root, with the repository-pinned `wasm-tools` on PATH:

```console
python research/standard-outbound/validate_contracts.py
python -m unittest discover -s research/standard-outbound -p test_validate_contracts.py
cargo test -p latent-wasmtime --test generic_backend --locked -- host_abi::nonblocking::
```

The validator checks `wasm-tools --version` against `tools/toolchain.toml`, then
encodes and validates the original v1 comparison directory. It stages the
companion with an exact copy of the WIT files in `wit/platform/network` as its v1
dependency, encodes it and validates the resulting type-only component. It never
writes dependencies into the source tree or substitutes hand-maintained v1
resource definitions. Each compiler command has a 30-second timeout, and
intermediate artifacts and dependencies are removed on success or failure.

The output directory must be **new**, even when an existing directory is empty.
The first invocation defaults to `target/outbound-contract`; subsequent attempts
must select a fresh path with `--output`, outside the WIT source trees. Existing
artifacts, symlinks and earlier observations are not overwritten. `--wasm-tools`
may select the pinned executable explicitly. Version matching is not binary
authentication; CI's separate checksum-verified installation still applies.

Only after both artifacts validate does the helper publish `v1.wasm`, `v2.wasm`
and `validation.json`. The JSON is also printed in the job log. It records the
observed compiler version, toolchain and input WIT hashes, artifact sizes and
hashes, and the explicit `type-only-contract-validation` evidence kind with
`runtimeQualification: false`. Changed inputs, missing or empty compiler outputs,
nonzero exits and timeouts are failures, not completed observations. A failed
attempt may leave an empty output directory; select a new path for the next run.

The Python tests exercise staging, source protection, tool-version refusal,
command sequencing, fresh-output ownership and failure cleanup with a mocked
compiler. They cannot establish WIT validity. The required `bindings` lane in
`tools/validate_contracts.sh` runs those controls **and** the real pinned compiler;
the `runtime` lane runs the focused Rust tests independently of an earlier
workspace-crate test failure.

The Rust controls parse the committed WIT and verify original v1 type aliases,
owned connect/chunk handoffs, borrowed observations, asynchronous guarded errors,
independent readiness flags and distinct EOF/would-block/elapsed outcomes. A
separate single-interface fixture encodes the companion's full type closure,
including flags, and validates its binary before checking default runtime denial.
Required imports, optional imports and a manifest relabelled as v1 must all fail
before Store creation or cache installation. Cross-package alias identity is
checked by the parser controls, not inferred from this single-interface fixture.

None of these checks installs the companion, widens v1 grants, establishes
physical socket behavior or closes the ordinary-library acceptance gates.
Owner approval and implementation-backed qualification remain required.
