;; Encoder/routing source control only. No Rust/std or guest execution claim.
(module
  (import "$root" "[context-get-1]" (func $get (result i32)))
  (import "$root" "[context-set-1]" (func $set (param i32)))
  (import "$root" "[thread-new-indirect-v0]" (func $new (param i32 i32) (result i32)))
  (import "latent:runtime-native/threads@0.1.0" "start" (func $admit (param i64 i64 i32)))
  (table (export "__indirect_function_table") 1 1 funcref)
  (memory (export "memory") 4 4)
  (global (export "__stack_pointer") (mut i32) (i32.const 131072))
  (global (export "__stack_low") i32 (i32.const 65536))
  (func $entry (export "__lsf_rust_owned_thread_entry") (param i32))
  (elem (i32.const 0) func $entry)
  (func (export "run") (export "__lsf_rust_activation_root") (result i32) (i32.const 42))
  (func (export "__lsf_rust_root_bootstrap") (param i32 i32) (result i32) (local.get 1))
  (func (export "__lsf_rust_root_finish") (param i32))
  (func (export "__lsf_rust_root_reap") (param i32))
  ;; A deliberately unrelated local result producer for the provider-origin
  ;; negative. The normal fixture never routes native admission to this body.
  (func (export "fake-native") (param i64 i64) (result i32)
    i32.const 192 i32.const 0 i32.store8 i32.const 192)
  (func (export "noop"))
)
