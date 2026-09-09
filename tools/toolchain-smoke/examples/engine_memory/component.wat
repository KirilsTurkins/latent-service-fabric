;; No start function, allocator, growth, or initialization touches the probe.
;; Page zero contains only the log message and canonical return scratch.
(component
  (type $logging (instance
    (type $level (enum "trace" "debug" "info" "warn" "error"))
    (export "level" (type $level-export (eq $level)))
    (type $field (record (field "name" string) (field "value" string)))
    (export "field" (type $field-export (eq $field)))
    (type $error (variant (case "budget-exhausted") (case "invalid-field" string) (case "unavailable")))
    (export "log-error" (type $error-export (eq $error)))
    (type $fields (list $field-export))
    (type $outcome (result bool (error $error-export)))
    (type $write (func (param "level" $level-export) (param "message" string) (param "fields" $fields) (result $outcome)))
    (export "write" (func (type $write)))))
  (import "latent:log/log@0.1.0" (instance $log (type $logging)))
  (alias export $log "write" (func $write))
  (core module $storage
    (memory (export "memory") 65 65)
    (data (i32.const 1024) "engine-memory-dirty-4194304-a5")
    ;; Host errors may contain a bounded string; their allocation is confined
    ;; to page zero and never overwrites the 4 MiB probe or silently succeeds.
    (func (export "realloc") (param i32 i32 i32) (param $size i32) (result i32)
      local.get $size i32.const 32768 i32.gt_u if unreachable end
      i32.const 32768))
  (core instance $storage (instantiate $storage))
  (alias core export $storage "memory" (core memory $memory))
  (alias core export $storage "realloc" (core func $realloc))
  (core func $write-lowered (canon lower (func $write) (memory $memory) (realloc $realloc)))
  (core module $guest
    (import "env" "memory" (memory 65 65))
    (import "env" "write" (func $write (param i32 i32 i32 i32 i32 i32)))
    (func (export "run") (param $mode i32) (result i32)
      (local $at i32) (local $bits i64) (local $loops i32)
      ;; Always inspect every byte before any dirty write. OR cannot hide a
      ;; nonzero byte through arithmetic wraparound or checksum cancellation.
      i32.const 65536 local.set $at
      loop $zero
        local.get $bits local.get $at i64.load i64.or local.set $bits
        local.get $at i32.const 8 i32.add local.tee $at
        i32.const 4259840 i32.lt_u br_if $zero
      end
      local.get $bits i64.const 0 i64.ne
      if i32.const -255 return end
      i32.const 65536 i32.const 165 i32.const 4194304 memory.fill
      i32.const 65536 local.set $at
      i64.const 0 local.set $bits
      loop $readback
        local.get $bits local.get $at i64.load
        i64.const 0xa5a5a5a5a5a5a5a5 i64.xor i64.or local.set $bits
        local.get $at i32.const 8 i32.add local.tee $at
        i32.const 4259840 i32.lt_u br_if $readback
      end
      local.get $bits i64.const 0 i64.ne
      if i32.const -254 return end
      ;; Canonical result area: result discriminant byte at 0, bool at 4.
      i32.const 2 i32.const 1024 i32.const 30 i32.const 0 i32.const 0 i32.const 0 call $write
      i32.const 0 i32.load8_u
      i32.const 4 i32.load8_u i32.const 1 i32.ne i32.or
      if i32.const -253 return end
      local.get $mode i32.const 1 i32.eq if unreachable end
      local.get $mode i32.const 2 i32.eq
      if
        i32.const 1000000000 local.set $loops
        loop $cancel
          i32.const 65536 i32.const 65536 i32.load i32.const 1 i32.add i32.store
          local.get $loops i32.const 1 i32.sub local.tee $loops br_if $cancel
        end
        i32.const -252 return
      end
      i32.const 692060160))
  (core instance $env
    (export "memory" (memory $memory))
    (export "write" (func $write-lowered)))
  (core instance $guest (instantiate $guest (with "env" (instance $env))))
  (type $mode (enum "success" "trap" "cancel"))
  (type $run (func (param "mode" $mode) (result u32)))
  (func $run (type $run) (canon lift (core func $guest "run")))
  (instance $api
    (export "mode" (type $mode))
    (export "run" (func $run)))
  (export "tests:engine-memory/memory@0.1.0" (instance $api)))
