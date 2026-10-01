"""Exact SDK-owned component composer with the upstream resource alias fix."""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.request

from tools.build_observation import file_identity
from tools.build_snapshot import digest
from tools.rust_capsule_project import read_file


VERSION = '0.10.1'
SIZE = 21726840
DIGEST = 'sha256:250c11762916ba733c7d22b62487580f21270ec9dde4f13460ea69d300e25406'
URL = 'https://github.com/bytecodealliance/wac/releases/download/v0.10.1/wac-cli-x86_64-unknown-linux-musl'


def selection(sdk: Path) -> dict:
    value = json.loads(read_file(sdk / 'component-composer.json'))
    expected = {'formatVersion': 1, 'version': VERSION, 'target': 'x86_64-unknown-linux-musl',
        'size': SIZE, 'digest': DIGEST, 'url': URL, 'upstreamFix': 'https://github.com/bytecodealliance/wac/pull/205'}
    if value != expected:
        raise ValueError('unreviewed .NET component composer profile')
    return value


def observed(directory: Path, sdk: Path) -> Path:
    pin = selection(sdk)
    binary = directory / 'component-composer/wac'
    identity = file_identity(binary, 'component-composer', SIZE)
    if identity['digest'] != pin['digest'] or identity['size'] != pin['size']:
        raise ValueError('component composer differs from the reviewed resource alias fix')
    return binary


def install(directory: Path, sdk: Path, commands) -> Path:
    pin = selection(sdk)
    started, data = time.monotonic(), bytearray()
    request = urllib.request.Request(pin['url'], headers={'User-Agent': 'LSF-SDK-tool-fetch'})
    with urllib.request.urlopen(request, timeout=30) as response:
        while block := response.read(65536):
            data.extend(block)
            if len(data) > SIZE or time.monotonic() - started > 180:
                raise ValueError('component composer fetch bound exceeded')
    if len(data) != SIZE or digest(data) != pin['digest']:
        raise ValueError('component composer download identity mismatch')
    output = directory / 'component-composer'
    output.mkdir()
    binary = output / 'wac'
    with binary.open('xb') as stream:
        stream.write(data)
    binary.chmod(0o755)
    if commands.run('component-composer-version', binary, '--version').strip() != b'wac-cli 0.10.1':
        raise ValueError('component composer version drift')
    return observed(directory, sdk)
