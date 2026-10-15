# Examples

Start with [Creating a capsule](../docs/component-development/creating-a-capsule.md)
for the shared six-language workflow. Example source, schema validity and a
compiler build establish different boundaries from installed provider authority
and signed runtime qualification.

## Maintained application and runtime examples

- [Echo contract](echo-contract/README.md): executable Rust component; build with `make echo-capsule`. The [standalone quickstart](../docs/development/standalone-quickstart.md) publishes, deploys and invokes it through the authenticated node.
- [Stateful order draft](stateful-reference/README.md): shared business contract, schema and Angular UI with six guest implementations. It uses explicit transaction/query/intent profiles, signed companions and installed state/effect authority; complete application and packaged qualification remain separate.
- [Angular reference application](angular-reference-application/README.md): finite SSR/client application using the selected renderer and browser boundary.
- [Java schema transition](java-transaction-schema/README.md): captured legacy/compatible/writer sources and explicit migration boundaries; a source build does not approve a migration or restore.
- [Static release](static-release/README.md) and [static API](static-api/README.md): publication and browser-facing fixtures with their declared package/serving profiles.
- [Outbound HTTP](outbound-http/README.md), [streaming HTTP](streaming-http/README.md), [local blobs](local-blobs/README.md) and [local secrets](local-secrets/README.md): configured capability-provider examples using actual bounded host owners.

These examples use their named profiles and current source. Published alpha.5
commands and older receipts do not qualify newer Development transaction or
language-runtime paths. Check each example's exact inputs and remaining
acceptance requirements before selecting a run.

## Contract and package fixtures

`counter-contract` and `order-workflow-contract` are declarative contract/schema
fixtures. They are not the executable stateful reference above. Their placeholder
state/workflow declarations do not imply an installed runtime or durable workflow
engine.

[Package inputs](package-inputs/README.md) are browser/SSR packaging fixtures;
[package format](package-format/README.md) covers exact-byte OCI/evidence layout.
Neither fixture alone supplies publisher trust, a serving/rendering provider or
an executable-content claim.
