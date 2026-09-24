;; Private reactor environment, no ambient process access. The only effects
;; here are the declared LSF clock capabilities, still authorized by the host.
(module
  (import "env" "memory" (memory 0))
  (import "latent:clock/monotonic@0.1.0" "now-nanos" (func $mono (result i64)))
  (import "latent:clock/wall@0.1.0" "now-unix-millis" (func $wall (result i64)))
  (func (export "environ_sizes_get") (param $count i32) (param $bytes i32) (result i32)
    local.get $count i32.const 0 i32.store
    local.get $bytes i32.const 0 i32.store
    i32.const 0)
  (func (export "environ_get") (param i32 i32) (result i32) i32.const 0)
  (func (export "proc_exit") (param i32) unreachable)
  (func (export "clock_time_get") (param $clock i32) (param i64) (param $out i32) (result i32)
    (local $time i64)
    local.get $clock i32.eqz
    if
      call $wall local.set $time
      local.get $time i64.const 18446744073709 i64.gt_u
      if unreachable end
      local.get $time i64.const 1000000 i64.mul local.set $time
    else
      local.get $clock i32.const 1 i32.ne
      if unreachable end
      call $mono local.set $time
    end
    local.get $out local.get $time i64.store
    i32.const 0)
)
