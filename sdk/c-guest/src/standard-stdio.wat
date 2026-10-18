;; SPDX-License-Identifier: Apache-2.0
(module
  (import "__main_module__" "lsf_c_stdio_fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "__main_module__" "lsf_c_stdio_fd_fdstat_get" (func $fd_fdstat_get (param i32 i32) (result i32)))
  (import "__main_module__" "lsf_c_stdio_fd_seek" (func $fd_seek (param i32 i64 i32 i32) (result i32)))
  (import "__main_module__" "lsf_c_stdio_fd_close" (func $fd_close (param i32) (result i32)))
  (export "fd_write" (func $fd_write))
  (export "fd_fdstat_get" (func $fd_fdstat_get))
  (export "fd_seek" (func $fd_seek))
  (export "fd_close" (func $fd_close))
)
