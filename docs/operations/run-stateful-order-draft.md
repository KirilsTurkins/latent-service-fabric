# Run a stateful order draft

Use the Development tools and a Linux x86-64 execution host. The node needs the
protected state store and checkpoint, enforced supply-chain policy, audit owner,
and current capability policies. Use a separate test namespace and the
[installed transaction configuration](../development/installed-transaction-rpc.md).
For tools and a local or remote Linux build host, follow the
[development workspace setup](../start/development-workspace.md).

## Create and admit the guest

From the LSF source checkout, set `GuestLanguage` to `rust`, `c`, `typescript`,
`go`, `java`, or `dotnet`. The creator writes an editable project outside the
checkout, with the selected language's captured SDK and the common order-draft
schema.

```bash
python tools/stateful_reference_project.py \
  --language "$GuestLanguage" --draft-id alice --output "../order-draft-$GuestLanguage"
python tools/stateful_reference_project.py \
  --language "$GuestLanguage" --draft-id bob --output "../order-draft-bob-$GuestLanguage"
```

Use the [guest authoring workflow](../component-development/transactional-authoring.md)
for the selected compiler, package, signing and admission steps. Install each
build's actual publication and signed transaction companion. For the two
deferred notifications, set `--http-profile` and `--event-profile` to the
qualified adapter profiles observed from the node when creating the project.
Install the separate staging and dispatch policies for the
[HTTPS recipient](../development/deferred-http-installation.md) and
[JetStream publisher](../development/deferred-jetstream.md).

Prepare each admitted backend before opening the browser. Set `Publication`
to its admitted publication ID. Read the lifecycle generation and use the
returned value for `GuestGeneration` in the preparation request. Repeat for
Bob's backend.

```bash
latent --phase4 release lifecycle --publication "$Publication"
latent --phase4 --rpc-timeout-ms 120000 release prepare \
  --publication "$Publication" --lifecycle-generation "$GuestGeneration" \
  --maximum-wait-ms 120000
```

Expect a prepared response for that publication. Preparation uses the current
node profile and leaves command execution to the authorized ingress route.

Use the [reference deployment workflow](../../examples/stateful-reference/README.md)
to derive the shared ingress routes from the signed companion and actual
publication, revision and generation. The
[transaction HTTP binding](../development/transaction-http-v1.md) defines the
command, query and original-result routes and their separate permissions.

## Install the signed Angular frontend

Use the [Angular build recipe](../development/angular-build-evidence.md) with
`examples/stateful-reference/angular` as the input root. Sign the assembled
frontend and the two completed guest builds with
`capsule_authoring demo-sign-stateful-reference` for a disposable node. Publish
the frontend with `latent web publish` and deploy it as `stateful-reference`
with the approved Angular renderer budget and one outbound HTTP request.

Keep the two read credentials in the protected HTTP provider configuration.
Each origin uses a separate static loopback destination and an independently
authorized GET on its draft's query path. The outbound policy ceiling must
cover the installed provider's bounded response body, header copies and
response framing. Keep two execution cells available for a renderer and its
upstream query on the shared listener.

Pass the frontend's current publication, revision and deployment generation
to `--renderer-selection` in the reference deployment helper and apply the
emitted GET and HEAD triggers. Prepare the approved publication on the
running node before opening the page. Read its lifecycle generation with
`latent web get`.

```bash
latent --phase4 --rpc-timeout-ms 120000 web prepare \
  --publication "$FrontendPublication" --lifecycle-generation "$FrontendGeneration" \
  --maximum-wait-ms 120000
```

## Create the namespace and submit a draft

Start the node with the signed operation installed. Set `Publication` to its
actual authorization publication, `CreateOperationId` to a unique operation ID,
and `NamespaceConfig` to the bounded schema and quota configuration for
`order-drafts-alice`. Use the signed companion's state schema and quotas within
the limits granted to the installed tenant.

```bash
latent --phase4 state create \
  --namespace order-drafts-alice --incarnation 1 \
  --authorization-publication "$Publication" --operation-id "$CreateOperationId" \
  --expected-generation 0 --configuration "$NamespaceConfig"
```

Repeat with the installed Bob publication, its configuration for
`order-drafts-bob` and a fresh operation ID. If a create response is lost,
recover that same operation via
`latent --phase4 state operation` with the same namespace, incarnation,
publication and operation ID. After successful creation, stop the node cleanly
and restart it with the same installed configuration. Readiness captures the
actual namespace and current deployment. Inspect it with
`latent --phase4 state inspect` and the same namespace selector.

Open the installed draft application with Alice's authorized credential.
Change the units and choose **Save draft**. The command records the original
screen revision. A committed update changes both state keys and stages two
notification intents. A fresh query displays the new revision. Open the draft
in two tabs before saving to exercise a stale edit. After the first tab commits,
the second tab's original revision can conflict. Use a fresh query before
choosing a new edit.

Select **Reject this edit** before saving to exercise a durable business
rejection. Check that the revision and units stay the same and the original
command has an empty effect list. Recover that command again after another
authorized edit changes the draft. The result route returns the original
rejection.

## Recover the original result

If the command response is lost, choose **Recover original command** before
editing again. The [reference browser journey](../../examples/stateful-reference/README.md)
can exercise this by dropping delivery of a real node response. Recovery uses
the same command identity through the application's result route and rechecks
the current caller. The same authorized subject can recover after credential
rotation. A different user in the tenant needs an explicit delegation.

When the result includes effect IDs, choose **Check effect status** with the
required current permission. A provider acknowledgement describes the
notification's dispatch disposition. For the original command, inspect the
commit and effects separately. [Transaction recovery](transaction-recovery.md)

External applications can run the same command, fresh query and lookup on the
maintained client transport. Select the language-specific SDK from the
[transaction clients](../development/transaction-clients.md) and keep the
original request and preconditions through cancellation or response loss.

When finished with the test namespace, quiesce it using its observed generation.
Inspect outstanding effects and durable commands before retiring it. Keep the
state and checkpoint together when stopping the node. [Operator recovery](transaction-recovery.md#choose-operator-actions-deliberately)
