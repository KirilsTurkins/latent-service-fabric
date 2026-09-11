# Docker comparison evidence shapes

These private Draft 2020-12 schemas describe the fixed comparison plan, completed
build and suite receipts, aggregates, and persistent-client inputs and completion.
They are benchmark contracts, separate from application manifest schemas.

| Document | Schema |
| --- | --- |
| Campaign `plan.json` | [plan](plan.schema.json) |
| `docker-builds.json` | [builds](builds.schema.json) |
| Campaign `suite.json` | [suite](suite.schema.json) |
| Replayed `aggregate.json` | [aggregate](aggregate.schema.json) |
| Client `plan.json` | [client plan](client-plan.schema.json) |
| Each original client command | [client command](client-command.schema.json) |
| Client `summary.json` | [client summary](client-summary.schema.json) |

The compact campaign plan checks closed fields, bounded group/phase shapes and
the exact profile totals. Semantic replay checks the complete derived campaign
matrix, including every phase value and the alternating group order. Completed
suite and aggregate shapes bind the profile to its owner, phase and offer counts;
smoke completion cannot set full-population qualification. Client command shapes
require every nullable key and distinguish inventory, phase and lifecycle commands.
The last command's exact receipt remains required in a completed client summary.

Run the [offline replay](../../../docs/testing/docker-comparison.md#offline-replay-and-publication)
to validate the evidence. Schema validation alone does not establish command
order or original line hashes, response semantics, artifact digests, effective
limits, actual container/process ownership, cleanup, timestamp relationships,
source equality, unavailable metrics or statistical summaries. Nested shared
receipts, client event/Attempt rows and aggregate metric tables are checked by
their existing semantic validators. Byte limits and strict integer types are also
enforced by replay; JSON Schema's mathematical integer semantics are insufficient.
Failed or partial originals remain diagnostics even when they do not satisfy a
completed document's schema.

The normal `python tools/validate_repository.py` gate checks all seven schemas
and both source-defined plans against the standalone and inline structural
contracts. From the repository root, the following
focused check validates schema syntax and the standalone plans with the
repository's measurement Python dependencies available:

```text
python -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator as V; from tools.optimization_docker.model import plan; p=Path('tools/optimization_docker/schemas'); schemas={f.stem:json.loads(f.read_text(encoding='utf-8')) for f in p.glob('*.schema.json')}; [V.check_schema(s) for s in schemas.values()]; [V(schemas['plan.schema']).validate(plan(x)) for x in ('smoke','full')]; print('Docker schemas and fixed plans validated')"
```

This command checks contracts only and does not run Docker or a benchmark.
