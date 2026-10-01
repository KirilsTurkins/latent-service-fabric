# Java aggregate format variants

These ordinary application projects keep the existing `aggregate/count` key,
namespace, State/Intent resources, WIT exports and opaque version/view tokens.
They use the maintained Java → TeaVM C → component recipe. `AggregateCodec` is
application encoding code and supplies no persistence or migration authority.

```sh
python tools/java_transaction_schema.py --variant legacy-v1 --project "$FreshV1"
python tools/java_transaction_schema.py --variant compatible-v2 --project "$FreshCompatibleV2"
python tools/java_transaction_schema.py --variant writer-v2 --project "$FreshWriterV2"
```

The original writer stores an eight-byte unsigned little-endian count with v1
media. The compatible v2 reader accepts that format and the exact tagged twelve
bytes with v2 media, while continuing to write v1 during canary. The v2 writer
uses `41 47 02 00` followed by the same eight-byte count. It is selected only
after host-reviewed, quiesced namespace migration; an old v1 reader cannot
decode its records. Both exact schema definition files are captured unchanged.

Build each project using the delivered `tools/java_capsule.py build` command and
retain its independent original source/component/package/compiler receipts.
`application-schema-inputs.json` describes reader/writer definitions only. The
common host review must separately bind a real package and conformance proof;
these inputs authorize no deployment, rollback, restore or migration. Node
execution, retained command/effect identities, compatibility review and paused
older-history restoration are qualified through the shared Phase 4 owners.

The bounded `EncodingVectors` JVM schedule checks byte formats and full-width
integers. It supplies no Java component, transaction, query or intent execution
evidence.
