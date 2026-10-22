;; Explicit async component types with the ordinary synchronous Core ABI.
;; This exercises legal blocking of an async task on a concurrent host callback.
(component
  (type $wait-type (func async (result u32)))
  (import "wait" (func $wait (type $wait-type)))
  (core func $wait-core (canon lower (func $wait)))
  (core module $guest
    (import "host" "wait" (func $wait (result i32)))
    (func (export "run") (result i32) call $wait))
  (core instance $host (export "wait" (func $wait-core)))
  (core instance $guest (instantiate $guest (with "host" (instance $host))))
  (type $run-type (func async (result u32)))
  (func (export "run") (type $run-type)
    (canon lift (core func $guest "run"))))
