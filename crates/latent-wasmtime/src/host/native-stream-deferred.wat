;; SOURCE ONLY. Nested version of the existing native stream fixture.
;; A hosted owner must parse it and prove the actual guest call is deferred.
(component
  (component $inner
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
    (func (export "write-sync") (result u32)
      (canon lift (core func $guest "write")))
    (func (export "answer") (result u32)
      (canon lift (core func $guest "answer"))))

  (instance $inner-instance (instantiate $inner))
  (alias export $inner-instance "make" (func $make))
  (alias export $inner-instance "read" (func $read))
  (alias export $inner-instance "read-value" (func $read-value))
  (alias export $inner-instance "answer" (func $answer))
  (alias export $inner-instance "write-sync" (func $write-sync))
  ;; The caller and stream owner are siblings: an ancestor-to-child adapter
  ;; unconditionally traps CannotEnterComponent before the stream operation.
  (component $caller
    (type $write-sync-type (func (result u32)))
    (import "call-write" (func $import-write (type $write-sync-type)))
    (core func $call-write (canon lower (func $import-write)))
    (core module $forwarder
      (import "" "call-write" (func $call-write (result i32)))
      (func (export "forward") (result i32) (call $call-write)))
    (core instance $forwarder (instantiate $forwarder
      (with "" (instance (export "call-write" (func $call-write))))))
    (type $forward-type (func async (result u32)))
    (func (export "write") (type $forward-type)
      (canon lift (core func $forwarder "forward"))))
  (instance $caller-instance
    (instantiate $caller (with "call-write" (func $write-sync))))
  (alias export $caller-instance "write" (func $write))
  (export "write" (func $write))
  (export "make" (func $make))
  (export "read" (func $read))
  (export "read-value" (func $read-value))
  (export "answer" (func $answer)))
