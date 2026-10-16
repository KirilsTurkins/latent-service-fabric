"""Pinned standard net/http projection to the declared typed HTTP backend.

This finite HTTP-only candidate changes no application/library source, grants,
Client redirect policy or custom RoundTripper. Native execution remains required.
"""
from __future__ import annotations

from pathlib import Path
import re

from tools.go_guest.runtime import checked_sources, replace_once

PROFILE = 'go-net-http-typed-streaming-v1'
PREIMAGES = {
    'net/http/transport.go': 'c9146e77adc22d4b74ba77384ec7be7fc27c3af21ff20485f642b4d611b381a4',
    'net/http/roundtrip.go': 'a02501dcc615b6af4144655cd28f6a6901973267d2a188794e4552104dcf589a',
    'net/http/client.go': 'ced3428a85206de8de79c10de38d34951e0b9823c0ccb68ff51329d048a1f7b9',
}


def prepare(goroot: Path, sdk: Path, output: Path, module: str) -> dict[str, str]:
    if (not isinstance(module, str) or len(module) > 256
            or not re.fullmatch(r'[A-Za-z0-9._~/-]+', module)
            or any(part in {'', '.', '..'} for part in module.split('/'))):
        raise ValueError('go-standard-http-module-identity')
    source = checked_sources(goroot, PREIMAGES)
    template = (sdk/'runtime/http_transport.go.in').read_text()
    match = re.fullmatch(r'//[^\n]*\n//[^\n]*\npackage http\n\nimport \(\n(.*?)\n\)\n\n(.*)',
                         template, flags=re.S)
    if match is None or not match[2].startswith('const lsfHTTPMaximumBody = '):
        raise ValueError('go-standard-http-template-shape')
    imports = match[1].replace('@module@', module)
    body = match[2]
    selected = {
        'net/http/roundtrip.go': replace_once(source['net/http/roundtrip.go'],
            'import _ "unsafe" // for linkname', 'import (\n\t_ "unsafe" // for linkname\n'+imports+'\n)')
    }
    selected['net/http/roundtrip.go'] = replace_once(selected['net/http/roundtrip.go'],
        '\treturn t.roundTrip(req)\n', '\treturn lsfTransportRoundTrip(t, req)\n')+'\n'+body
    # Automatic wire compression is excluded by the current typed contract.
    # Make the finite default explicit; a concrete Transport requesting it is
    # rejected instead of silently ignoring its field or adding a reserved header.
    selected['net/http/transport.go'] = replace_once(source['net/http/transport.go'],
        'var DefaultTransport RoundTripper = &Transport{\n',
        'var DefaultTransport RoundTripper = &Transport{\n\tDisableCompression: true,\n')
    output.mkdir()
    replacements = {}
    for name, text in selected.items():
        path = output/name.replace('/', '_')
        path.write_text(text, encoding='utf-8')
        replacements[str(goroot/'src'/name)] = str(path)
    return replacements
