(component
  (type $required (instance (export "read" (func (result u32)))))
  (import "tests:unavailable/host@0.1.0" (instance (type $required)))
  (core module $guest (func (export "value") (result i32) i32.const 7))
  (core instance $guest (instantiate $guest))
  (func $value (result u32) (canon lift (core func $guest "value")))
  (instance $api (export "value" (func $value)))
  (export "tests:adversarial/api@0.1.0" (instance $api)))
