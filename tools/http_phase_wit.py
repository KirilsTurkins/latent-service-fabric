"""Nominal HTTP resource dependency for the selected phase-only WIT world.

WIT resolution implicitly imports a referenced interface. Retaining its legacy
operations would require a second operational provider rather than just the
unchanged resource identities used by phase-timing.
"""
from __future__ import annotations
import re
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, read_file


def nominal_type_owner(source: bytes) -> bytes:
    """Preserve canonical owners without importing the legacy callable surface."""
    require(source == read_file(ROOT / 'wit/platform/http-v3/package.wit'),
            'phase-fetch-nominal-canonical-preimage')
    pattern = rb'^    ([a-z-]+): async func[^\n]*;\n'
    names = re.findall(pattern, source, re.MULTILINE)
    require(names == [b'open', b'write', b'finish', b'read', b'chunk-bytes', b'trailers',
                      b'abort-upload', b'abort-body'], 'phase-fetch-nominal-exact-operations')
    return re.sub(pattern, b'', source, flags=re.MULTILINE)
