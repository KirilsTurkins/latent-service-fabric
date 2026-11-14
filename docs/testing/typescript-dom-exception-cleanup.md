# Native DOMException failures and foreground EventTarget retirement

Continuation for #1934, based on `068b27937c7bd36b27f0576bf29ed35f0855274a`.
The existing AbortSignal factory guard is not enough: EventTarget invalid
redispatch and other native callers enter `DOMException::raise/create` directly.
The pinned implementation dereferenced unchecked allocation/constructor results
and could write native slots into a replacement constructor's wrong-class object.
The default native constructor also used an unchecked `Error` string allocation.

## Production changes

The maintained source derivation now authenticates and transforms the whole
pinned `builtins/web/dom-exception.cpp`. Strings remain rooted before constructor
lookup/reentry. Every allocation, construction and pending-exception boundary is
checked. Native class validation precedes slot writes; no fallible allocation or
script follows validation. `raise` propagates failure without dereferencing null
or replacing an earlier failure. Default construction and both WebIDL string
conversions obey the same bool/pending-exception contract. The pinned observable
constructor lookup/reentry is retained; this does not replace it with a shim.

Ordinary EventTarget, not just AbortSignal, now finalizes on the foreground.
Its listener/vector destructors mutate the same activation-local NativeRetirement
list. Their leases still remain live through physical destruction, actual engine
collection completion and outside-GC host acknowledgement. No fabricated GC end,
new owner kind, owner ceiling, grant or profile promotion is introduced.

## Validation executed

The exact emitted factory, raise and native-constructor bodies run under bounded
JSAPI fault doubles. Cases cover two string allocations, getter/constructor
failure, false/no-pending termination, successful API calls with pending errors,
wrong native class, null construction, embedded NUL text, constructor reentry,
root-stack order and preservation of pre-existing failure. The original bodies
reproduce the unchecked boundaries; selected bodies pass. These are finite
doubles, not a moving collector or signed-component witness.

The combined event/abort/retirement/runtime-profile/native-build/native-await/
carrier-scheduling selection plus the new module passes 113 test methods under
GCC, Clang, and Clang ASan+UBSan, with no skips and leak checking enabled. Counts
are observations, not a required inventory. The existing ownership CI matrix
now includes the new module; prior commands and settings remain unchanged.

Five actual derived translation units compile with the retained pinned WASI SDK
30 / Clang 21 and SpiderMonkey headers: dom-exception.cpp, event-target.cpp,
event.cpp, abort-signal.cpp and abort-controller.cpp. This is compile evidence,
not a full linked-engine run. The missing configuration header was reconstructed
from retained config.status definitions; original-header byte identity is not
claimed. Full normal allocator/MFBT/mozglue/Rust link inputs remain unavailable.

## Source and qualification boundary

StarlingMonkey is `9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37`; SpiderMonkey is
`9dab3d6f643e926a340c391ea30968e940390dec`. The new unchanged-source fixture has
SHA-256 `7d51a56e77de10c80d90611056695a517af312120543e60c3d230cc1ae6632f7` and
is retained under the existing StarlingMonkey fixture attribution. The modified
production preimage and restored event tests/fixtures were verified against their
current #1934 Git blobs. Adjacent tests use the retained integration projection;
this is not a claim that the complete current repository was rebuilt.

Fresh signed fan-out refusal/default-reentry qualification, actual major/minor/
incremental/compacting GC, failed physical decommit custody, and aggregate
byte-attribution obligations remain separate. #1931's Store-order/reuse-veto
work must not be interpreted as proving them. No #745 checkbox is completed.
