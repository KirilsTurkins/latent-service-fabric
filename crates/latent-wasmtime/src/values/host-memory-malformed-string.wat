;; Synthetic malformed UTF-8 result fixture; no imports or external effects.
;; Regenerate: wasm-tools parse host-memory-malformed-string.wat -o host-memory-malformed-string.wasm
(component
      (core module $m
        (memory (export "memory") 1)
        (data (i32.const 0) "\10\00\00\00\01\00\00\00")
        (data (i32.const 16) "\ff")
        (func (export "run") (result i32) i32.const 0))
      (core instance $i (instantiate $m))
      (func (export "run") (result string)
        (canon lift (core func $i "run") (memory $i "memory"))))
