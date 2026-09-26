# Registered Rust echo guest

This directory contains registration only, not another guest implementation.
The maintained source and validation instructions remain in the
[echo fixture](../../echo-contract/README.md). The `echo` region surrounds its
existing `Guest` implementation; the only guest-source changes are two comments.

This is a **guest/component** scenario, not a network client or browser example.
The registry intentionally claims source extraction only. Existing phase evidence
is not automatically a matching per-source validation record for this registration.

See [source-backed examples](../../../docs/development/website-examples.md) for
rendering, registration, limits, and the evidence handoff. The website does not
execute the guest, the validation target, or commands from these instructions.
