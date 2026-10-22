# Local owner-retirement extension

The original crate is bytes 1.12.1, registry archive SHA-256
`fc652a48c352aef3ea3aed32080501cf3ef6ed5da78602a020c991775b0aff04`.
`UPSTREAM.json` records the original file identities and retained MIT license.
The original constructor, vtable, atomics and other source remain unchanged.
The only source addition is `from_owner_with_retirement` and its separate
private vtable; the Cargo manifest additionally registers its allocator test.

The original `from_owner` destroys fields of its owner before freeing the
opaque owner Box. A reservation inside that owner can therefore refund the
last allocation too early. The extension holds the original affine memory
reservation in an inline optional guard alongside the owner. At the last real
reference, it moves only that guard to a local, destroys the owner in its
original stable address, frees the actual Box, then drops the guard. The owner
may be `!Unpin`; the movable guard must be `Unpin`. No extra allocation, ledger,
timer, deferred cleanup or early capacity return is introduced.

The one constructor callback confirms an already admitted reservation after
the Box allocation exists and before the owner view is borrowed or published.
The returned result keeps its existing ordinary execution budget owner as well
as that physical-memory reservation. The original 256-byte owner escrow and
all byte-capacity/refusal/clone/journal assertions remain.

`test_owner_retirement` uses a real allocator observer. It rejects the former
layout through the original constructor, then verifies the new ordering for
stable-address owners, slices/clones, Vec and mutable copies, an empty payload,
eight concurrent final clones and unwinding in confirmation, AsRef and Drop.
It is a native allocation test, not signed guest/runtime qualification. The
dedicated workflow builds only this std-only crate and test; ordinary workspace
checks cover the integrated ResultPayload path.
