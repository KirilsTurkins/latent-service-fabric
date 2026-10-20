"""Ordinary named BCL calls, with independent pure and explicit TaskWait roots."""
from pathlib import Path

from tools.dotnet_guest.runtime import ACTIVATION
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot
from tools.sdk_scratch_fixture import project as scratch_project


def project(output: Path, *, joined: bool):
    require(type(joined) is bool, 'closed-filesystem-fixture-profile')
    app, record = scratch_project('dotnet', output)
    sdk = read_file(app / 'sdk-lock.json')
    if joined:
        path = app / 'wit/world.wit'
        source = read_file(path)
        require(source.count(b'greet: func(') == source.count(b'world service {') == 1,
                'closed-filesystem-async-world-preimage')
        path.write_bytes(source.replace(b'greet: func(', b'greet: async func(', 1).replace(
            b'world service {', b'world service {\n    import ' + ACTIVATION.encode() + b';', 1))
        for name, data in snapshot(ROOT / 'wit/platform/activation-runtime').items():
            target = app / 'wit/deps/activation-runtime' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
    require(read_file(app / 'sdk-lock.json') == sdk, 'closed-filesystem-original-sdk-lock')
    return app, {**record, 'sourceDigest': digest(inventory(snapshot(app))),
        'explicitTaskWaitWorld': joined, 'sdkProfileAndLimitsChanged': joined,
        'sdkLockChanged': False, 'filesystemGrantsAdded': False, 'invalidArgumentCalls': 6}
