"""Source-pinned finite net.Dial projection to an explicitly declared stream.

This installs no provider, grant, resolver, TLS implementation or retry. The
normal provider's accounting refusal remains independent of compiler selection.
"""
from __future__ import annotations

from pathlib import Path
import re

from tools.go_guest.runtime import checked_sources, replace_once

PROFILE = 'go-net-declared-streams-v1'
PREIMAGES = {
    'crypto/tls/cache.go': '553ad7a40a9b198bea838833e3e5ed5660ec9b031ad75f58a9ea119e44bd3bfb',
    'net/dial.go': '1ea8719962e33747db841fae362a339c29315fde2c5554a344b2935aa6f803b5',
    'net/lookup.go': 'e8b6b0a0dc7ca0715fe14e6599b1784dc85ce59689e0cb3f9a7fe3eea26ada19',
    'net/tcpsock.go': '0c3392bd7c2966f894e01ea27514623cf09dc2660e426049219f7e5ee3ec0f74',
}


def function(text: str, signature: str, body: str) -> str:
    # Complete upstream files were authenticated first. Go's pinned declarations
    # close at column zero; unexpected/multiple shapes are not rewritten.
    pattern = r'(?ms)^' + re.escape(signature) + r' \{\n.*?^\}'
    found = list(re.finditer(pattern, text))
    if len(found) != 1:
        raise ValueError('go-standard-network-declaration-drift')
    return text[:found[0].start()] + signature + ' {\n' + body + '\n}' + text[found[0].end():]


def prepare(goroot: Path, sdk: Path, output: Path, module: str) -> dict[str, str]:
    if (not isinstance(module, str) or len(module) > 256
            or not re.fullmatch(r'[A-Za-z0-9._~/-]+', module)
            or any(part in {'', '.', '..'} for part in module.split('/'))):
        raise ValueError('go-standard-network-module-identity')
    sources = checked_sources(goroot, PREIMAGES)
    template = (sdk / 'runtime/net_stream.go.in').read_text(encoding='utf-8')
    match = re.fullmatch(r'//[^\n]*\n//[^\n]*\npackage net\n\nimport \(\n(.*?)\n\)\n\n(.*)',
                         template, flags=re.S)
    if match is None or not match[2].startswith('const lsfStreamMaximumChunk = '):
        raise ValueError('go-standard-network-template-shape')
    dial = function(sources['net/dial.go'],
        'func (d *Dialer) DialContext(ctx context.Context, network, address string) (Conn, error)',
        '\treturn lsfStreamDial(ctx, d, network, address)')
    dial = function(dial,
        'func (d *Dialer) DialTCP(ctx context.Context, network string, laddr netip.AddrPort, raddr netip.AddrPort) (*TCPConn, error)',
        '\treturn nil, &OpError{Op: "dial", Net: network, Err: lsfStreamUnsupported()}')
    dial = replace_once(dial, 'import (\n',
        'import (\n' + match[1].replace('@module@', module) + '\n') + '\n' + match[2]
    tcp = function(sources['net/tcpsock.go'],
        'func DialTCP(network string, laddr, raddr *TCPAddr) (*TCPConn, error)',
        '\treturn nil, &OpError{Op: "dial", Net: network, Err: lsfStreamUnsupported()}')
    lookup = sources['net/lookup.go']
    signatures = {
        'func (r *Resolver) LookupHost(ctx context.Context, host string) (addrs []string, err error)': 'nil',
        'func (r *Resolver) LookupIPAddr(ctx context.Context, host string) ([]IPAddr, error)': 'nil',
        'func (r *Resolver) LookupIP(ctx context.Context, network, host string) ([]IP, error)': 'nil',
        'func (r *Resolver) LookupNetIP(ctx context.Context, network, host string) ([]netip.Addr, error)': 'nil',
        'func (r *Resolver) LookupCNAME(ctx context.Context, host string) (string, error)': '""',
        'func (r *Resolver) LookupSRV(ctx context.Context, service, proto, name string) (string, []*SRV, error)': '"", nil',
        'func (r *Resolver) LookupMX(ctx context.Context, name string) ([]*MX, error)': 'nil',
        'func (r *Resolver) LookupNS(ctx context.Context, name string) ([]*NS, error)': 'nil',
        'func (r *Resolver) LookupTXT(ctx context.Context, name string) ([]string, error)': 'nil',
        'func (r *Resolver) LookupAddr(ctx context.Context, addr string) ([]string, error)': 'nil',
    }
    for signature, empty in signatures.items():
        lookup = function(lookup, signature, '\treturn ' + empty + ', errors.ErrUnsupported')
    lookup = function(lookup,
        'func (r *Resolver) LookupPort(ctx context.Context, network, service string) (port int, err error)',
        '\tport, needsLookup := parsePort(service)\n'
        '\tif needsLookup { return 0, errors.ErrUnsupported }\n'
        '\tif port < 0 || port > 65535 { return 0, &AddrError{Err: "invalid port", Addr: service} }\n'
        '\treturn port, nil')
    # Only the removed public DNS bodies referenced this package. Preserve its
    # original dependency/initialization edge instead of deleting the import.
    lookup = replace_once(lookup, '\t"internal/stringslite"\n', '\t_ "internal/stringslite"\n')
    # Only the declared-stream managed-v5 path uses this bounded private cache.
    # Its whole upstream file was authenticated before any overlay is published.
    # Application cleanup callbacks remain explicitly refused by activation.py.
    cert_cache = (sdk / 'runtime/tls_cert_cache.go.in').read_text(encoding='utf-8')
    if not cert_cache.startswith('// Compiler-owned bounded Go TLS certificate cache.\npackage tls\n'):
        raise ValueError('go-standard-network-tls-cache-template-shape')
    output.mkdir()
    replacements = {}
    for name, text in {'net/dial.go': dial, 'net/tcpsock.go': tcp, 'net/lookup.go': lookup,
                       'crypto/tls/cache.go': cert_cache}.items():
        path = output / name.replace('/', '_')
        path.write_text(text, encoding='utf-8', newline='\n')
        replacements[str(goroot / 'src' / name)] = str(path)
    return replacements
