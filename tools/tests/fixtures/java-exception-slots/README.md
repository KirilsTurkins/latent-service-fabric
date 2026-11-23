# Native exception-handler lifetime witness

`exceptions.h` is the unchanged TeaVM 0.15.0 C runtime resource from
`core/src/main/resources/org/teavm/backend/c/exceptions.h` in
<https://github.com/konsoletyper/teavm/tree/0.15.0>. TeaVM is licensed under the
Apache License, Version 2.0; see <https://www.apache.org/licenses/LICENSE-2.0>.
The fixture's exact SHA-256 is
`024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368`.

`core.h` and `definitions.h` are minimal native witness scaffolding, not SDK
runtime implementations. `probe.c` uses real setjmp/longjmp and checks disjoint,
nested and recursive descriptor lifetimes. It does not run TeaVM or a Wasm guest.
Reproduction commands and qualification boundaries are in
`docs/testing/java-exception-slot-lifetimes.md`.
