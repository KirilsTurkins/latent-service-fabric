"""Explicit public CA inputs for one owned Linux npm resolver child."""
import re
import ssl
import sys

from tools.application_dependency_store import DependencyError, path_name, read_bytes, regular_path
from tools.build_snapshot import digest

PROFILE = 'npm-linux-explicit-registry-ca-v1'
MAX_BYTES = 512 * 1024
MAX_CERTIFICATES = 256
PEM = re.compile(rb'(?:-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----[ \t\r\n]*)+')


def selection(policy):
    if 'tlsTrust' not in policy:
        return None
    value = policy['tlsTrust']
    if not isinstance(value, dict) or set(value) != {'caFile'}:
        raise DependencyError('npm-registry-public-trust-declaration-invalid')
    name = path_name(value['caFile'])
    if name.split('/')[0] in {'vendor', 'target', 'dependency-inputs', 'application-vendor', 'dependencies', '.git'}:
        raise DependencyError('npm-registry-public-trust-path-invalid')
    return name


def public_bundle(raw):
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES
            or not PEM.fullmatch(raw.strip())
            or not 1 <= raw.count(b'-----BEGIN CERTIFICATE-----') <= MAX_CERTIFICATES):
        raise DependencyError('npm-registry-public-ca-bundle-required')
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=raw.decode('ascii'))
    except (UnicodeError, ValueError, ssl.SSLError):
        raise DependencyError('npm-registry-public-ca-bundle-required') from None
    return raw


def source(project, name):
    try:
        path = regular_path(project / name)
        if not path.resolve(strict=True).is_relative_to(project.resolve(strict=True)) or path.stat().st_nlink != 1:
            raise ValueError()
        return public_bundle(read_bytes(path, MAX_BYTES))
    except (OSError, ValueError):
        raise DependencyError('npm-registry-public-ca-unavailable-or-changed') from None


def identity(name, raw):
    return {'profile': PROFILE, 'caFile': name, 'digest': digest(raw), 'size': len(raw)}


def prepare(project, owned, policy, environment):
    name = selection(policy)
    if name is None:
        return None
    if sys.platform != 'linux':
        raise DependencyError('npm-registry-explicit-ca-requires-linux')
    raw = source(project, name)
    owned = regular_path(owned).resolve(strict=True)
    root = owned / 'npm-registry-trust'
    root.mkdir(mode=0o700)
    bundle = root / 'public-ca.pem'
    with bundle.open('xb') as output:
        output.write(raw)
    bundle.chmod(0o600)
    environment.update(NPM_CONFIG_CAFILE=str(bundle), NPM_CONFIG_STRICT_SSL='true')
    return check(project, owned, policy, environment)


def check(project, owned, policy, environment):
    name = selection(policy)
    if name is None:
        return None
    raw = source(project, name)
    root = regular_path(owned / 'npm-registry-trust')
    bundle = root / 'public-ca.pem'
    try:
        if (read_bytes(bundle, MAX_BYTES) != raw or bundle.stat().st_nlink != 1
                or environment.get('NPM_CONFIG_CAFILE') != str(bundle)
                or environment.get('NPM_CONFIG_STRICT_SSL') != 'true'):
            raise ValueError()
    except (OSError, ValueError):
        raise DependencyError('npm-registry-public-trust-mutated') from None
    return identity(name, raw)


def validate(project, value):
    if value is None:
        return
    if (not isinstance(value, dict) or set(value) != {'profile', 'caFile', 'digest', 'size'}
            or value['profile'] != PROFILE or type(value['size']) is not int):
        raise DependencyError('npm-registry-public-trust-identity-invalid')
    name = selection({'tlsTrust': {'caFile': value['caFile']}})
    if value != identity(name, source(project, name)):
        raise DependencyError('npm-registry-public-trust-input-drift')
