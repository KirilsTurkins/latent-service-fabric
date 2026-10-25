(component
  (core module $code
    (func $depth (result i32)
      call $depth
      i32.const 1
      i32.add)
    (func (export "run") (param i32) (result i32)
      local.get 0
      if (result i32)
        call $depth
      else
        i32.const 42
      end))
  (core instance $instance (instantiate $code))
  (func $run (param "recurse" bool) (result u32)
    (canon lift (core func $instance "run")))
  (instance $api (export "run" (func $run)))
  (export "examples:compatibility-stack/api@1.0.0" (instance $api)))
