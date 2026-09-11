# Kubernetes comparison evidence shapes

These self-contained Draft 2020-12 schemas describe completed public benchmark
records. They are separate from application manifest schemas and the unchanged
#111 binary build inputs.

| Document | Structural schema |
| --- | --- |
| Public `bootstrap.json` | [bootstrap](bootstrap.schema.json) |
| Completed campaign `suite.json` | [suite](suite.schema.json) |
| Replayed `aggregate.json` | [aggregate](aggregate.schema.json) |
| Final cluster `cleanup.json` | [cluster cleanup](cluster-cleanup.schema.json) |

Outer fields are closed. Suite and aggregate envelopes distinguish the one-pair
300-offer smoke from seven-pair 9,926-offer full evidence. Smoke cannot set either
full-population qualification flag. The compact nested plan checks selectors and
population shape; exact source-defined plan equality remains a replay check.
Completed group envelopes also require the separate API-graph and worker-proxy
milestones, with at most twenty retained nat/filter rule observations. Structural
acceptance of those rows does not prove the actual forwarding rules or connectivity.
The suite stores closed group identity/hash references to `group-P-G.json`; replay
verifies their exact population, paths, bytes and identity before loading each
bounded full group (`$defs/group`) without raising the shared decoder limits.
Nested API, process, resource, source-input, metric and credential-removal records
keep their existing semantic validators. Credentials in the bootstrap are only
path/length/hash metadata; actual private files must never be archived.

Run the [offline replay and archive workflow](../../../docs/testing/kubernetes-comparison.md#offline-archive-and-original-docker-dependency).
Schema acceptance does not prove original byte hashes, the Docker dependency,
image identity, Service/EndpointSlice ownership, original client commands,
responses, clock relationships, API-call closure, resource quantities, arithmetic
or Linux/Windows credential removal. The mandatory semantic replay checks those
facts and exact CSV/manifest bytes. It also enforces strict Python numeric types;
JSON Schema's mathematical integer type is insufficient on its own. Failed or
partial originals remain diagnostic even if they do not match a completed-record
schema. They are validated through the separately indexed failure/recovery path.

The normal `python tools/validate_repository.py` CI gate checks the exact four-file
schema set, Draft syntax and both source plans against the suite and aggregate
plan definitions. It does not construct a campaign fixture.

The following local check requires the measurement `jsonschema` dependency. It
checks all four schema documents and both source-defined plans; it does not
contact Kubernetes or run a workload:

```text
python -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator as V; from tools.optimization_kubernetes.model import plan; p=Path('tools/optimization_kubernetes/schemas'); s={f.stem:json.loads(f.read_text(encoding='utf-8')) for f in p.glob('*.schema.json')}; [V.check_schema(v) for v in s.values()]; [V({'\u0024defs':s[n]['\u0024defs'],'\u0024ref':'#/\u0024defs/plan'}).validate(plan(profile,owner='lsf-112-0123456789ab')) for n in ('suite.schema','aggregate.schema') for profile in ('smoke','full')]; print('Kubernetes structural schemas and source plans validated')"
```

These files contain no external `$ref`; structural checks do not fetch a remote
schema. Whole-package semantic replay remains the publication gate.
