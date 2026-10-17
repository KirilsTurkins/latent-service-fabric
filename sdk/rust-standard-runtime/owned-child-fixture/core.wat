;; Transparent canonical-child mechanism control. No Rust/std code executes.
;; All Task and Native owners come from the original protected host imports.
(module
  (import "$root" "[context-get-1]" (func $get (result i32)))
  (import "$root" "[context-set-1]" (func $set (param i32)))
  (import "$root" "[thread-new-indirect-v0]" (func $new (param i32 i32) (result i32)))
  (import "$root" "[thread-yield-then-resume]" (func $switch (param i32) (result i32)))
  (import "latent:runtime-native/threads@0.1.0" "start" (func $admit (param i64 i64 i32)))
  (import "latent:runtime/activation@0.1.0" "register" (func $register (param i32 i32 i64 i64 i32)))
  (import "latent:runtime/activation@0.1.0" "settle" (func $settle (param i64 i64 i32)))
  (import "[export]tests:caller/api@1.0.0" "[task-return]run" (func $return (param i32)))
  (table (export "__indirect_function_table") 1 1 funcref)
  (memory (export "memory") 4 4)
  (global $sp (export "__stack_pointer") (mut i32) (i32.const 131072))
  (global (export "__stack_low") i32 (i32.const 65536))
  (global $mode (mut i32) (i32.const 0))

  (func $require (param i32)
    local.get 0 i32.eqz if unreachable end)
  (func $task (param $context i32) (param $kind i32)
    local.get 1 i32.const 0 i64.const 0 i64.const 0 i32.const 1024 call $register
    i32.const 1024 i32.load8_u i32.eqz call $require
    local.get 0 i32.const 1024 i64.load offset=8 i64.store offset=16
    local.get 0 i32.const 1024 i64.load offset=16 i64.store offset=24)
  (func $settle-task (param i32)
    local.get 0 i64.load offset=16 local.get 0 i64.load offset=24
    i32.const 1088 call $settle
    i32.const 1088 i32.load8_u i32.eqz call $require)
  (func $prepare (param $context i32)
    local.get 0 i32.const 196608 i32.store
    local.get 0 i32.const 131072 i32.store offset=4
    local.get 0 i32.const 196608 i32.store offset=8
    local.get 0 i32.const 1 i32.store offset=12)

  (func $entry (export "__lsf_rust_owned_thread_entry") (param $context i32)
    call $get local.get 0 i32.eq call $require
    global.get $sp i32.const 196608 i32.eq call $require
    global.get $sp i32.const 16 i32.sub global.set $sp
    local.get 0 i32.load i32.const 196592 i32.eq call $require
    global.get $sp i32.const 16 i32.add global.set $sp
    global.get $mode i32.const 1 i32.eq if unreachable end
    global.get $mode i32.const 2 i32.eq if (loop $spin br $spin) end
    i32.const 900 i32.const 42 i32.store
    local.get 0 i32.const 4 i32.store offset=12)
  (elem (i32.const 0) func $entry)

  (func $run (param $which i32) (result i32)
    (local $child i32)
    local.get 0 global.set $mode
    global.get $sp i32.const 131072 i32.eq call $require
    i32.const 512 call $prepare
    i32.const 512 local.get 0 i32.const 5 i32.eq
    if (result i32) i32.const 2 else i32.const 0 end call $task
    i32.const 0 i32.const 512 call $new local.set $child
    ;; A canonical handle is real accepted work even before its first resume.
    local.get 0 i32.const 6 i32.eq if i32.const 42 return end
    local.get $child call $switch drop
    call $get i32.const 256 i32.eq call $require
    global.get $sp i32.const 131072 i32.eq call $require
    i32.const 512 i32.load offset=12 i32.const 5 i32.eq call $require
    i32.const 900 i32.load i32.const 42 i32.eq call $require
    local.get 0 i32.const 3 i32.eq
    if
      ;; A fresh context and reset byte cannot reuse an original Task token.
      i32.const 768 call $prepare
      i32.const 768 i32.const 512 i64.load offset=16 i64.store offset=16
      i32.const 768 i32.const 512 i64.load offset=24 i64.store offset=24
      i32.const 0 i32.const 768 call $new drop
      unreachable
    end
    local.get 0 i32.const 4 i32.eq
    if
      ;; The first child returned; its engine-owned stack/metadata remain charged.
      i32.const 768 call $prepare
      i32.const 768 i32.const 0 call $task
      i32.const 0 i32.const 768 call $new drop
      unreachable
    end
    i32.const 512 call $settle-task
    i32.const 42)

  (func (export "[async-lift-stackful]tests:caller/api@1.0.0#run")
        (export "__lsf_rust_activation_root") (param i32)
    local.get 0 call $run call $return)

  (func (export "__lsf_rust_root_bootstrap") (param $low i32) (param $high i32) (result i32)
    i32.const 256 i32.const 0 call $task
    i32.const 256 local.get 1 i32.store
    i32.const 256 local.get 0 i32.store offset=4
    i32.const 256 local.get 1 i32.store offset=8
    i32.const 256 i32.const 1 i32.store offset=12
    i32.const 256)
  (func (export "__lsf_rust_root_finish") (param i32)
    local.get 0 i32.const 4 i32.store offset=12)
  (func (export "__lsf_rust_root_reap") (param i32)
    call $get i32.eqz call $require
    local.get 0 i32.load offset=12 i32.const 5 i32.eq call $require
    local.get 0 call $settle-task)
)
