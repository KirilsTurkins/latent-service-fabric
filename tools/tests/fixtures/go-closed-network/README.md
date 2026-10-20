# Exact Go socket reference inputs

`net_fake.go.in` is the complete Go 1.27.2 `src/net/net_fake.go`, Git blob
`cc35d90a26742fc3cd248f1cf2e96260ecbf7f45`, 27,195 bytes, SHA-256
`784b369c57be52fa87ace5f10e07e3c24b45d549639e1487734b793024188df3`.
It retains its original copyright/license notice. `LICENSE.golang` is the
upstream BSD license, blob `2a7cf70da6e498df9c11ab6a5eaa2ddd7af34da4`,
SHA-256 `911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad`.

`reference.go.txt` and `run-reference.mjs` are owned finite comparison source.
They exercise TCP/UDP fake listener construction and its standard Unsupported
replacement. They are not a runtime shim, substitute network provider, signed
guest programme or kernel accounting proof.
