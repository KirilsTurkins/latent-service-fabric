# Release an existing frontend build

Use this workflow to publish reviewed HTML, JavaScript, styles and other supported
assets without installing Rust. Your framework still produces its normal build
output. LSF packages those files, checks approved evidence and selects an exact
publication through GET/HEAD routes.

Run these tools on Linux. On Windows, use your WSL environment. Install Node.js
24, Python 3.12 or newer and the [authenticated released CLI](../installation.md).
Use a reviewed checkout of the helper tools that matches your intended profile.
Keep organization credentials and signing files outside the build checkout.

## Prepare the reviewed files

Build your frontend normally. Review its public file list, deliberate exclusions,
routing and source/toolchain/build observations using the
[static-site inventory format](../component-development/static-sites.md).
Do not silently omit unsupported files to make validation pass. Packaging cannot
prove that a framework is compatible with the browser's CSP.

Set `Cli` and `Python` to your installed executable paths, `BuildOutput` to the
existing output directory, and `Inventory` to the reviewed capture JSON. Choose
a new private `Prepared` directory under a directory you own:

```sh
node tools/static-release/release.mjs prepare --cli "$Cli" --python "$Python" --build-output "$BuildOutput" --inventory "$Inventory" --repository "$SourceRepository" --output "$Prepared"
```

The result contains the unsigned package, an embedded SBOM, `observation.json`
and `PREPARE-COMPLETE.json`. The observation says supplied-file assembly,
non-hermetic inputs, incomplete dependencies and unchecked reproducibility. It
does not claim to have run or reproduced your framework build. Review both the
package and the observation before sending them to your signing authority.

## Approve and sign the exact release

Your organization provides its publisher and builder identities, approved raw
public keys, current admission policy and revocations. `Identities` is canonical
JSON with `publisher` and `builder`, each containing `id` and `publicKey`. The
public key is canonical base64 of 32 raw Ed25519 bytes. Your policy administrator
must explicitly allow `https://latent.dev/build/web-package-assembly/v1` and the
selected repository label; this tool creates no trust policy.

```sh
node tools/static-release/release.mjs request-signing --prepared "$Prepared" --identities "$Identities" --lifetime-seconds 3600 --output "$SigningRequest"
```

Send that exact request, package and observation through your organization's
approval process. A generated request is **not approval**. The approved request
must retain its exact package, observation, key identities and validity. If the
bytes change or the request expires, create and review a new request.

In a protected signing job, use externally supplied PKCS#8 DER keys matching the
approved public keys. The approved file and keys must be owned by the current
Linux user, have mode `0600`, and reside in a private `0700` directory. Keep the
key contents out of environment variables, command arguments, logs and uploaded artifacts.
The arguments below contain paths only:

```sh
node tools/static-release/release.mjs sign --cli "$Cli" --prepared "$Prepared" --approval "$ApprovedRequest" --publisher-key "$PublisherKey" --builder-key "$BuilderKey" --policy "$Policy" --tenant "$Tenant" --output "$Evidence"
```

The helper creates detached publisher and builder signatures, then uses the
native verifier to check current policy, revocations, tenant, SBOM and exact
output identities. Continue only when `SIGNING-COMPLETE.json` exists. A failed
directory is not completed evidence. An external signer may instead implement
the [publisher](../reference/publisher-trust.md) and
[web-assembly](../reference/web-release-admission.md) evidence contracts.

## Transfer and publish

Use your [explicit OCI profile](../reference/oci-registry.md). Record the immutable
package digest from the preparation receipt. Tags are upload labels; deployment
inputs use digests:

```sh
"$Cli" package push "$Prepared/package" --registry-profile "$RegistryProfile" --reference "$UploadLabel" --evidence-index "$Evidence/index.json" --evidence-root "$Evidence"
"$Cli" package pull --registry-profile "$RegistryProfile" --reference "$PackageDigest" --output-dir "$PulledPackage" --evidence-output "$PulledEvidence"
"$Cli" --tenant "$Tenant" package verify "$PulledPackage" --evidence-index "$PulledEvidence/index.json" --evidence-root "$PulledEvidence" --policy "$Policy"
```

Persist a unique operation ID in your private job journal **before** publishing.
Use the same ID when investigating an interrupted response:

```sh
"$Cli" --config "$ClientConfig" --output json web publish "$PulledPackage" --evidence "$PulledEvidence/index.json" --operation-id "$PublishOperation" --expected-generation 0 > publication-result.json
"$Cli" --config "$ClientConfig" --output json web operation "$PublishOperation" > publication-recovery.json
```

Require a known committed receipt and record its tenant/publication ID. A timeout,
UNKNOWN result or evicted receipt does not prove that publication failed. Stop
automatic writes, inspect the original operation and exact current publication,
and reconcile before authorizing another action. Preserve unsuccessful receipts.
For an interrupted OCI push, pull the recorded digest to check the remote bytes;
do not infer success from the upload label or repeat a publication blindly.

Apply GET and HEAD together through the
[route-set reconciliation guide](static-route-sets.md). It records both intended
routes, protects concurrent changes and recovers interrupted cutovers. Rollback
is a new explicit route-set operation selecting a currently eligible earlier
publication; it is not a reset of operation history.

## Renew evidence and recover

Before evidence or trust snapshots expire, obtain new organization approval and
sign the **unchanged** package into a fresh evidence directory. Verify it under
current policy. Record a new renewal operation and the publication's observed
lifecycle generation:

```sh
"$Cli" --config "$ClientConfig" --output json web get --publication "$Publication"
"$Cli" --config "$ClientConfig" --output json web renew-evidence --publication "$Publication" --package-digest "$PackageDigest" --evidence "$RenewedEvidence/index.json" --operation-id "$RenewalOperation" --expected-generation "$Generation"
"$Cli" --config "$ClientConfig" --output json web operation "$RenewalOperation"
```

Renewal cannot override a revoked key, disallowed source, retired publication or
changed trust policy. Do not reuse an old successful verification as current
authority. Resolve generation conflicts from fresh state. After a node restart,
honor its persisted restart clock floor and verify readiness before mutations.

## Connect it to CI and Terraform

Terraform provisions the node, ingress, protected credentials and durable
storage. A separate frontend job prepares/signs/uploads packages and records
their immutable digests, evidence identities, publication IDs, operation IDs and
route journals. Updating one publication does not change the runtime revision.
Keep failed and uncertain outcomes available to the next job; serialize updates
to the same route set and use its state fences for unrelated concurrent changes.

The maintained `Released frontend publication workflow` tests this sequence with
authenticated release binaries in a clean non-root container, without Rust. It
uses fresh disposable test identities, a real TLS registry and a real node.
Its small [examples](../../examples/static-release/README.md) exercise static
and documentation publications, renewal, rollback and restart. These test keys
are not operational trust, and this run does not qualify a managed cloud host.
