# Request content length at the captured WASI header boundary

`dotnet-wasi-request-content-length-v1` extends the coupled HTTP/CoreLib
selection at the original `WasiHttpInterop.ConvertRequestHeaders` content
header enumeration. The maintained BCL stores a computable content length
lazily: enumerating `HttpContent.Headers` alone does not materialize it. The
original signed POST case creates ordinary `ByteArrayContent` and requires
that its known length be transmitted; its metadata assertion remains intact.

The compiler authenticates the exact 297-byte conversion method and the
104-byte original `HttpContentHeaders.ContentLength` getter in the pinned
assembly. It substitutes one stack-compatible call with a private helper
which calls that getter and returns the same header object. It preserves the
original no-content branch, explicit lengths (including explicit null),
unknown stream lengths, header values and exceptions. It neither serializes
nor buffers content to infer a length, installs a handler, retries a request,
nor adds imports or grants. All other original methods and the serialized
product identities remain checked. Its exact receipt is required before
project mutation and is retained with the same joined ILC reference evidence.

Thirty additional actual captured-BCL host assertions reproduce the missing
lazy header, compare against the original getter and cover byte-array segments,
zero-length bodies, seekable/nonseekable streams, explicit length/null,
unchanged stream position and other headers, and unmodified getter exceptions.
These controls create no native fields and do not qualify transmission,
pending I/O, POST, uncertain POST or full #693/#746 acceptance. The unchanged
fourteen-case signed HTTP gate and subsequent library gates remain mandatory.
