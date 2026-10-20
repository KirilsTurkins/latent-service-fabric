# Pinned Go network derivation inputs

`net/dial.go`, `net/lookup.go` and `net/tcpsock.go` are exact Go 1.27.2
upstream source fixtures. Their full SHA-256 values are authenticated by
`tools/go_guest/network.py`. The source retains its original copyright and
BSD license notice; `LICENSE.golang` contains that upstream license.

`streams-generated.go.txt` is the exact, formatted streams package generated
twice from `wit/platform/network/package.wit` with componentize-go 0.4.3,
revision `148dba505f8c6c64ad84db777cfde5e34e25098b`, wit-bindgen-go
revision `4f9a02d74cec9257c14ba9b160fa787a3523fd0b`, and the Go 1.27.2 formatter.
Its SHA-256 is `21d79d0d1efdf115b9082a364abe40cb30256f3b197416f57f15cbec94e9319a`.
It is test input, not a replacement generator or checked-in application binding.

`connection-owner-test.go.txt` is owned reference-test source. The qualification
helper copies the actual SDK private owner and this test into one isolated,
dependency-free Go module. Its runtime result is distinct from component
construction, signing, provider installation and network execution.

`crypto/tls/cache.go` is the exact Go 1.27.2 private certificate-cache source,
SHA-256 `553ad7a40a9b198bea838833e3e5ed5660ec9b031ad75f58a9ea119e44bd3bfb`.
Declared-stream selection replaces only this authenticated cache with the
finite invocation-owned implementation; generic cleanup callbacks remain refused.
