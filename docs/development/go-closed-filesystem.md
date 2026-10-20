# Ordinary Go file APIs without a filesystem profile

This finite #681 criterion-5 slice keeps scratch storage unsupported. The
maintained closed Go adapter imports only the guest's own memory; no directory,
descriptor, filesystem provider, writable storage or new grant is installed.
Only `path_open` changes from WASI NOTCAPABLE (76) to ENOSYS (52). Preopen
discovery still returns EBADF (8), and every unrelated adapter export is
byte-identical to the authenticated original. No Go application/syscall shim,
error alias, hidden fallback, path translation or fake successful file is added.

The exact Go 1.27.2 `syscall/fs_wasip1.go` preimage is
`5cf5a98b3361c2d839e084b183366849cd276c9585620f04cc3c75e35a371448`.
Its discovery loop ends at EBADF; `preparePath` retains fd -1 when no directory
is preopened, but `Open` still reaches `openat` and the closed `path_open`.
Ordinary `os.Open`, `os.OpenFile` and `os.CreateTemp` therefore reach this
same no-authority result. CreateTemp returns a non-ErrExist error immediately,
without a hidden retry loop. All original ordinary API calls remain intact.

The [pinned Go error implementation](https://github.com/golang/go/blob/go1.27.2/src/syscall/syscall_wasip1.go#L77-L88)
(`2017243455e2f7f62bdd0c36040be61af3989b5d96ab81d115d24228657ed1b1`)
maps `errors.Is(err, errors.ErrUnsupported)` to ENOSYS only. ENOTSUP (58)
is distinct in this Go port and is not treated as standard Unsupported by
the evidence classifier. The actual fixture requires `errors.Is` before
publishing a numeric ENOSYS result; unclassified output cannot pass the gate.

The dedicated hosted lane compiles the exact old/current adapters with the
pinned wasm-tools. One real Wasmtime target executes them under fixed 64 KiB
memory and 10,000 fuel each: old path_open 76, new 52, unchanged discovery 8,
mkdir/socket 76 and descriptor-read 8, with no memory writes or host filesystem.
The full-source preimage guard rejects any unrelated byte/export change.
This is a core adapter reference, separate from signed component qualification.

The same lane requires a fresh original Go normal27 qualification. Its five
authenticated native products and four companion packages feed the unchanged
generic scratch runner, which repeats normal27 and adds six signed entry,
open/create/temp, explicit fixture-trap and fresh-state calls. Every standard
call must be caught and return underlying 52, standard Unsupported and zero
outbound/log/effects, under the original budgets. Provider/physical retirement,
process reaping and clean node shutdown remain required. A wrong result,
generic trap, successful file, changed source/native tuple or missing call
cannot satisfy this gate. Bounded diagnostics and a public normal-products
bundle are retained; keys, compiler caches and private peers are not exported.

Local source controls and Rust formatting are separate from the pending actual
core/native/signed campaign. No local native build is used. Only the reached
three open/create/temp paths are qualified by that campaign; other filesystem
APIs, implemented scratch storage, durable state and the full six-language
resource/facility/concurrency matrix remain outside it. #681 stays open.
