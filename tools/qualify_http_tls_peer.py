"""Bounded Linux transport-reference lane; no SDK/native-provider qualification."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.http_tls_peer_reference import CASES, exercise
from tools.owned_test_process import run_owned
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, write_json

MATERIALS = ('tools/qualify_http_tls_peer.py', 'tools/http_tls_peer_reference.py',
    'tools/standard_http/tls_peer.py', 'tools/standard_http/peer.py',
    'tools/standard_http/protocol.py', 'tools/standard_http/vectors.py',
    'tools/standard_http/observations.py', 'tools/owned_test_process.py',
    '.github/workflows/http-tls-fixture.yml')

CONFIGURATION = '''[req]
prompt = no
distinguished_name = subject
x509_extensions = extensions
[subject]
CN = controlled-loopback-fixture
[extensions]
subjectAltName = IP:127.0.0.1
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = serverAuth
'''


def qualify(output):
    require(sys.platform == 'linux', 'tls-reference-linux-process-owner-required')
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'tls-reference-separated-output')
    output = fresh(output)
    started = time.monotonic()
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip()
    materials = {name:file_identity(ROOT/name) for name in MATERIALS}
    record = {'schemaVersion':'latent.http.tls-peer-reference.v1', 'status':'incomplete',
        'source':source, 'materials':materials, 'signedGuestExecuted':False,
        'providerAccountingQualified':False, 'kernelAccountingQualified':False,
        'privateKeyRetained':False, 'openssl':ssl.OPENSSL_VERSION}
    stage = 'disposable-certificate'
    try:
        openssl = Path(shutil.which('openssl') or 'missing-openssl').resolve(strict=True)
        original_tool = file_identity(openssl)
        record['certificateTool'] = original_tool
        with tempfile.TemporaryDirectory(prefix='lsf-http-tls-private-') as temporary:
            private = Path(temporary)
            configuration = private/'openssl.cnf'
            configuration.write_text(CONFIGURATION, encoding='ascii', newline='\n')
            certificate, key = private/'certificate.pem', private/'private.pem'
            generated = run_owned([str(openssl), 'req', '-newkey', 'ec', '-pkeyopt',
                'ec_paramgen_curve:prime256v1', '-nodes', '-x509', '-sha256', '-days', '1',
                '-config', str(configuration), '-keyout', str(key), '-out', str(certificate)],
                cwd=private, timeout=15, maximum=65536)
            require(generated.returncode == 0 and generated.cleaned, 'tls-reference-certificate-generation')
            der = ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding='ascii'))
            (output/'certificate.der').write_bytes(der)
            record['publicCertificate'] = file_identity(output/'certificate.der')
            stage = 'six-real-tls-protocol-controls'
            record['cases'] = exercise(certificate, key)
            require([row['case'] for row in record['cases']] == list(CASES), 'tls-reference-six-cases')
        require(time.monotonic()-started <= 60 and file_identity(openssl) == original_tool
                and materials == {name:file_identity(ROOT/name) for name in MATERIALS}
                and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == source,
                'tls-reference-final-tool-source-and-time')
        record.update(status='passed', seconds=time.monotonic()-started)
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(qualify(parser.parse_args().output)['status'])
