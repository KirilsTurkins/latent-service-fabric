# Ownership functional parser fixture

`ownership_functional_control.json.gz` retains the original bytes of all 31 files
from functional attempt 03. Each file has its original SHA-256, byte length and
base64 encoding inside a deterministic gzip envelope. The fixture includes the
three real small Wasm components, payload/context inputs, generated manifest,
generator and normal raw documents, logs, process receipts and debug source
identity. Tests unpack and verify those bytes before semantic replay.

The execution was functional validation only: a debug libtest from the common
neutral implementation, run while the repository was clean at `b4509fb`. The
retained identity and source receipts give the complete commit, tree and actual
executable hash. Its earlier compiled Rust source set matched that checkpoint;
this fixture does not establish a release build recipe or performance result.
No qualifying suite or aggregate is fabricated.

The actual generator performed one capabilities preparation, 13 borrowed context
charge checks, zero Invokes and zero guest Stores. The normal child performed
three preparations, 24 ordinary direct calls and two real pending-future proofs.
Both proofs retained the control's raw vector through guest dispatch and released
it at owner scope exit. Both children joined their compiler and runtime threads.

The regression tests mutate copies and recompute dependent hashes, so rejection
exercises semantic associations rather than merely noticing stale file hashes.
The original functional output remains separately preserved in development
diagnostics. Attempts 01 and 02 failed before spawning the collector because
the debug executable exceeded the production helper's normal binary bound;
attempt 03 used an explicitly bounded local debug supervisor.
