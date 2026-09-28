# Serve gzip through the HTTPS edge

Use this option when you want smaller static downloads from the
[local HTTPS edge](local-https-edge.md). Your build output and signed packages
stay unchanged. LSF verifies the original content; the trusted edge compresses
it for delivery over HTTPS. Gzip bytes are not a separately publisher-signed
package representation.

## Enable compression

Build the edge and prepare its protected TLS files as in the HTTPS guide. Add
`"compression":"gzip"` to the canonical `edge.json` configuration:

```json
{"authority":"frontend.example.test:18443","bind":"0.0.0.0","certificate":"/etc/lsf/tls/server.pem","compression":"gzip","formatVersion":1,"port":18443,"privateKey":"/etc/lsf/tls/server-key.pem","upstreamPort":18080}
```

Run this profile with `--memory 384m`; keep the guide's other container limits
and private mounts. The image uses four shared compression threads, at most four
exchanges, an 8 MiB original body limit and an 8 MiB + 64 KiB encoded limit. There
are no per-site processes or cached compressed copies. Omit `compression`, or
use `"none"`, to keep identity streaming and its 192 MiB profile.

## Check the same file in both representations

Using the certificate trust for your real hostname, request a known static file:

```sh
curl --fail --dump-header identity.headers -H 'Accept-Encoding: identity' https://your.example/app.js --output identity.js
curl --fail --dump-header gzip.headers --compressed https://your.example/app.js --output decoded.js
cmp identity.js decoded.js
```

`--compressed` decompresses the result, so the saved files should match. The gzip
response has `Content-Encoding: gzip`, `Vary: Accept-Encoding` and a different
strong ETag. A browser uses the ETag for its selected representation. GET, HEAD
and 304 agree on that validator. If-Match uses strong comparison; If-None-Match
uses weak comparison. Supplying an identity ETag for a gzip If-Match returns 412.

Set both GET and HEAD routes to the same publication using the
[route reconciliation workflow](static-route-sets.md). They remain
independent native routes: gzip HEAD checks HEAD, reads GET, and rejects a
representation mismatch with 502. It does not silently choose one route.

## Understand failures and cost

Unsupported encodings with identity explicitly excluded return 406. Malformed
encoding preferences, duplicate coding names, Range and date-based conditions
return 400. Valid explicit quality values and wildcard/identity preferences are
supported. Native missing, denied, revoked or damaged content keeps its native
error; the edge never substitutes a cached success. CSP, HSTS, Origin and Fetch
Metadata rules still apply.

Each compressed request reads and buffers the original, then compresses it.
Conditional gzip requests also do this work; gzip HEAD makes a native HEAD and
GET. There is no on-disk compression cache. A disconnected client releases its
transport immediately; a compression job already running keeps its bounded slot
until it finishes. Saturated capacity is rejected, not queued or retried.

The maintained local drill observed 2,686,976 original bytes becoming 7,889 gzip
bytes and a separate 2,621,440-byte publication becoming 7,696 bytes. These are
deliberately repetitive JavaScript transfer fixtures, not typical application
ratios. The receipt records three timings for each encoding, memory/CPU samples
and exact source digests. Measure your own output and host; these observations do
not establish a production latency improvement or an earlier regression.

See the [compression decision](../../adr/0058-transform-static-identity-bytes-at-a-bounded-trusted-edge.md)
for the complete integrity and resource contract.
