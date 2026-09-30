# Server source WIT conformance fixture

`web-graph.json` is the parsed authoritative `wit/platform/web` interface and
its captured context dependency, produced with checked-in wasm-tools 1.254.0.
The JSON is canonicalized only for stable test input. It is a WIT-parser
fixture, not a compiled/executed Java application or an admission receipt.

The test compares this actual schema with mutations that keep the export name
but change async, parameter or result semantics. Real compiler integration
must inspect the final component with the same tool and captured authoritative
reference tree. This fixture alone cannot establish source-API translation.
