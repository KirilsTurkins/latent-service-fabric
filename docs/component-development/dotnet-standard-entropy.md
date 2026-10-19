# Ordinary .NET secure entropy

The compiler-owned `dotnet-native-entropy-v2` profile connects the pinned
`SystemNative_GetCryptographicallySecureRandomBytes` PAL entrypoint to the
existing `latent:random/random@0.1.0` `u64-value` operation. Applications and
outside libraries keep ordinary `System.Security.Cryptography.RandomNumberGenerator`
calls. The authoritative application world must explicitly declare RANDOM, and
the operator must separately grant the selected provider and operation. Merely
emitting a WASI import grants nothing. The primary closed adapter still denies
WASI secure random.

The exact NativeAOT package, archive and `pal_random.c.obj` identities are checked
before deriving the private object. Both linker wraps must appear exactly once
in the actual linker response; another wrap, source mutation or changed object
is rejected. The existing noncryptographic hash-seed function is unchanged.
Its bytes-only policy cannot authorize secure scalar draws. Native port receipts
retain their existing `noncrypto-entropy-*` filenames and record the new profile,
both wraps and secure ABI explicitly, invalidating the old source/recipe identity.

The pinned [PAL source](https://github.com/dotnet/runtimelab/blob/8449ba666dd991e495d8363d9852f18eb86a1aa1/src/native/libs/System.Native/pal_random.c)
returns zero on success and minus one on failure. Its
[managed caller](https://github.com/dotnet/runtimelab/blob/8449ba666dd991e495d8363d9852f18eb86a1aa1/src/libraries/Common/src/Interop/Unix/System.Native/Interop.GetRandomBytes.cs)
converts failure into `CryptographicException`. The port fills at most 65,536
bytes, requests one scalar for each eight output bytes, and retires each scalar
owner after canonical lowering. Provider denial clears the requested destination
and returns failure; it never substitutes a seed or acknowledges partial output.
Zero-length native calls consume no entropy. The canonical result has a one-byte
discriminant, a payload at offset eight, and size/alignment 16/8, enforced during
native compilation. Provider, activation and operator budgets remain independent
and may reject a smaller request.

The default-off outside-NuGet qualification captures an ordinary managed library,
removes its original source/feed, builds offline, signs the result and uses the
existing node workflow. It covers array/span/instance/offset and integer APIs,
argument errors, request-sensitive initialization, bytes-only operation denial,
budget exhaustion, trap/fuel recovery and a fresh activation after each terminal
case. No raw random bytes are retained. Its explicit experimental policy is
restricted to the selected publication and does not change default language
profiles or authorize transactional application entropy.

The new signed secure-RNG programme is pending actual execution. Source tests
and the prior Console/hash-seed campaign do not qualify this secure path. The
Linux owning test also executes a small native reference for exact byte order,
buffer canaries, all three typed provider errors, partial-output clearing and
unchanged noncryptographic behavior. This provides no statistical-quality,
FIPS, transactional replay or concurrency certification. It advances the entropy
portion of [#681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681);
the complete multi-language resource/clock/logging requirements remain separate.
