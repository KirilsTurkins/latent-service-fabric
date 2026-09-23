# Creating a capsule

Build three small programs and run them on your LSF node: greet a visitor,
count words, and calculate a shipping price. Each has its own service name and
purpose. Together they show how to accept input, return an answer and explain
an invalid request.

Complete steps 1–7 of [Run your first node](../start/first-node.md) first.
Keep that terminal open: this tutorial uses its running node, `cli`, `field`
and `answer` helpers. Run commands from the same repository root.

This tutorial uses Rust to write the programs that run inside your node. Each
example below has one Rust implementation. The small `component` section
connects its ordinary Rust function to LSF.

The [client SDK guide](../learn/use-a-client.mdx) offers Rust, TypeScript, Go,
C, Java and C# examples for a different task: calling these programs from an
application outside the node. Those client SDKs do not compile capsules in
all six languages. For lower-level C capsule examples, see the
[C guest examples](../../sdk/c-guest/README.md).

## 1. A greeting capsule

This capsule accepts a name and returns a greeting. An empty name produces a
helpful error instead. Open
[`component.rs`](../../tools/toolchain-smoke/examples/tutorial_greeting/component.rs)
to see or edit the complete implementation:

<!-- lsf-example: guest/tutorial-greeting capsule -->

Its contract says the input is a string and the result is either a string
answer or a string error:

```wit
greet: func(name: string) -> result<string, string>;
```

That line lives in
[`world.wit`](../../tools/toolchain-smoke/examples/tutorial_greeting/world.wit).
The `wit_bindgen` line generates the connection between this contract and the
Rust function. The node uses the same contract to check incoming calls.

## 2. A word-count capsule

This example processes a document instead of greeting a person. It counts
groups of characters separated by spaces, tabs or newlines. An empty document
contains zero words. Very long input returns a readable error.

<!-- lsf-example: guest/tutorial-word-count capsule -->

The [contract](../../tools/toolchain-smoke/examples/tutorial_word_count/world.wit)
returns a whole number on success:

```wit
count: func(text: string) -> result<u32, string>;
```

## 3. A shipping calculator

This capsule accepts two arguments: the number of items and whether the
customer chose express delivery. It returns a price in cents, so `650` means
6.50 units of currency. This tutorial uses a simple example price rule:
500 cents for standard delivery or 1200 for express, plus 75 per item.

<!-- lsf-example: guest/tutorial-shipping capsule -->

The [contract](../../tools/toolchain-smoke/examples/tutorial_shipping/world.wit)
accepts a whole number and a boolean:

```wit
quote: func(items: u32, express: bool) -> result<u32, string>;
```

These programs do not need network access, files, secrets or another running
service. Start here before adding [capabilities](../learn/use-capabilities.md).

## 4. Build the three capsules

```bash
python3 tools/build_tutorial_capsules.py
TUTORIAL_PACKAGES="$PWD/target/tutorial-capsules"
```

Wait for `Ready: greeting`, `Ready: word-count` and `Ready: shipping`.
Each output directory contains:

| File | What it is for |
| --- | --- |
| `component.wasm` | The compiled program that the node runs |
| `capsule.json` | Its name, exported contract and resource limits |
| `contracts.json` | The machine-readable input and output types |
| `deployment.json` | The service name used to reach this program |
| `input.json` | An example call |

The builder fills in the generated identifiers. You do not need to calculate
or copy them. If you already built these examples, choose a fresh directory
with `--output target/tutorial-capsules-second` and set `TUTORIAL_PACKAGES`
to that directory.

## 5. Publish and deploy each program

The following helper repeats the publish and deploy steps from the first-node
guide. It reads the publication returned by your node and puts it into the
deployment file. Run it once per capsule:

```bash
deploy_tutorial() {
    local name=$1 package="$TUTORIAL_PACKAGES/$1"
    cli release publish --manifest "$package/capsule.json" \
        --component "$package/component.wasm" --contracts "$package/contracts.json" \
        >"$RESULTS/$name-published.json"
    python3 - "$package/deployment.json" "$RESULTS/$name-published.json" \
        "$RESULTS/$name-deployment.json" <<'PY'
import json, sys
deployment = json.load(open(sys.argv[1]))
release = json.load(open(sys.argv[2]))["data"]["release"]
deployment["spec"]["release"] = release["digest"]
deployment["spec"]["publication"] = release["publication"]["id"]
with open(sys.argv[3], "x") as output:
    json.dump(deployment, output)
PY
    cli deployment apply "$RESULTS/$name-deployment.json" --expected-generation 0 \
        >"$RESULTS/$name-applied.json"
    printf 'Deployed %s\n' "$name"
}
deploy_tutorial greeting
deploy_tutorial word-count
deploy_tutorial shipping
```

Your one node can now answer calls to all three services.

## 6. Try the inputs and see the answers

Greet Ada:

```bash
cli invoke --service examples/greeting --contract examples:greeting/api@1.0.0 \
    --function greet --activation-id tutorial-greeting \
    --input "$TUTORIAL_PACKAGES/greeting/input.json" >"$RESULTS/greeting-answer.json"
answer "$RESULTS/greeting-answer.json"
```

Expected: `[{"ok":"Hello, Ada!"}]`.

Count the words in `LSF runs small programs`:

```bash
cli invoke --service examples/word-count --contract examples:word-count/api@1.0.0 \
    --function count --activation-id tutorial-word-count \
    --input "$TUTORIAL_PACKAGES/word-count/input.json" >"$RESULTS/words-answer.json"
answer "$RESULTS/words-answer.json"
```

Expected: `[{"ok":4}]`.

Calculate standard shipping for two items:

```bash
cli invoke --service examples/shipping --contract examples:shipping/api@1.0.0 \
    --function quote --activation-id tutorial-shipping \
    --input "$TUTORIAL_PACKAGES/shipping/input.json" >"$RESULTS/shipping-answer.json"
answer "$RESULTS/shipping-answer.json"
```

Expected: `[{"ok":650}]`. To try express delivery, write `[2, true]` into
a new input file and invoke with a new activation ID. The result is `1350`.

Now request zero items to see how an application reports invalid input:

```bash
printf '[0, false]\n' >"$RESULTS/invalid-shipping.json"
cli invoke --service examples/shipping --contract examples:shipping/api@1.0.0 \
    --function quote --activation-id tutorial-invalid-shipping \
    --input "$RESULTS/invalid-shipping.json" >"$RESULTS/invalid-answer.json" || test "$?" -eq 3
answer "$RESULTS/invalid-answer.json"
```

Expected: `[{"err":"Choose between 1 and 100 items."}]`. The node is still
running and can accept the next valid request.

## 7. Change a program

Open the greeting's `component.rs` and change `Hello` to `Welcome`.
Build into a fresh directory:

```bash
python3 tools/build_tutorial_capsules.py --output target/tutorial-capsules-welcome
```

The new `greeting/component.wasm` contains your change. To replace the running
version, continue with [delivery and updates](../learn/deliver-and-recover-a-capsule.md).
A running deployment keeps its previous publication until you explicitly update it.

## 8. Clean up

When you finish, remove the three deployments:

```bash
for name in greeting word-count shipping; do
    generation=$(field "$RESULTS/$name-applied.json" data deployment generation)
    cli deployment delete "tutorial-$name" --expected-generation "$generation"
done
```

You can keep the node running for another tutorial, or return to the
[first-node cleanup](../start/first-node.md#8-continue-or-stop) to stop it.
Your source files and built capsules remain available for the next experiment.
