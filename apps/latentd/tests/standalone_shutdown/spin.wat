(component
  (core module $guest
    (func (export "spin") (result i32)
      (loop $spin (br $spin))
      unreachable))
  (core instance $guest (instantiate $guest))
  (func $spin (result u32)
    (canon lift (core func $guest "spin")))
  (instance $api
    (export "spin" (func $spin)))
  (export "tests:shutdown/api@0.1.0" (instance $api)))
