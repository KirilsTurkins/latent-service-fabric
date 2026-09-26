# How a capsule becomes a running service

You write a capsule, publish it to a node, and deploy it under a service name.
Each call to that service creates a new activation. These names describe
different steps, which matters when you update a program or recover a lost
response.

## Follow one greeting request

Imagine a capsule with a `greet` function that returns `Hello, Ada!`:

1. **Build the capsule.** The result is a WebAssembly component and its contract:
   a description of the inputs and outputs.
2. **Publish it.** The node checks the submitted program and returns a
   **publication ID**. That ID identifies this admitted publication in your tenant.
3. **Deploy it.** A deployment associates a service such as `examples/greeting`
   with the publication that should answer its calls.
4. **Invoke it.** A caller asks for `greet("Ada")`. Routing selects the deployed
   publication, and an **activation** runs the function with fresh guest state.
5. **Return and clean up.** The caller receives the answer; the node reclaims
   the activation's resources. The deployment remains available for another call.

The [first-node walkthrough](../start/first-node.md) lets you try this sequence
with an echo function. [Creating a capsule](../component-development/creating-a-capsule.md)
adds the greeting example.

## The identifiers you keep

| Identifier | What it tells you | When you need it |
| --- | --- | --- |
| Component checksum | Which compiled program bytes you have | Checking an artifact or diagnosing a mismatched build |
| Package checksum | Which complete package, including its metadata and assets, you have | Signing, transfer and package inspection |
| Publication ID | Which admitted publication belongs to a tenant | Selecting a program for deployment or changing its lifecycle |
| Deployment name | Which configured service deployment you are changing | Reading, updating or deleting a deployment |
| Deployment generation | Which version of that deployment you read | Preventing an update from overwriting somebody else's change |
| Activation ID | Which individual call you are asking about | Looking up status or requesting cancellation |
| Operation ID | Which managed administrative change you submitted | Recovering its retained result after a lost response |

The CLI can write these values to JSON files. The tutorials read them for you;
you do not need to copy long checksums by hand. A checksum or ID identifies
something, but it does not grant permission to use it. Your authenticated tenant,
current policy and the selected operation determine permission.

A package can change without changing its program?for example, when its software
inventory is corrected. Publishing the same bytes in two tenants also creates
separate publication identities. Do not substitute a component checksum where
a command asks for a publication ID.

## What happens when you update a service

Build and publish the changed capsule, then update the deployment to select the
new publication. Supply the generation you last read so a competing change
causes a conflict instead of being overwritten.

Requests already running keep their selected revision. Later requests use the
new route. Restoring an earlier version is another explicit update, and that
publication must still be eligible under current policy. Keeping its bytes in a
cache does not restore revoked permission.

Try this in [Update and restore a capsule](deliver-and-recover-a-capsule.md).
The [deployment reference](../deployment-routing.md) explains route generations
and managed catalog state versions when you need more detailed coordination.

## What a lost response means

A timeout means the caller did not receive a result in time. The node or an
external provider may already have acted. Keep the original activation or
operation ID and inspect that result before deciding what to do next.

`Unknown` means retained history cannot establish the result; the record may
have expired. It does not mean the operation never happened. `Uncertain` means
durable confirmation is unresolved. The [client guide](use-a-client.mdx) and
[operator reference](../reference/operator-cli.md) explain the lookup methods.

Likewise, an accepted cancellation request is not proof that cleanup has
finished. Active work remains accounted for until its owner has stopped it and
released its resources. Deployments retain bounded metadata while idle, but
they do not each keep a running guest instance.
