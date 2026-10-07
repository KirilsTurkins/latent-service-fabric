# Explicit Java recovery recipe v1

This opt-in application recipe keeps `count`, the original `view-version`, and
the absent or present `key-version` as distinct observations. The shared
six-language `transactional-aggregate` example keeps its existing two-field
`count`/`version` result.

`tools/java_transaction_schema.py` selects this recipe explicitly, checks the
closed source/WIT identities in `recipe.json`, and copies `world.wit.in` into
the fresh captured project's `wit/world.wit`. The `.in` file is a recipe input,
separate from repository-wide registered WIT packages. The generated SDK lock
retains its actual source and WIT digests, and the captured project includes
the exact recipe declaration.

The Java source and WIT preserve the original recovery variant bytes. Its
existing package/world spelling does not select or substitute this recipe in
the shared generator: independent compilation, exact artifact association and
the selected publication still determine the actual component contract.

The declaration grants no trust or execution authority. Compiler and signed
node qualification require their own original source-specific process and
execution receipts; these source files do not qualify either boundary.
