"""Owned additions to the unchanged published-client and private-worker fixture."""
from __future__ import annotations

import json
from pathlib import Path

from tools.go_http_library_fixture import capture_source
from tools.go_guest.activation import INITIALIZER_PROFILE, MANAGED_PROFILE
from tools.rust_capsule_project import ROOT, digest, read_file

LIBRARY_SOURCE = 'sdk/go-guest/runtime/http-library-conformance/main.go'
CONTROL_SOURCE = 'tools/fixtures/go-http-tenants/control.go'
ANCHOR = b'\tlibrary, mode := which/100, which%100\n'
DISPATCH = b'\tif which >= 300 && which <= 302 { return tenantControl(which,address) }\n'


def derive(original: bytes) -> bytes:
    if original.count(ANCHOR) != 1 or DISPATCH in original:
        raise ValueError('go-http-tenant-original-client-source-drift')
    return original.replace(ANCHOR, DISPATCH + ANCHOR)


def project(directory: Path, outside: Path, identity: str, *, runtime_profile=INITIALIZER_PROFILE):
    if type(runtime_profile) is not str or runtime_profile not in {INITIALIZER_PROFILE,MANAGED_PROFILE}:
        raise ValueError('go-http-tenant-closed-runtime-profile')
    app, library = capture_source(directory, outside, identity)
    original = read_file(app/'src/main.go')
    source = derive(original)
    (app/'src/main.go').write_bytes(source)
    (app/'src/tenant.go').write_bytes(read_file(ROOT/CONTROL_SOURCE))
    descriptor = json.loads(read_file(app/'capsule-project.json'))
    descriptor['runtimeProfile'] = runtime_profile
    (app/'capsule-project.json').write_bytes((json.dumps(descriptor,indent=2)+'\n').encode())
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_bytes((json.dumps(lock,indent=2)+'\n').encode())
    return app, library
