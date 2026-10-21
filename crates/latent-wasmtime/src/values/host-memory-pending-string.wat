;; Synthetic real pending native-call fixture; it has only a test wait import.
;; Regenerate: wasm-tools parse host-memory-pending-string.wat -o host-memory-pending-string.wasm
(component
  (import "wait" (func $wait))
  (core func $lower (canon lower (func $wait)))
  (core module $m
    (import "host" "wait" (func $wait))
    (memory (export "memory") 1)
    (data (i32.const 0) "\10\00\00\00\02\00\00\00")
    (data (i32.const 16) "ok")
    (func (export "run") (result i32) call $wait i32.const 0))
  (core instance $host (export "wait" (func $lower)))
  (core instance $i (instantiate $m (with "host" (instance $host))))
  (func (export "run") (result string)
    (canon lift (core func $i "run") (memory $i "memory"))))
