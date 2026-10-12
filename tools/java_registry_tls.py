"""Explicit private-feed TLS inputs confined to the Java resolution stage."""
from __future__ import annotations

import os
from pathlib import Path
import re
import time

from tools.application_dependency_store import DependencyError, path_name, read_bytes, regular_path
from tools.build_process import BuildProcessError, run_bounded_result
from tools.build_snapshot import digest

MAX_CERTIFICATE = 65536
MAX_TRUST_STORE = 4 * 1024 * 1024
MAX_CERTIFICATES = 62  # The declaration and native graph retain two lock slots.
TRUST_PREPARATION_SECONDS = 30


def certificate_name(value: object) -> str:
    if not isinstance(value, str):
        raise DependencyError('java-registry-certificate-path-invalid')
    path_name(value)
    if (value.split('/')[0] in {'target', '.git', 'dependency-inputs'}
            or value in {'sdk-lock.json', 'java-dependencies.json', 'java-resolved.lock.json',
                         'application-dependencies.json', 'application-dependencies.lock.json'}):
        raise DependencyError('java-registry-certificate-path-invalid')
    return value


def certificates(config: dict) -> tuple[str, ...]:
    selected = set()
    for repository in config['repositories']:
        if 'tlsTrust' not in repository:
            continue
        value = repository['tlsTrust']
        if not isinstance(value, dict) or set(value) != {'caFile'}:
            raise DependencyError('java-registry-trust-declaration-invalid')
        selected.add(certificate_name(value['caFile']))
    if len(selected) > MAX_CERTIFICATES:
        raise DependencyError('java-registry-certificate-count-limit')
    return tuple(sorted(selected))


def credentials(config: dict, environment: dict) -> None:
    """Copy only complete, bounded credential pairs for declared repositories."""
    selected = {}
    for repository in config['repositories']:
        prefix = 'LSF_REGISTRY_' + repository['id'].upper().replace('-', '_')
        username, password = (os.environ.get(prefix + suffix) for suffix in ('_USERNAME', '_PASSWORD'))
        if username is None and password is None:
            continue
        if (username is None or password is None or not 1 <= len(username) <= 1024
                or not 1 <= len(password) <= 16384 or re.search(r'[\x00-\x1f\x7f]', username + password)):
            raise DependencyError('java-registry-credential-pair-invalid')
        selected.update({prefix + '_USERNAME': username, prefix + '_PASSWORD': password})
    environment.update(selected)


def prepare(project: Path, config: dict, work: Path, java: Path, environment: dict):
    """Derive an owned truststore; never change JDK or machine trust settings.

    Returned public certificate bytes become native lock inputs. The private
    derived store and SDK tool inputs are checked again before capture commits.
    Credentials are not given to keytool and never enter these identities.
    """
    names = certificates(config)
    if not names:
        return (), {}, {}, None
    source = {}
    for name in names:
        raw = read_bytes(regular_path(project / name), MAX_CERTIFICATE)
        text = raw.strip()
        if (not text.startswith(b'-----BEGIN CERTIFICATE-----')
                or not text.endswith(b'-----END CERTIFICATE-----')
                or text.count(b'-----BEGIN CERTIFICATE-----') != 1
                or text.count(b'-----END CERTIFICATE-----') != 1
                or b'PRIVATE KEY' in text):
            raise DependencyError('java-registry-public-certificate-required')
        source[name] = raw
    java = regular_path(java)
    jdk = java.parent.parent
    keytool = jdk / 'bin' / ('keytool.exe' if java.suffix.lower() == '.exe' else 'keytool')
    system_store = jdk / 'lib/security/cacerts'
    original = read_bytes(system_store, MAX_TRUST_STORE)
    tools = {str(keytool): digest(read_bytes(keytool)), str(system_store): digest(original)}
    if environment.get('JAVA_HOME'):
        selected_java = Path(environment['JAVA_HOME']) / 'bin' / java.name
        if digest(read_bytes(selected_java)) != digest(read_bytes(java)):
            raise DependencyError('java-registry-resolution-jdk-home-mismatch')
    trust = work / 'private-registry-cacerts'
    with trust.open('xb') as target:
        target.write(original)
    trust.chmod(0o600)
    deadline = time.monotonic() + TRUST_PREPARATION_SECONDS
    key_environment = {name: value for name, value in environment.items() if not name.startswith('LSF_REGISTRY_')}
    for ordinal, (name, raw) in enumerate(source.items()):
        certificate = work / f'public-registry-ca-{ordinal:04d}.pem'
        with certificate.open('xb') as target:
            target.write(raw)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DependencyError('java-registry-trust-preparation-deadline')
        try:
            result = run_bounded_result([str(keytool), '-importcert', '-noprompt', '-trustcacerts',
                '-alias', f'lsf-captured-registry-{ordinal:04d}', '-keystore', str(trust),
                '-storepass', 'changeit', '-file', str(certificate)], work, key_environment, remaining, 16384)
        except BuildProcessError as error:
            raise DependencyError('java-registry-trust-preparation-failed-private-diagnostics-discarded') from error
        if result.returncode or time.monotonic() >= deadline:
            raise DependencyError('java-registry-trust-preparation-failed-private-diagnostics-discarded')
        if certificate.read_bytes() != raw:
            raise DependencyError('java-registry-certificate-mutated')
    derived = read_bytes(trust, MAX_TRUST_STORE + MAX_CERTIFICATES * MAX_CERTIFICATE)
    inputs = {str(trust): digest(derived)}
    identity = {'profile': 'java-captured-registry-trust-v1',
        'keytoolExecutableDigest': tools[str(keytool)], 'defaultTrustStoreDigest': tools[str(system_store)],
        'derivedTrustStoreDigest': digest(derived), 'derivedTrustStoreSize': len(derived),
        'certificates': [{'path': name, 'digest': digest(raw), 'size': len(raw)} for name, raw in source.items()],
        'preparationMaximumSeconds': TRUST_PREPARATION_SECONDS}
    # This password protects only the owned public-certificate store. It is the
    # JDK's fixed public default, not a repository credential or signing key.
    arguments = ('-Djavax.net.ssl.trustStore=' + str(trust), '-Djavax.net.ssl.trustStorePassword=changeit')
    return arguments, source, {**tools, **inputs}, identity
