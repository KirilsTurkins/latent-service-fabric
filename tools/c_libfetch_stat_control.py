#!/usr/bin/env python3
"""Linux source controls for libfetch Stat and Range; HTTP ports are doubles."""
from pathlib import Path
import argparse
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wasm32', action='store_true',
                        help='require the wasm32 metadata control')
    parser.add_argument('--zig', help='path to the pinned Zig executable')
    parser.add_argument('--node', help='path to the Node executable')
    args = parser.parse_args()
    if args.wasm32:
        if not args.zig or not args.node:
            parser.error('--wasm32 requires both --zig and --node')
        zig = Path(args.zig).resolve(strict=True)
        node = Path(args.node).resolve(strict=True)
        if not zig.is_file() or not node.is_file():
            parser.error('--zig and --node must name executable files')
    elif args.zig or args.node:
        parser.error('--zig and --node require --wasm32')
    fixture = ROOT / 'tools/tests/fixtures/c-libfetch-stat'
    with tempfile.TemporaryDirectory(prefix='lsf-c-libfetch-stat-') as owned:
        for name in ('c-libfetch-stat', 'c-libfetch-range'):
            executable = Path(owned) / name
            control = ROOT / 'tools/tests/fixtures' / name / 'control.c'
            subprocess.run([
                'gcc', '-std=gnu11', '-D_GNU_SOURCE', '-ffunction-sections', '-fdata-sections',
                '-I' + str(fixture), '-I' + str(ROOT / 'sdk/c-guest/include'),
                str(ROOT / 'sdk/c-guest/src/libfetch/fetch.c'),
                str(ROOT / 'sdk/c-guest/src/libfetch/http.c'), str(control),
                '-Wl,--gc-sections', '-o', str(executable),
            ], check=True, timeout=60)
            subprocess.run([str(executable)], check=True, timeout=10)
        executable = Path(owned) / 'range-probe'
        subprocess.run([
            'gcc', '-std=gnu11', '-D_GNU_SOURCE', '-ffunction-sections', '-fdata-sections',
            '-I' + str(fixture), '-I' + str(ROOT / 'sdk/c-guest/include'),
            str(ROOT / 'sdk/c-guest/src/libfetch/fetch.c'),
            str(ROOT / 'sdk/c-guest/src/libfetch/http.c'),
            str(ROOT / 'sdk/c-guest/runtime-fixtures/libfetch/stat-probe.c'),
            str(fixture / 'range-probe-control.c'), '-Wl,--gc-sections', '-o', str(executable),
        ], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=10)
        if args.wasm32:
            # Include the real backend with the existing port declarations;
            # garbage-collect unrelated code and run only metadata conversion.
            includes = zig.parent / 'lib/libc/include'
            wasm = Path(owned) / 'metadata.wasm'
            subprocess.run([
                str(zig), 'cc', '-target', 'wasm32-wasi', '-std=c11', '-O2',
                '-Wall', '-Wextra', '-Werror', '-ffunction-sections', '-fdata-sections',
                '-nostdlib', '-isystem', str(includes / 'wasm-wasi-musl'),
                '-isystem', str(includes / 'generic-musl'), '-Wl,--gc-sections', '-Wl,--no-entry',
                '-I' + str(ROOT), '-I' + str(fixture), '-I' + str(ROOT / 'sdk/c-guest/include'),
                str(fixture / 'wasm-metadata.c'), '-o', str(wasm),
            ], check=True, timeout=60)
            subprocess.run([str(node), str(fixture / 'wasm-metadata.js'), str(wasm)],
                           check=True, timeout=10)
        subprocess.run([
            'gcc', '-std=gnu11', '-D_GNU_SOURCE', '-fsyntax-only', '-I' + str(fixture),
            '-I' + str(ROOT / 'sdk/c-guest/include'),
            str(ROOT / 'sdk/c-guest/runtime-fixtures/libfetch/stat-probe.c'),
        ], check=True, timeout=30)


if __name__ == '__main__':
    main()
