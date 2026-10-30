# latent-stream-factory-native

Private fixed ioctl/descriptor boundary for the selected Linux stream-factory
image. It supplies `mint(&File) -> io::Result<OwnedFd>` to the safe stream provider.
It does not authenticate an image, open a connection, issue a capability grant or
reserve an activation budget. The caller retains the original admitted resource
and precharge throughout the operation and any uncertain cleanup.

The public function exists on Unix; the implementation supports Linux x86_64.
Other Unix targets return `Unsupported`. Non-Unix consumers do not receive a
substitute descriptor or generic syscall interface.

## Architecture and ownership

[src/lib.rs](src/lib.rs) owns the complete boundary:

| Stage | Responsibility |
| --- | --- |
| `validate_original` | Check the character device, root ownership, exact 0600 mode, protected `/` and `/dev`, and identity against `/dev/lsf-stream-factory`. |
| `ffi::Mint` | Describe the single `_IO(0xb7, 1)` request with a zero argument and no userspace pointer. |
| `ffi::mint` | Let rustix handle errno, then adopt only the successful newly installed descriptor as its original `OwnedFd`. |
| Caller | Retain the selected native-factory owner, original budget and quarantined backing until actual retirement. |

The trusted driver returns a new readonly/CLOEXEC descriptor or negative errno.
Descriptor zero is valid. Adoption uses no truncation, `> 0` test or fallible gap
after successful installation. Dropping `OwnedFd` closes the descriptor; it does
not prove that its kernel children, backing bank or Root have retired.

## Trust boundary

The crate denies unsafe code except in its fixed FFI module, whose safety
comments bind the ioctl and ownership assumptions. Callers cannot supply an
opcode, flags, pointer, cost or credential. The selected trusted kernel and
protected device namespace are prerequisites: path/metadata checks do not defend
against a hostile privileged kernel or establish image provenance.

A descriptor or observed counter never authorizes a budget refund. Uncertain
physical retirement keeps the existing owner charged; this leaf cannot mint
replacement authority or turn a timeout into a cleanup proof.

## Integration and verification

[latent-streams](../latent-streams/README.md) consumes the target-specific leaf.
The [kernel accounting contract](../../docs/runtime/outbound-stream-kernel-accounting.md)
separates source derivation, actual constructor execution, final native return
and production installation. The
[constructor VM](../../docs/development/kernel-native-constructor-vm.md),
[Root-return programme](../../docs/development/kernel-native-return-vm.md) and
[bank reclamation](../../docs/development/kernel-bank-reclamation-vm.md) retain
their exact tested sources and remaining boundaries.

The inline Linux test rejects a foreign regular file and checks real descriptor
adoption/drop. It does not execute the custom-kernel mint or qualify retirement.
Use the [registered test workflow](../../docs/development/local-tests.md) to find
the owning suite and prerequisites. [Cargo.toml](Cargo.toml) owns the Linux-only
rustix dependency and narrow lint exception.

See the [workspace index](../README.md) and [security policy](../../SECURITY.md)
for the surrounding implementation and reporting boundaries.
