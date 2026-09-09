The two gzip files retain unchanged actual #106 dirty-source diagnostic raw
graphs from snapshot11. Each has 52 Invokes, 125 wire commands, 24 functional
Invokes and 288 source diagnostic records. D0 uses on-demand allocation; P0 uses
pooling. Both native resource-fault witnesses, all original identities and all
original outcome/clock fields remain intact.

These are functional regression fixtures only. They are not release evidence:
tests replay the offers, statuses, source diagnostic lineage and native proof
rows, without qualifying the source/build/artifact graph or a benchmark suite.
The original files remain under ignored `target/phase1-extension/`:

| Source | Expanded bytes | SHA-256 |
| --- | ---: | --- |
| `issue106-dirty-collector-11-D0-raw.json` | 716,101 | `0c6299cab9183d8d20b072ad284febafc7e473edb27ec84d82547f2e97ed8970` |
| `issue106-dirty-collector-11-P0-raw.json` | 716,244 | `973e8398f52ebd33b6395a5e03ebbff9ef3ffa3f31c259b3f84b383afb07be41` |
