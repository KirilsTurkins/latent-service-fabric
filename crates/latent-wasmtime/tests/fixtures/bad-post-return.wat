(component
  (core module $guest
    (func (export "value") (result i32) i32.const 7)
    (func (export "post") (param i32) unreachable))
  (core instance $guest (instantiate $guest))
  (func $value (result u32)
    (canon lift (core func $guest "value") (post-return (func $guest "post"))))
  (instance $api (export "value" (func $value)))
  (export "tests:adversarial/api@0.1.0" (instance $api)))
