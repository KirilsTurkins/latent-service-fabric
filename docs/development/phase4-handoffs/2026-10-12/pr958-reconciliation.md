# PR #958: preserve original effect association controls

The original `dee4232bbfd8e12cc119a0e095fa198cfd20a009` snapshot only exposed a
test wrapper around an older private command coordinator. Its #400 issue body
and comments were reviewed against the installed runtime delivered through
#823/#828/#956. That private coordinator no longer owns the current RPC path.

The useful regression is now exercised through the current authenticated effect
management port. Two real atomic commands and their effect rows are committed in
one protected store. The original association succeeds; pairing either original
command with the other effect is denied. Exact command/outbox row bytes remain
unchanged, the original effect stays pending, and actual dispatcher/store owners
complete their normal clean shutdown.

All ten effect-management controls passed on qualified Linux storage, including
the nine previous cases and the new original-row association regression. The CI
inventory retains every previous case and ignore guard and increases the wire
suite requirement from 213 to 214. Current command coverage retains 88 baseline
and 280 required run blocks with 149 delegated owners.

The snapshot is reconciled over #856's delivered head and its current source
owners. #400's full CLI/recovery/saturation acceptance remains separate; no
ticket closes and no public diagnostic wrapper is introduced.
