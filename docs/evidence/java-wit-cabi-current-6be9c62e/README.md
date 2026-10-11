# Current Java model bridge to retained actual WIT/C ABI evidence

At source `6be9c62e6ef363e4057e12db110ba31c50c86104`, the current Java graph and
Java/C generators execute against the retained original actual parser and C ABI
outputs for all nine minimized cases. All 38 command logs and the unchanged
fixture inventory are rehashed. The source digest remains
`sha256:266dd9e794b89475d6391270adee411b52affdc0ec011a299794b64ded890a37`.

Both supported cases, `shared-types` and `inclusion`, reproduce both original
Java and C outputs byte for byte. Multiple exports, aliases, versions, names,
public resource exports and futures retain their exact unsupported-profile
refusals. The malformed case remains tied to the original actual parser
rejection; that parser produced no graph to execute again.

[The current receipt](verified-current-model-bridge.json) records the original
actual outputs, current model execution and exact comparisons. Its SHA-256 is
`6ea58430b5c515de25f4618a81f18ea843e766a8c906d33ea188d2d385ee87d5`.
The [preceding bridge](original-retained-bridge.json),
[original verifier source](original-review.py.txt) and generated Java/C text
remain separately retained under the [exact file inventory](original-files.json).

The actual parser and C ABI generator were not rebuilt or rerun for this source
bridge. Original hosted run `36778196735` retains its failed aggregate outcome.
The original parsed inputs and byte-identical outputs support the current model
comparison; they establish neither a new guest execution nor full current CI.
