#!/usr/bin/env python3
"""Linux source control for the C libfetch Stat path; HTTP ports are doubles."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    fixture = ROOT / 'tools/tests/fixtures/c-libfetch-stat'
    with tempfile.TemporaryDirectory(prefix='lsf-c-libfetch-stat-') as owned:
        executable = Path(owned) / 'control'
        subprocess.run([
            'gcc', '-std=gnu11', '-D_GNU_SOURCE', '-ffunction-sections', '-fdata-sections',
            '-I' + str(fixture), '-I' + str(ROOT / 'sdk/c-guest/include'),
            str(ROOT / 'sdk/c-guest/src/libfetch/fetch.c'),
            str(ROOT / 'sdk/c-guest/src/libfetch/http.c'), str(fixture / 'control.c'),
            '-Wl,--gc-sections', '-o', str(executable),
        ], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=10)
        subprocess.run([
            'gcc', '-std=gnu11', '-D_GNU_SOURCE', '-fsyntax-only', '-I' + str(fixture),
            '-I' + str(ROOT / 'sdk/c-guest/include'),
            str(ROOT / 'sdk/c-guest/runtime-fixtures/libfetch/stat-probe.c'),
        ], check=True, timeout=30)


if __name__ == '__main__':
    main()
