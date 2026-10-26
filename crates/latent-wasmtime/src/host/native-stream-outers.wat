;; SOURCE ONLY. Derived from Wasmtime v48.0.7 async.rs canonical stream examples.
;; One hosted wasm-tools 1.254.0 parse; never assembled locally.
;; No network, clocks, allocator, imported host callback or background executor.
(component
  (core module $libc
    (memory (export "memory") 1)
    (data (i32.const 256) "*"))
  (core instance $libc (instantiate $libc))

  (type $stream (stream u8))
  (core func $new (canon stream.new $stream))
  (core func $read
    (canon stream.read $stream async (memory (core memory $libc "memory"))))
  (core func $write
    (canon stream.write $stream async (memory (core memory $libc "memory"))))

  (core module $guest
    (import "" "memory" (memory 1))
    (import "" "new" (func $new (result i64)))
    (import "" "read" (func $read (param i32 i32 i32) (result i32)))
    (import "" "write" (func $write (param i32 i32 i32) (result i32)))
    (global $writable (mut i32) (i32.const 0))

    ;; Transfer the readable half to the host; preserve the writable half here.
    (func (export "make") (result i32)
      (local $pair i64)
      (local.set $pair (call $new))
      (global.set $writable
        (i32.wrap_i64 (i64.shr_u (local.get $pair) (i64.const 32))))
      (i32.wrap_i64 (local.get $pair)))

    ;; The host supplies an ordinary StreamReader whose producer is HostReady.
    ;; Return the ORIGINAL canonical code; do not invent completion on BLOCKED.
    (func (export "read") (param $readable i32) (result i32)
      (local $code i32)
      (local.set $code (call $read (local.get $readable) (i32.const 512) (i32.const 1)))
      (local.get $code))

    ;; Host pipe() installs HostReady consumer before this actual guest entry.
    (func (export "write") (result i32)
      (local $code i32)
      (local.set $code (call $write (global.get $writable) (i32.const 256) (i32.const 1)))
      (local.get $code))

    (func (export "read-value") (result i32)
      (i32.load8_u (i32.const 512)))
    (func (export "answer") (result i32) (i32.const 42)))

  (core instance $guest (instantiate $guest
    (with "" (instance
      (export "memory" (memory $libc "memory"))
      (export "new" (func $new))
      (export "read" (func $read))
      (export "write" (func $write))))))

  (func (export "make") (result $stream)
    (canon lift (core func $guest "make")))
  (type $read-type (func async (param "reader" $stream) (result u32)))
  (type $write-type (func async (result u32)))
  (func (export "read") (type $read-type)
    (canon lift (core func $guest "read")))
  (func (export "write") (type $write-type)
    (canon lift (core func $guest "write")))
  (func (export "read-value") (result u32)
    (canon lift (core func $guest "read-value")))
  (func (export "answer") (result u32)
    (canon lift (core func $guest "answer"))))
