# Update and restore a capsule

Change the greeting capsule from `Hello, Ada!` to `Welcome, Ada!`, deploy the
new version, then restore the original. You will see that building a program
and selecting the program that serves requests are separate steps.

Complete [Creating a capsule](../component-development/creating-a-capsule.md)
through step 6 first. Keep its node and terminal running. This guide uses the
same `cli`, `field` and `answer` helpers, the `RESULTS` directory and the original
`TUTORIAL_PACKAGES` directory. Leave `TUTORIAL_PACKAGES` pointing to the original
build so it remains available for restoration.

## 1. Save the current deployment

```bash
cp "$RESULTS/greeting-deployment.json" "$RESULTS/greeting-original.json"
cp "$RESULTS/greeting-applied.json" "$RESULTS/greeting-before-update.json"
CURRENT_GENERATION=$(field "$RESULTS/greeting-applied.json" data deployment generation)
```

The saved deployment names your original publication. The generation is the
version of the deployment you last changed. Supplying it in the update prevents
you from overwriting another person's intervening change.

## 2. Change and build the program

Open
[`component.rs`](../../tools/toolchain-smoke/examples/tutorial_greeting/component.rs)
and change `Hello, {name}!` to `Welcome, {name}!`. Build into a fresh directory:

```bash
python3 tools/build_tutorial_capsules.py --output target/tutorial-capsules-welcome
WELCOME_PACKAGE="$PWD/target/tutorial-capsules-welcome/greeting"
```

If you already built this version in the previous tutorial, skip the build
command and set `WELCOME_PACKAGE` to that existing greeting directory.
Otherwise wait for the three `Ready:` messages. The builder rebuilds all three
examples; this walkthrough changes only the greeting deployment.

The node still serves the original version. A source edit and build do not
change its publication or routing.

## 3. Publish the new version

```bash
cli release publish --manifest "$WELCOME_PACKAGE/capsule.json"     --component "$WELCOME_PACKAGE/component.wasm"     --contracts "$WELCOME_PACKAGE/contracts.json"     >"$RESULTS/greeting-welcome-published.json"
```

Prepare a deployment selecting the returned publication. This small script
keeps the service name and other settings from your original deployment:

```bash
python3 - "$RESULTS/greeting-original.json"     "$RESULTS/greeting-welcome-published.json" "$RESULTS/greeting-welcome.json" <<'PY'
import json, sys
deployment = json.load(open(sys.argv[1]))
release = json.load(open(sys.argv[2]))["data"]["release"]
deployment["spec"]["release"] = release["digest"]
deployment["spec"]["publication"] = release["publication"]["id"]
with open(sys.argv[3], "x") as output:
    json.dump(deployment, output)
PY
```

## 4. Switch the deployment and call it

```bash
cli deployment apply "$RESULTS/greeting-welcome.json"     --expected-generation "$CURRENT_GENERATION"     >"$RESULTS/greeting-welcome-applied.json"
WELCOME_GENERATION=$(field "$RESULTS/greeting-welcome-applied.json" data deployment generation)
cli invoke --service examples/greeting --contract examples:greeting/api@1.0.0     --function greet --activation-id tutorial-welcome     --input "$TUTORIAL_PACKAGES/greeting/input.json"     >"$RESULTS/greeting-welcome-answer.json"
answer "$RESULTS/greeting-welcome-answer.json"
```

Expected: `[{"ok":"Welcome, Ada!"}]`.

The service name and function contract stayed the same. Only the selected
publication changed. A request already in progress keeps its selected revision;
new requests use the updated deployment.

If the generation conflicts, stop and inspect the current deployment with
`cli deployment get tutorial-greeting`. Another change may have occurred. Do not
remove the precondition or repeatedly increase the generation to force an update.

## 5. Restore the original version

Apply the saved original deployment, using the generation returned by the update:

```bash
cli deployment apply "$RESULTS/greeting-original.json"     --expected-generation "$WELCOME_GENERATION"     >"$RESULTS/greeting-applied.json"
cli invoke --service examples/greeting --contract examples:greeting/api@1.0.0     --function greet --activation-id tutorial-restored     --input "$TUTORIAL_PACKAGES/greeting/input.json"     >"$RESULTS/greeting-restored-answer.json"
answer "$RESULTS/greeting-restored-answer.json"
```

Expected: `[{"ok":"Hello, Ada!"}]`. Restoration creates another deployment
generation; it does not turn back the node's history. The original publication
must remain available and eligible. This local exercise does not use the staged
rollout coordinator; [managed rollouts](../phase-2-rollouts.md) add staged
traffic and retained operation recovery.

## If a response is lost

A lost response does not prove that the update failed. Read
`cli deployment get tutorial-greeting` and inspect the current selected
publication and generation before choosing another action. That read shows
current state, not a complete history of what happened.

This tutorial uses simple object-generation preconditions. For administrative
changes needing an exact retained result, use
[managed deployment operations](../phase-2-operator-workflows.md#managed-deployment-receipts)
with a caller-retained operation ID and catalog state version. Query that original
operation after a timeout. An unknown retained result must stay unknown; do not
invent another operation ID to discover whether the first one committed.

For a lost invocation response, query the original activation ID. Repeating
`invoke` could run the function again. See [client recovery](use-a-client.mdx).

## Finish and continue

The restored response is saved in `greeting-applied.json`, so the
[three-capsule cleanup](../component-development/creating-a-capsule.md#8-clean-up)
uses the current generation. Follow it to remove the deployments, then stop the
[first node](../start/first-node.md#8-continue-or-stop) when finished.
Your source still says `Welcome`; change it back if you want later builds to
produce the original greeting.

The local learning node accepts capsules you build yourself. For delivery between
systems, continue with [packaging](../component-development/packaging.md),
[publisher trust](../reference/publisher-trust.md) and
[package admission](../reference/package-admission.md). Those steps add package
verification and policy; uploading bytes alone does not establish trust.
