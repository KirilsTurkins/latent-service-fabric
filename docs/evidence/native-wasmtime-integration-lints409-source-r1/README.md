# Wasmtime integration lint source checkpoint

This checkpoint repairs inherited integration fixture lint sites after the
[original strict Clippy attempt](../native-wasmtime-lints409-r6/clippy-owned-r5.log).
Long cases retain their original ordered assertions through focused helpers;
shared service fixtures reuse one runtime support module. Default values, numeric
policy limits, prepared identities, deadlines, cancellation, provider ownership
and cleanup remain the original inputs. The concurrent service case now includes
its bounded producer diagnostic snapshot in the existing failed assertion.

The [source receipt](receipt.json) freezes every changed source digest and verifies
all 52 affected test names and attributes, every configuration/ignore attribute,
and the unchanged Rust suite catalog. It introduces no lint waiver. Pinned
Rust 1.97.1 formatting, 29 suite/profile cases and read-only CI coverage passed.

Native integration Clippy and execution have not run for these changed test
sources. The root campaign owns the shared native compiler slot. This checkpoint
does not claim a native pass or Java transaction execution; the retained library
qualification has its own earlier source identity.
