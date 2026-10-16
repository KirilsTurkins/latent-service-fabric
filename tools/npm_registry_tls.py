"""Explicit public TLS roots for native npm fetch; never ambient trust or keys."""
from __future__ import annotations

from pathlib import Path
import ssl

from tools.application_dependency_store import DependencyError, path_name, read_bytes, regular_path
from tools.build_observation import file_identity
from tools.build_snapshot import digest

MAX_CERTIFICATE = 65536
MAX_CERTIFICATES = 16


def names(registries: dict) -> tuple[str, ...]:
    selected = set()
    for row in registries['registries']:
        if not isinstance(row, dict):
            raise DependencyError('npm-registry-configuration-invalid')
        if 'tlsTrust' not in row:
            continue
        value = row['tlsTrust']
        if not isinstance(value, dict) or set(value) != {'caFile'}:
            raise DependencyError('npm-registry-trust-declaration-invalid')
        name = value['caFile']
        if not isinstance(name, str):
            raise DependencyError('npm-registry-certificate-path-invalid')
        path_name(name)
        if (name.split('/')[0] in {'target', '.git', 'dependency-inputs', 'vendor', 'node_modules'}
                or name in {'sdk-lock.json', 'package.json', 'package-lock.json', 'npm-resolved.lock.json',
                            'latent.dependencies.json', 'latent.dependencies.lock.json', 'capsule-project.json'}):
            raise DependencyError('npm-registry-certificate-path-invalid')
        selected.add(name)
    if len(selected) > MAX_CERTIFICATES:
        raise DependencyError('npm-registry-certificate-count-limit')
    return tuple(sorted(selected))


def public_certificate(raw: bytes) -> None:
    value = raw.strip()
    if (not value.startswith(b'-----BEGIN CERTIFICATE-----')
            or not value.endswith(b'-----END CERTIFICATE-----')
            or value.count(b'-----BEGIN CERTIFICATE-----') != 1
            or value.count(b'-----END CERTIFICATE-----') != 1
            or b'PRIVATE KEY' in value):
        raise DependencyError('npm-registry-public-certificate-required')
    try:
        # Parse X.509 with the platform TLS library; no peer connection or
        # default trust loading is involved in this bounded syntax validation.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=value.decode('ascii'))
    except (ValueError, UnicodeError, ssl.SSLError):
        raise DependencyError('npm-registry-public-certificate-invalid') from None


class Trust:
    def __init__(self, project: Path, registries: dict, work: Path):
        self.project = project
        self.sources = {name: read_bytes(regular_path(project / name), MAX_CERTIFICATE)
            for name in names(registries)}
        for raw in self.sources.values():
            public_certificate(raw)
        self.bundle = None
        self.identity = None
        self.recipe = file_identity(Path(__file__), 'npm-registry-tls-recipe')
        if self.sources:
            self.raw = b''.join(raw.strip() + b'\n' for raw in self.sources.values())
            self.bundle = work / 'selected-public-registry-roots.pem'
            with self.bundle.open('xb') as target:
                target.write(self.raw)
            self.bundle.chmod(0o600)
            self.identity = {'profile': 'npm-explicit-public-registry-roots-v1',
                'recipe': self.recipe, 'defaultRoots': 'pinned-native-node-builtin',
                'additionalBundleDigest': digest(self.raw), 'additionalBundleBytes': len(self.raw),
                'certificates': [{'path': name, 'digest': digest(raw), 'size': len(raw)}
                    for name, raw in self.sources.items()]}

    def inject(self, environment: dict) -> None:
        if self.bundle is not None:
            # This value is derived solely from the explicit reviewed public
            # inputs. build_environment never inherits NODE_EXTRA_CA_CERTS.
            # Node retains its pinned builtin roots and adds this owned bundle.
            environment['NODE_EXTRA_CA_CERTS'] = str(self.bundle)

    def check_unchanged(self) -> None:
        if (file_identity(Path(__file__), 'npm-registry-tls-recipe') != self.recipe
                or any(read_bytes(regular_path(self.project / name), MAX_CERTIFICATE) != raw
                    for name, raw in self.sources.items())
                or self.bundle is not None and read_bytes(self.bundle, MAX_CERTIFICATE * MAX_CERTIFICATES) != self.raw):
            raise DependencyError('npm-registry-trust-input-mutated')
