#!/bin/sh
# Test-only compiler adapter. This does not build or qualify SpiderMonkey/Wasm.
set -eu
exec "${LSF_TYPESCRIPT_SANITIZER_CXX:-clang++}" \
  -fsanitize=address,undefined -fno-sanitize-recover=all \
  -fno-omit-frame-pointer -g "$@"
