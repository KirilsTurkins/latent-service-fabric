#!/usr/bin/env python3
"""Prepare the pinned font-based PrimeIcons build input with WOFF2 only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_snapshot import SnapshotError, is_reparse
from tools.static_site import read, require


def prepare_primeicons(package: Path, output: Path) -> None:
    package, output = package.absolute(), output.absolute()
    require(not output.exists() and output.parent.is_dir()
            and package != output and package not in output.parents
            and not any(is_reparse(p) for p in [output.parent, *output.parents]), 'font-output')
    metadata = json.loads(read(package, 'package.json', 65536))
    require(metadata.get('name') == 'primeicons' and metadata.get('version') == '8.0.2', 'font-package-version')
    css = read(package, 'primeicons.css', 128 * 1024).decode('utf-8')
    font = read(package, 'fonts/primeicons.woff2', 1024 * 1024)
    license_bytes = read(package, 'LICENSE.md', 65536)
    require(font.startswith(b'wOF2') and len(font) >= 48 and license_bytes, 'font-input')
    faces = list(re.finditer(r'@font-face\s*\{[^{}]*\}', css))
    require(len(faces) == 1 and re.search(r'font-family\s*:\s*[\'"]primeicons[\'"]', faces[0][0]), 'font-face-profile')
    face = "@font-face {\n  font-family: 'primeicons';\n  font-display: block;\n  src: url('./primeicons.woff2') format('woff2');\n  font-weight: normal;\n  font-style: normal;\n}\n"
    css = css[:faces[0].start()] + face + css[faces[0].end():]
    # This is a closed preparation recipe, not a general CSS sanitizer.
    urls = re.findall(r'url\s*\(([^)]*)\)', css, flags=re.I)
    require(urls == ["'./primeicons.woff2'"] and not re.search(r'@import\b', css, re.I), 'font-unexpected-resource')
    output.mkdir()
    for name, data in [('primeicons.css', css.encode()), ('primeicons.woff2', font), ('LICENSE.txt', license_bytes)]:
        with (output / name).open('xb') as stream:
            stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primeicons', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_primeicons(args.primeicons, args.output)
        return 0
    except (SnapshotError, OSError, ValueError, UnicodeError) as error:
        print(str(error) if isinstance(error, SnapshotError) else 'static-site-font-preparation-failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
