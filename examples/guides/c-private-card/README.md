# Fetch a price card from a private C worker

The capsule calls a developer-owned card library. A second library starts a
pthread, calls libfetch on that thread and joins it before returning the card.
The card library reads its expected identifier and name from a captured
16-byte resource. The application returns the identifier, name length,
response length and checksum.

Use the installed Linux C toolkit. Set `C_TOOLS` to its absolute installation
directory and `EXAMPLE` to the absolute path of this example. Create the
project outside the checkout.

```sh
work=$(mktemp -d)
py="$C_TOOLS/sdk/bin/python"
cli="$C_TOOLS/recipe/tools/c_capsule.py"
"$py" -I -B "$cli" new "$work/app" --template greeting --name c-thread-runtime \
  --threading-profile c-context144-sync-cooperative-v1
cp -R "$EXAMPLE/application/." "$work/app/"
cp -R "$EXAMPLE/libraries" "$work/libraries"
"$py" -I -B "$cli" resolve "$work/app" --candidate "$work/card.lock"
```

Read `card.lock` and check the identities, dependency edges and selected
resource. Accept the bytes you reviewed and verify the capture.

```sh
lock_digest=$(sha256sum "$work/card.lock" | cut -d ' ' -f 1)
"$py" -I -B "$cli" review-lock "$work/app" --candidate "$work/card.lock" \
  --expect "sha256:$lock_digest"
"$py" -I -B "$cli" dependencies "$work/app"
```

Move the example's copied library directory out of its declared path. The
installed compiler can now build using the reviewed capture.

```sh
mv "$work/libraries" "$work/originals-removed"
mkdir "$work/build-cache"
"$py" -I -B "$C_TOOLS/recipe/tools/dev_guest_recipe.py" \
  --language c --project "$work/app" --output "$work/output"
```

The compiler writes `component.wasm` and its build receipts under
`$work/output`. Deployment requires the `c-libfetch-clock-entropy-v1`
runtime profile and an HTTP grant for the chosen destination. In the signed
test, the peer served a 57-byte price card. The capsule returned
`card:7:5:57:1776131770`. Each of the three runs made one GET, and the node
reported zero physical owners after each invocation.
[Signed executions and measured usage](../../../docs/testing/evidence/c-private-pthread-library-2026-11-24.json)
