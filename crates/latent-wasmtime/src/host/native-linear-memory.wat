(module
  (memory (export "memory") 4 5)
  (data (i32.const 0) "actual-memory")
  (func (export "answer") (result i32) i32.const 42))
