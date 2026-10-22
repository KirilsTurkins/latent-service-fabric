(component
  (import "host-resource" (type $host (sub resource)))
  (type $guest (resource (rep i32)))
  (core module $module
    (func (export "answer") (result i32) i32.const 42)
    (func (export "pass") (param i32) (result i32) local.get 0))
  (core instance $instance (instantiate $module))
  (func (export "answer") (result u32)
    (canon lift (core func $instance "answer")))
  (func (export "host-pass") (param "value" (own $host)) (result (own $host))
    (canon lift (core func $instance "pass")))
  (export "guest-resource" (type $guest)))
