"""Explicit public CA inputs for one owned Linux Go resolver child."""
import re
import ssl
import sys

from tools.application_dependency_store import DependencyError, path_name, read_bytes, regular_path
from tools.build_snapshot import digest

PROFILE = 'go-linux-explicit-proxy-ca-v1'
MAX_BYTES = 512 * 1024
MAX_CERTIFICATES = 256
PEM = re.compile(rb'(?:-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----[ \t\r\n]*)+')


def selection(policy):
    if 'tlsTrust' not in policy:
        return None
    value = policy['tlsTrust']
    if not isinstance(value, dict) or set(value) != {'caFile'}:
        raise DependencyError('go-proxy-public-trust-declaration-invalid')
    name = path_name(value['caFile'])
    if name.split('/')[0] in {'vendor', 'target', 'dependency-inputs', 'application-vendor', 'dependencies', '.git'}:
        raise DependencyError('go-proxy-public-trust-path-invalid')
    return name


def public_bundle(raw):
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES
            or not PEM.fullmatch(raw.strip())
            or not 1 <= raw.count(b'-----BEGIN CERTIFICATE-----') <= MAX_CERTIFICATES):
        raise DependencyError('go-proxy-public-ca-bundle-required')
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=raw.decode('ascii'))
    except (UnicodeError, ValueError, ssl.SSLError):
        raise DependencyError('go-proxy-public-ca-bundle-required') from None
    return raw


def source(project, name):
    try:
        path = regular_path(project / name)
        if not path.resolve(strict=True).is_relative_to(project.resolve(strict=True)) or path.stat().st_nlink != 1:
            raise ValueError()
        return public_bundle(read_bytes(path, MAX_BYTES))
    except (OSError, ValueError):
        raise DependencyError('go-proxy-public-ca-unavailable-or-changed') from None


def identity(name, raw):
    return {'profile': PROFILE, 'caFile': name, 'digest': digest(raw), 'size': len(raw)}


def prepare(project, owned, policy, environment):
    name = selection(policy)
    if name is None:
        return None
    if sys.platform != 'linux':
        raise DependencyError('go-proxy-explicit-ca-requires-linux')
    raw = source(project, name)
    owned = regular_path(owned).resolve(strict=True)
    root = owned / 'go-proxy-trust'
    root.mkdir(mode=0o700)
    bundle, directory = root / 'public-ca.pem', root / 'empty-certificates'
    with bundle.open('xb') as output:
        output.write(raw)
    bundle.chmod(0o600)
    directory.mkdir(mode=0o700)
    environment.update(SSL_CERT_FILE=str(bundle), SSL_CERT_DIR=str(directory))
    return check(project, owned, policy, environment)


def check(project, owned, policy, environment):
    name = selection(policy)
    if name is None:
        return None
    raw = source(project, name)
    root = regular_path(owned / 'go-proxy-trust')
    bundle, directory = root / 'public-ca.pem', root / 'empty-certificates'
    try:
        if (read_bytes(bundle, MAX_BYTES) != raw or bundle.stat().st_nlink != 1
                or not directory.is_dir() or regular_path(directory) != directory
                or any(directory.iterdir()) or environment.get('SSL_CERT_FILE') != str(bundle)
                or environment.get('SSL_CERT_DIR') != str(directory)):
            raise ValueError()
    except (OSError, ValueError):
        raise DependencyError('go-proxy-public-trust-mutated') from None
    return identity(name, raw)


def validate(project, value):
    if value is None:
        return
    if (not isinstance(value, dict) or set(value) != {'profile', 'caFile', 'digest', 'size'}
            or value['profile'] != PROFILE or type(value['size']) is not int):
        raise DependencyError('go-proxy-public-trust-identity-invalid')
    name = selection({'tlsTrust': {'caFile': value['caFile']}})
    if value != identity(name, source(project, name)):
        raise DependencyError('go-proxy-public-trust-input-drift')
