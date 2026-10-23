# Original capability handle and copied-buffer memory

Both ordinary and pending-clock handle births now prepay the original shared row,
Arc headers, private billing owner and all resource-owned strings before copying
or allocating. Shared strong/weak storage keeps the same memory ledger charged
until physical retirement. Legacy sessions retain their existing admission path.

`Work` input copies and `OwnedCapabilityResponse` byte copies reserve their
physical Vec capacity before allocation. Reply admission includes simultaneously
live input and output. The inline affine owner zeroes and frees the backing before
its memory reservation drops, including closed-session, cross-thread and unwind
paths. These owners retain physical memory without creating another ordinary
execution-accounting owner.

The [actual native job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39878219065/job/120168986663)
passed all 188 controls on `c802283a5546620f071bd02ec01c410696893c5b`.
The programme preserves the original 177 selectors and adds six handle controls
and five copied-buffer controls. Independent verification checked 179 CRC
members, 85 exact commands, 170 stream identities, 150 source materials and all
five native products. The normal build authenticated the selected local Bytes
fork first. The [additive observation](evidence/host-codec-handle-buffer-native-2026-10-23.json)
and immutable `tools/host_codec_handle_buffer_native_products.py` retain this
exact workflow-dispatch origin; the earlier 177-control observation is unchanged.

This is native ownership evidence. It does not execute a signed guest or qualify
whole-cost or whole-runtime requirements. Audit/journal queues and persisted
metadata, transitive provider and transport graphs, ingress, shared preparation,
and full pressure/retirement qualification remain outstanding.
