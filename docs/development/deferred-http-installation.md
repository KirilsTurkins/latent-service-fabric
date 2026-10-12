# Signed deferred HTTP installation

The standalone runtime uses the existing `qualified-http-effect-v1` adapter and
the installed buffered HTTP provider. Its clock is the same once-bound protected
state clock. Configuration pins, signatures and inspection output confer no
staging or dispatch permission.

Include one `deferred-http-requirements.json` package asset with media type
`application/json`, at most 8192 bytes. The existing signed transaction-asset
capture reads its exact digest and bytes on the original reserved recovery worker.
The response allowance includes this document. No second package reader or
filesystem read is introduced at the rule acceptance fence.

The closed document has these fields:

| Field | Required value |
| --- | --- |
| `formatVersion` | `1` |
| `protocol` | `lsf-atomic-idempotent-http-v1` |
| `capsule`, `deployment`, `stateBinding`, `namespace` | Exact signed transaction companion links |
| `companionDigest` | Digest of the exact companion bytes |
| `binding` | Logical intent binding, at most 256 bytes |
| `operation` | `http` |
| `adapter` | `qualified-http-effect-v1` |
| `payloadFormat` | `http-body-value-v1` |
| `idempotencyProfile` | Exact profile produced by the actual configured adapter |
| `ceiling` | Existing `DispatchCeiling` fields below |

`ceiling` uses the existing snake-case field names:
`maximum_payload_bytes`, `maximum_response_bytes`, `maximum_attempts`,
`maximum_age_millis`, `attempt_timeout_millis`. Its payload and age cannot exceed
the configured qualified endpoint. Response capacity must be at least 22,528
bytes. Attempts are bounded by 128, age by seven days, timeout by 60 seconds and
response capacity by 1 MiB. The endpoint also bounds payloads to 64 KiB.
The old put-once descriptor and its fixed-payload/count promises are rejected.

The operation's `deferredHttp` configuration pins this asset's digest, provider
ID, endpoint incarnation and opaque credential reference. Its staging policies
and binding must match the deployment's intents grant and actual adapter profile.
The original caller's namespace/entity permission still gates each `stage` call.

Dispatch has a separate HTTP `send` policy and binding. Installation checks the
qualified POST and GET profile request using the verified capsule's canonical
service identity, publication and actual provider reference. Each actual GET,
POST and lookup path is checked again against that current policy before network
polls. Lookup never falls through to POST. Audit-required dispatch fails closed.

Rule publication retains the captured policy generation, current signed source
and namespace lifecycle, original native reservation and resident metadata.
Dispatch stays paused until all configured installations finish and readiness
checks pass. A missing namespace permits management only; creation and restart
must precede execution. Policy, publication, credential, namespace or retention
refusal never grants a replacement attempt or renews its deadline.

The HTTP adapter's real TLS/protected-store tests and the standalone signed
capture tests are distinct from Java guest and packaged workflow qualification.
Issues #409 and #718 retain those wider acceptance requirements.
