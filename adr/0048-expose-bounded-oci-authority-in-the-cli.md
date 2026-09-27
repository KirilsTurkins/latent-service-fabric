# ADR-0048: Expose bounded OCI authority in the CLI

- Status: Accepted
- Date: 2026-09-27

## Context

The operator CLI accepts only static registry credentials and socket addresses,
while the existing OCI library has reviewed bearer, DNS and redirect controls.
Operators cannot use those controls through released package commands. Hosted
registry qualification is separate from exposing the library configuration.

## Decision

Add a closed version 2 CLI registry profile. The profile explicitly binds one
registry/repository to an approved token realm, service, identity, credential
epoch and action set. A separate protected Basic credential file supplies token
service credentials. Optional network policy declares exact registry, token and
storage origins, bounded DNS/static resolution, address allowlists and content
prefixes. The profile calls the existing OCI constructors; it adds no second
HTTP stack, authentication loop or redirect implementation.

Keep the 16 KiB profile/credential caps and the transport's finite destination,
address, TTL, connection, buffer and redirect ceilings. Network configuration
cannot coexist with the ordinary static socket arrays. Version 1 remains a
static profile and rejects the new fields. Version 2 rejects plaintext loopback,
anonymous or preissued Bearer challenge credentials, unknown/duplicate/null
fields and configurations that fail the library's exact-authority checks.

The CLI retains its original absolute transfer deadline and bounded cleanup.
Token refresh cannot extend that deadline or replay an uncertain write. Redirect
credentials remain stripped by the existing transport. CI identity provisioning
and rotation stay outside LSF; credentials never become CLI arguments or output.

## Consequences and validation

Schema and native tests cover version crossing, limits, closed nested fields,
identity binding, action scope, private-address denial, malformed authorities,
unapproved token endpoints, rejected roots and credential redaction. Existing
OCI TLS/DNS/refresh/redirect/uncertain-write tests continue to qualify the shared
transport. No ACR or ACA support claim follows from these tests. The actual
short-lived-identity ACR qualification in issue #634 remains required before
adding a hosted configuration to the support matrix.
