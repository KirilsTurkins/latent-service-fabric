# Inspect a composition

Check a selected component, HTTP route or typed child before sending application
traffic. This guide uses the Development frontend and operator CLI; install the
pinned [source toolchain](../development/toolchain.md) when your alpha.5 binaries
do not contain these commands.

## Check prerequisites and declarations

`doctor` reads host prerequisites. With a workspace it also observes the selected
node; it does not execute a project recipe:

```bash
latent-dev dev doctor --workspace "$Workspace"
```

Prepare a [composition input](../../schemas/dev-composition-input.schema.json)
with the actual package, component, publication, deployment generation and
contract/function identities. The [support matrix](../development/composition-support.md)
explains supported, unsupported and untested declarations. Then run:

```bash
latent-dev dev preflight --input "$Composition"
latent-dev dev preflight --input "$Composition" --workspace "$Workspace"
```

The first command checks the captured structure and profile definitions. The
second can inspect the provisioned backend and actual preparation through its
authenticated operator. Neither runs or deploys a guest. Definition support,
preparation, live observation and execution are separate result fields. An
unobserved authority field stays unobserved; a package digest grants no access.

## Inspect the exact installed target

For an existing Java HTTP installation, set `Publication` to its real
`publication:sha256:` identity and use the configured tenant administrator CLI:

```bash
latent route target --service examples/java-http-adapter \
  --contract latent:web/application@0.1.0 --function handle \
  --publication "$Publication" --include-preparation
```

Use your actual service, contract and function for a different target. Inspect
the returned publication/revision, deployment and route generations, HTTP
bindings, provider/policy identities and preparation result. `exportCompatible`
and `httpCompatible` describe different surfaces. Multiple canary candidates
without a routing key do not predict a future request's selected revision.

This read starts no application activation. It can perform bounded native
preparation when requested. A target or policy change invalidates the observation;
normal dispatch checks current authority again. See
[target inspection](../reference/target-inspection.md) for bounds and selectors.

## Inspect an actual failure

After sending one controlled request, find the retained roots for its real
service and inspect the returned activation ID:

```bash
latent activation roots --service examples/java-http-adapter --page-size 32 --output json
latent activation tree "$ActivationId" --page-size 32 --output json
```

Follow a returned page token explicitly. Diagnostics describe the producer's
actual stage, reason and available allocation terms; absence remains unknown.
An empty retained page is not proof that no request ran. Do not infer guest
memory exhaustion from a generic allocation failure or infer effect completion
from an activation result. [Activation inspection](../reference/activation-inspection.md)
defines retention, tenant permissions and sanitized fields.

For a lost transactional response, use
[original command recovery](../operations/transaction-recovery.md). Repeating the
request or refreshing its edit precondition cannot resolve its original outcome.
