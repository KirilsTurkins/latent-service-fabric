(component
  (type $handle (resource (rep i32)))
  (core module $guest (func (export "take") (param i32)))
  (core instance $guest (instantiate $guest))
  (func $take (param "value" (borrow $handle))
    (canon lift (core func $guest "take")))
  (instance $api
    (export "handle" (type $handle))
    (export "take" (func $take)))
  (export "tests:adversarial/api@0.1.0" (instance $api)))
