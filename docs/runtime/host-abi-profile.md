# Host ABI compatibility profile

Phase 3 starts from one explicit data-only host ABI profile instead of separate
allowlists in packaging and execution code. The current profile is
`lsf-host-abi-phase3-v1`, defined in `latent-core`.

This first profile intentionally contains only the already implemented exact
interfaces:

- `latent:context/context@0.1.0`
- `latent:log/log@0.1.0`
- `latent:clock/monotonic@0.1.0`
- `latent:clock/wall@0.1.0`

Package semantic validation uses the profile to decide whether a declared host
import is recognized, then compares the imported interface against the pinned
repository WIT. The Wasmtime linker setup independently verifies that the
compiled built-in bindings match the same complete profile before publishing an
instance pre-link. Same-name interfaces at a different version are not matched.

The profile describes ABI recognition only. It does not grant a capability,
renew a mutable policy decision, prove that a provider is configured, or create
provider resources. `HostInterfaceBinding::Provider` is reserved for later #202
slices where a recognized Phase 3 interface can be structurally inspected while
preparation still fails closed unless its bounded node-owned provider is
installed.

Adding asynchronous functions, resources, futures or streams requires extending
the bounded semantic comparison first and then publishing an explicit profile
revision. Existing context/log/clock WIT bytes and versions remain unchanged.
Phase 3 provider contracts are therefore still unavailable in this slice.

This boundary preserves the existing resource model: dormant deployments gain
no process, thread, listener, socket, provider instance, pool or execution cell
from ABI recognition alone.
