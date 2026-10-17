# Go typed HTTP context cancellation prerequisite

The compiler adds context-aware typed HTTP methods only when the application
already imports `latent:http/streaming@0.3.0` and selects an admitted activation
runtime profile. It creates no network/runtime grant. The default runtime
profile and existing generated methods retain their behavior. This is a
prerequisite for [ordinary Go HTTP qualification](https://github.com/KirilsTurkins/latent-service-fabric/issues/692),
not an implementation or qualification of `net/http.Transport`.
Timed contexts require the explicit v3 or v4 timer profile; earlier profiles
retain their existing timer-constructor rejection.

The six reviewed generated call bodies are authenticated before derivation.
Argument layouts, pinned allocations, original methods and resource ownership
remain intact. Context variants check cancellation before dispatch and preserve
argument/result pins while the existing dispatcher parks the calling goroutine.
The compiler captures both the transformation recipe and the resulting bytes.

Cancellation unjoins the exact original subtask before issuing the asynchronous
canonical cancellation intrinsic. An immediate terminal event is consumed and
dropped once. A blocked cancellation rejoins the existing wait set and retains
the original pending entry and pins until its real terminal callback. If normal
delivery already removed or replaced the exact channel entry, the caller consumes that original event
instead of cancelling a dropped or reused handle. No helper executor, goroutine,
second pending inventory or replacement budget is introduced.

Only `RETURNED` permits decoding the result buffer, including owned resources
returned while cancellation raced completion. `START_CANCELLED` restores an own
upload argument because it was not transferred; `RETURN_CANCELLED` leaves it
consumed. The original ordinary wait still rejects cancellation before decoding.
The timer prehandler, checkpoints, initializer order and fresh quiescence checks
remain present in every selected dispatcher profile. Chunk bytes returned by the
context facade are copied before its resource is dropped.

Six focused source controls exercise the authenticated generated calls, drift,
own-argument restoration, every dispatcher profile and explicit SDK selection.
A separate actual wasm-tools 1.254.0 encoder control confirms the import spelling
and `(i32) -> i32` signature emit `canon subtask.cancel async`. These are source
and ABI assembly controls, not signed execution.

`tools/qualify_go_http_context.py` builds the checked-in typed SDK fixture through
the maintained Go compiler, with the original 900/600-second limits. Its receipt
explicitly says `compile-only` and `signedExecution: not-run`. The fixture covers
pre-cancelled calls, pending finish cancellation by a runnable sibling, timed
context cancellation, body cancellation and ordinary JSON/trailer consumption.
Native execution of these cases, race retirement, sibling progress, root drain
and cross-activation isolation remain required. This source candidate must not be
counted as default `http.Client`, unchanged library or private module evidence.
