# Exact-source local Python contracts lane for Java builder evidence

The original **Repository contracts / Python** run block passed for
`59c03abd1fbf2bcc39430ebe9866eb5ab23ee020`. It ran **2,932 tests**, retaining
the ten original guarded skips, in 537.503 test seconds. The run block took
556.189669 seconds; the complete controller took 585.805004 seconds.
[The unchanged receipt](receipt.json) records the exact command,
`tools/validate_contracts.sh "$CI_CONTRACT_LANE"`, with `CI_CONTRACT_LANE=python`.
Tracked source files stayed unchanged.

The actual environment was Ubuntu 24.04.5, Python 3.13.5 and unprivileged UID
23001, using the separately inspected tooling image
`sha256:c19db1b2bb887c214b87d05aa7f15a6d2108758fa4f2cf04d09bddce8a627502`.
The process had a private source checkout, home and Cargo directory. Both
`LSF_REQUIRE_NATIVE_PROCESS_TESTS=1` and `LSF_REQUIRE_COMPILER_ISOLATION=1`
remained enabled. A scoped `seccomp=unconfined` container setting permitted the
original bubblewrap namespace guards; no extra capabilities were added and no
shared native cache was used.

[The first environment failure](original-environment-failure.json) remains
recorded: all 2,932 cases ran, with five failures caused by the container denying
the original namespace creation. The actual bubblewrap failure and namespace
probes are retained. The separate [compiler isolation receipt](compiler-isolation-receipt.json)
records all nine unchanged module cases passing with zero skips after correcting
only that outer environment setting. The subsequent complete lane used the same
source and assertions.

[The complete original streams](complete-original-streams.tar.gz) retain both
attempts, their controllers, original stdout and stderr, namespace probes and
receipts, including empty streams. The [member inventory](original-stream-inventory.json)
anchors every original byte sequence; each archive member was independently
rehashed. All raw originals also remain outside disposable worktrees.

This qualifies the recorded Python lane run block. The receipt explicitly records
that Java, Go, .NET, wasm-tools, Buf, Zig and wit-bindgen were absent. Synthetic
Java-class messages in source tests do not establish an installed compiler or a
real guest build. Full repository CI, SDK and guest builds, other native lanes,
hosted uploads and attestations remain separate; `fullRepositoryCiPassed` is
false. The earlier [Fast](../java-builder-local-fast-ci-0325/README.md) and
[Documentation](../java-builder-local-docs-ci-0325/README.md) proofs belong to
their original `0325b746` source. Signed builder acceptance remains in the
separate [C4 composition campaign](../java-composed-c4-3b7/README.md).
