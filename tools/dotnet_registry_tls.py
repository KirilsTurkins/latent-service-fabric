"""Explicit public NuGet CA inputs for an owned Linux restore child only."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import ssl
import sys

from tools.application_dependency_store import DependencyError, path_name, read_bytes, regular_path
from tools.build_snapshot import digest

PROFILE = 'nuget-linux-explicit-ca-bundle-v1'
MAX_BUNDLE = 512 * 1024
MAX_CERTIFICATES = 256
CERTIFICATES = re.compile(rb'(?:-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----[ \t\r\n]*)+')


def selection(policy: dict | None) -> str | None:
    if not isinstance(policy, dict) or 'tlsTrust' not in policy:
        return None
    value = policy['tlsTrust']
    if not isinstance(value, dict) or set(value) != {'caFile'} or not isinstance(value['caFile'], str):
        raise DependencyError('nuget-feed-trust-declaration-invalid')
    name = path_name(value['caFile'])
    if name.split('/')[0] in {'vendor', 'target', 'obj', 'bin', '.git', 'dependency-inputs', 'dependencies', 'application-vendor'}:
        raise DependencyError('nuget-feed-trust-path-invalid')
    return name


def public_bundle(raw: bytes) -> bytes:
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE
            or not CERTIFICATES.fullmatch(raw.strip())
            or not 1 <= raw.count(b'-----BEGIN CERTIFICATE-----') <= MAX_CERTIFICATES):
        raise DependencyError('nuget-feed-public-ca-bundle-required')
    try:
        # Parse only public X509 certificates; no key/password or verification
        # bypass exists. This context never connects or changes machine trust.
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=raw.decode('ascii'))
    except (UnicodeError, ValueError, ssl.SSLError):
        raise DependencyError('nuget-feed-public-ca-bundle-required') from None
    return raw


def source(project: Path, files: dict[str, bytes], name: str) -> bytes:
    try:
        path = regular_path(project / name)
        if (not path.resolve(strict=True).is_relative_to(project.resolve(strict=True))
                or path.stat().st_nlink != 1):
            raise ValueError()
        raw = public_bundle(read_bytes(path, MAX_BUNDLE))
        if files.get(name) != raw:
            raise ValueError()
    except (OSError, ValueError, KeyError):
        raise DependencyError('nuget-feed-certificate-unavailable-or-changed') from None
    return raw


def validate(files: dict[str, bytes], value: dict | None) -> None:
    if value is None:
        return
    if (not isinstance(value, dict) or set(value) != {'profile', 'caFile', 'digest', 'size'}
            or value['profile'] != PROFILE or type(value['size']) is not int):
        raise DependencyError('nuget-feed-trust-identity-invalid')
    name = selection({'tlsTrust': {'caFile': value['caFile']}})
    raw = files.get(name)
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE
            or value != {'profile': PROFILE, 'caFile': name, 'digest': digest(raw), 'size': len(raw)}):
        raise DependencyError('nuget-feed-trust-input-drift')
    public_bundle(raw)


@dataclass(frozen=True)
class Trust:
    project: Path
    files: dict[str, bytes]
    name: str
    original: bytes
    bundle: Path
    directory: Path
    environment: dict[str, str]

    @property
    def identity(self):
        return {'profile': PROFILE, 'caFile': self.name, 'digest': digest(self.original), 'size': len(self.original)}

    def check(self):
        try:
            if (source(self.project, self.files, self.name) != self.original
                    or read_bytes(regular_path(self.bundle), MAX_BUNDLE) != self.original
                    or self.bundle.stat().st_nlink != 1 or not self.directory.is_dir()
                    or self.directory.is_symlink() or any(self.directory.iterdir())
                    or self.environment.get('SSL_CERT_FILE') != str(self.bundle)
                    or self.environment.get('SSL_CERT_DIR') != str(self.directory)):
                raise ValueError()
        except (OSError, ValueError):
            raise DependencyError('nuget-feed-trust-mutated') from None


def prepare(project: Path, files: dict[str, bytes], policy: dict | None,
            owned: Path, environment: dict[str, str]) -> Trust | None:
    name = selection(policy)
    if name is None:
        return None  # Default restore retains byte-compatible environment/policy.
    if sys.platform != 'linux':
        raise DependencyError('nuget-explicit-ca-profile-requires-linux')
    raw = source(project, files, name)
    root = owned / 'nuget-feed-trust'
    root.mkdir(mode=0o700)
    bundle, directory = root / 'public-ca-bundle.pem', root / 'empty-certificates'
    directory.mkdir(mode=0o700)
    with bundle.open('xb') as output:
        output.write(raw)
    bundle.chmod(0o600)
    # An existing empty directory prevents an implicit default-directory
    # fallback. The complete selected public bundle must include required roots.
    environment.update(SSL_CERT_FILE=str(bundle), SSL_CERT_DIR=str(directory))
    result = Trust(project, files, name, raw, bundle, directory, environment)
    result.check()
    return result
