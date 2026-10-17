# Internal I/O encoder fixture

`internal-io.json` contains the unchanged actual wasm-tools 1.254.0 output for
two finite synthetic worlds, an importing caller and exporting adapter. Both
use the captured SDK's four private WASI I/O function shapes. The caller uses
synchronous types; the adapter uses async types. Other stream operations remain
synchronous. This is a source and component-encoder fixture, not an emitted C#
application or execution receipt.

The original caller component SHA-256 is
`d5a8d813835c21dd922da9d8d77e12142095c606069c9630fe96b82bc0e1e029`;
the original adapter component SHA-256 is
`8e7fe2fcec4a49b4c25137a55ccc502b282a043f3c8b10083295a0c0746715dc`.
The normal encoder projection produced
`378378b0b8c343af68f49c1243af874b519314df7a97082fcc96dda776245b3e`
and independently verified the complete graph projection plus all four original
core-module payloads byte-for-byte. No component code was disassembled.
