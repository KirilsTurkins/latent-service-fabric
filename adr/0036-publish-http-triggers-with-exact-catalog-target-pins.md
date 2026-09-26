# ADR-0036: Publish HTTP triggers with exact catalog target pins

## Status

Accepted; Phase 3 issue #223. Extends ADR-0011, ADR-0025 and ADR-0035.

[ADR-0043](0043-select-static-web-publications-as-first-class-http-targets.md)
extends this application target with a separate static-web variant and current
format-v2 HTTP state. The target remains exact; static serving invents no
component or deployment identity.

## Context

HTTP host/path selection must not combine an old trigger with a newer logical
service resolution. A component digest does not identify a publication, and a
content revision alone cannot distinguish deletion and recreation of the same
deployment. Trigger records must survive restart without creating dormant
execution resources.

## Decision

Store the closed buffered HTTP profile in the existing deployment catalog.
One transaction publishes canonical route matchers, tenant publication IDs,
named deployment IDs, content revisions, deployment object generations and
bounded operation receipts. All catalog writers preserve this table. Updates
require explicit global-state and trigger-object CAS preconditions.

Select against one coherent current publication and retain the accepted target
with its original route view and read charge. Recheck exact deployment pins and
current publication eligibility. A stale winning match denies without fallback.
The runtime's guarded activation-start decision remains authoritative for calls
already selected. A receipt is historical evidence, never an execution grant.

The exact `latent:web/application@0.1.0` export is a shared application contract
that tenant capsules may implement. Capsule worlds and other owned exports keep
their existing tenant namespace constraints. This exception neither installs
host imports nor changes admission, publisher trust or lifecycle scope.

One canonical authority belongs to one tenant within the catalog. Matchers use
explicit methods and exact/segment-prefix paths with deterministic precedence.
This authority reservation does not verify DNS ownership or replace the shared
ingress's host/TLS access policy. Route metadata itself creates no public HTTP
listener.

## Consequences

Trigger state and receipts share catalog format 7 and the existing replace/fsync
boundary. Uncertain state denies new selection until recovery. Historical
records remain inspectable and removable after target revocation. Operation
history, pages, candidate tables and retained read owners have finite limits.
Mutation audit runs inline on the existing control runtime, with response
preflight before commit and explicit uncertainty after lost completion.

See the [HTTP trigger contract](../docs/reference/http-triggers.md) for the
profile, limits, compatibility and operational recovery rules.
