"""Prepare exactly the reviewed PR 1657 continuation; never move a branch."""
from pathlib import Path
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

BASE = '46156d8dd5f6f2954b175108ce8d2d1a96d11c00'
BASE_TREE = '29b8504f71ce7c0a49b2f3b92d4834e9b8f408cb'
STAGE = Path(__file__).resolve().parent
CLIENT = 'crates/latent-capabilities/src/broker/pools/client.rs'
ADMISSION = 'crates/latent-capabilities/src/broker/pools/client/admission.rs'
HTTP_TESTS = 'crates/latent-capabilities/src/broker/pools/client/admission/http_tests.rs'
NETWORK = 'crates/latent-http/src/network.rs'
DOC = 'docs/testing/rust-combined-http-diagnostic.md'
NODE = 'tools/rust_thread_http_combined_node.py'
TESTS = 'tools/tests/test_rust_thread_http_combined_node.py'
ORIGINAL = {
    CLIENT: '40583e5c6553c7a2b4147137fa2afc875c8cdfe4',
    ADMISSION: '2c9536cb2bad8ebcab48a863ef40091da7919559',
    NETWORK: '8e9b7ba5f7e746192d8d129a529c45c5c2b372d2',
    DOC: '6489dc99b3aaad40ea3d865eb953c5e2709ff7b9',
    NODE: 'c8cd85bbbfa89923fa47c6adc25d44df80ed97fe',
    TESTS: 'c08b68ec379f48a84cfbc04bc0feebf2ece9196b',
}
PATHS = sorted([*ORIGINAL, HTTP_TESTS])


def git(*args):
    return subprocess.check_output(['git', *args], text=True, timeout=30).strip()


def replace(path, before, after, count=1):
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if text.count(before) != count:
        raise ValueError('unexpected replacement count: ' + path)
    p.write_text(text.replace(before, after), encoding='utf-8')


def apply():
    assert git('rev-parse', 'HEAD') == BASE
    assert not git('status', '--porcelain')
    for path, sha in ORIGINAL.items():
        assert git('hash-object', path) == sha, path
    assert not Path(HTTP_TESTS).exists()
    replace(CLIENT, '''        if backoff.dialing {
            let error = busy();
            super::super::http::refusal::observe(
                super::super::http::refusal::Stage::PoolActiveDial,
                &error,
            );
            return Err(error.into());
        }
''', '''        if backoff.dialing {
            // Distinguish an in-progress setup from real capacity exhaustion.
            // Existing immediate callers still observe/refuse this condition;
            // the HTTP-specific waiter can await setup without retrying I/O.
            return Err(ClientAccessError::ActiveDial);
        }
''')
    replace(ADMISSION, '//! Wait only for bookkeeping access, before any socket or dial is allocated.',
        '//! Pre-dial waits retain the accepted request and allocate no socket.\n//! Ordinary callers wait only for bookkeeping. HTTP may additionally serialize\n//! behind an already admitted dial, never behind response headers or backoff.')
    replace(ADMISSION, '#[cfg(all(test, target_os = "linux"))]\nmod tests;',
        '#[cfg(all(test, target_os = "linux"))]\nmod http_tests;\n#[cfg(all(test, target_os = "linux"))]\nmod tests;')
    replace(ADMISSION, '    Contended,\n    Failed(PlatformError),',
        '    Contended,\n    ActiveDial,\n    Failed(PlatformError),')
    replace(ADMISSION, '            Self::Contended => super::busy(),', '''            Self::Contended => super::busy(),
            Self::ActiveDial => {
                let error = super::busy();
                crate::broker::http::refusal::observe(
                    crate::broker::http::refusal::Stage::PoolActiveDial,
                    &error,
                );
                error
            }''')
    replace(ADMISSION, '                Err(ClientAccessError::Failed(error)) => return Err(error),', '''                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::ActiveDial) => {
                    return Err(ClientAccessError::ActiveDial.immediate());
                }''', count=4)
    replace(ADMISSION, '    /// Reserve exactly once after bookkeeping becomes accessible.', '''    /// HTTP connection setup may serialize behind this client's one admitted
    /// dial. The current request already owns bounded running-request capacity;
    /// waiting creates no task, socket, connection charge, or fresh deadline.
    ///
    /// A successful dial releases its setup slot before response headers are
    /// awaited. Thus a held response cannot prevent this caller's first dial.
    /// Capacity, backoff, poisoned bookkeeping, cancellation and revoked
    /// authority still fail closed. No attempted protocol operation is retried.
    pub async fn reserve_http_connection_wait(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        loop {
            call.check_client(&self.core)?;
            match self.reserve_owned(Some(call.io.lease()), None, None) {
                Ok(value) => return Ok(value),
                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::Contended | ClientAccessError::ActiveDial) => {
                    // This is only unacquired pre-dial admission. Keep the
                    // same paid future, authority fence and absolute deadline.
                    call.io
                        .wait_for(tokio::time::sleep(Duration::from_millis(1)))
                        .await?;
                }
            }
        }
    }

    /// Reserve exactly once after bookkeeping becomes accessible.''')
    Path(HTTP_TESTS).write_bytes((STAGE / 'http-tests.rs').read_bytes())
    replace(NETWORK, '            client.reserve_connection_wait(call).await?', '''            // Only pre-dial setup is serialized. Once the other connection
            // exists, its pending headers/body do not own the setup slot.
            client.reserve_http_connection_wait(call).await?''')
    replace(NODE, "NATIVE = 'latent:runtime-native/threads@0.1.0'\n", "NATIVE = 'latent:runtime-native/threads@0.1.0'\n" + '''# This fixed two-pool programme is not the single-client HTTP fixture. Its
# eight retained PAL/stack owners leave no room for real HTTP completion
# fibers. Provision those two additional owners explicitly, not by refunding
# live stacks or bypassing the original activation memory ledger.
COMBINED_NATIVE_OWNERS = 10
''')
    replace(NODE, "    activation['nativeThreads'] = True\n", "    activation['nativeThreads'] = True\n    activation['limits'] = {**http.RUNTIME_LIMITS, 'nativeOwners': COMBINED_NATIVE_OWNERS}\n")
    replace(NODE, "            record['configurationIdentity'] = file_identity(config)\n", "            record['configurationIdentity'] = file_identity(config)\n            record['runtimeLimits'] = read_json(config)['providers']['activationRuntime']['limits']\n")
    replace(DOC, '''engine-owned HTTP completion fibers. Both draw from the original eight-Native-owner
ceiling and the same 16 MiB activation ledger. Child admission still requires its
separate native grant and a distinct original Task; accepted child-start capacity
is not recycled on logical completion. Every actual mapping and its metadata
remain charged until physical drop, and cached child permits remain charged
until Store destruction. Other native-thread profiles keep refusing unadmitted
stack creation; a configuration name or package inspection cannot select this
combined path without the immutable final-graph proof.
''', '''engine-owned HTTP completion fibers. The combined controller explicitly sets
`nativeOwners` to ten: eight retained PAL/stack owners and capacity for two
concurrent HTTP completion fibers. This is a change to this diagnostic's host
capacity, not a successful qualification under the earlier eight-owner ceiling.
The ordinary HTTP fixture remains at eight; no ordinary default is changed.
The witness records the selected runtime limits alongside the configuration
identity. A complete signed run is still required to establish that this
provisioning suffices; it is not a general or certified minimum-owner bound.

All actual owners still share the same runtime Native ceiling and 16 MiB
activation ledger. Child admission still requires its separate native grant
and a distinct original Task; accepted child-start capacity is not recycled
on logical completion. Every actual mapping and its metadata remain charged
until physical drop, and cached child permits remain charged until Store
destruction. Other native-thread profiles keep refusing unadmitted stack
creation; a configuration name or package inspection cannot select this
combined path without the immutable final-graph proof.

HTTP invocation connection setup may wait behind the same client's one active
dial. This waits before allocating a socket or attempting protocol work, using
the already accepted request's original deadline, cancellation, authority, and
running-request ownership. The dial slot releases after setup, not after the
first response, so withheld response headers do not serialize independent
requests. Capacity exhaustion, backoff, poisoned ownership, and revocation still
refuse; an attempted dial or HTTP request is never replayed. Other callers of
the ordinary connection-admission API retain their immediate active-dial
refusal. The regression controls live in
`crates/latent-capabilities/src/broker/pools/client/admission/http_tests.rs`.
''')
    # Keep the new capacity controls in the module already selected by both
    # the focused witness and repository discovery, rather than an orphan test.
    replace(TESTS, 'from types import SimpleNamespace\n', 'from copy import deepcopy\nimport json\nfrom pathlib import Path\nimport tempfile\nfrom types import SimpleNamespace\n')
    capacity = (STAGE / 'capacity-tests.py').read_text(encoding='utf-8')
    capacity = capacity[capacity.index('class CombinedCapacityControls'):capacity.index("if __name__ == '__main__':")].rstrip()
    replace(TESTS, "if __name__ == '__main__':", capacity + "\n\n\nif __name__ == '__main__':")
    # Exact candidate identities before formatting; these are independently
    # retained in the preceding continuation's patch, not observed approvals.
    expected = {CLIENT: '2088d6ebf0b06ee388b65ba1c86d665a0eb4d438',
                ADMISSION: '44661511d98293ea2caa4e2503542506bf814a49',
                NETWORK: '59370262ffff1014b23e8a2490ed622cc2e9c692',
                DOC: 'b7cf981da1d35a8cfeab0d15c7c2e7aaa708c54b',
                NODE: 'a97e284b9d1a8cb99a36ab25b33e5ef252cf8d06',
                HTTP_TESTS: 'c9aa746824bf97c0dad7d09d1bb392975ebfa5f9'}
    for path, sha in expected.items():
        assert git('hash-object', path) == sha, path
    (STAGE / 'paths.json').write_text(json.dumps(PATHS), encoding='utf-8')


def publish():
    assert git('rev-parse', 'HEAD') == BASE
    subprocess.run(['git', 'add', '--', *PATHS], check=True)
    assert git('diff', '--cached', '--name-only').splitlines() == PATHS
    assert not git('diff', '--name-only')
    expected_tree = git('write-tree')
    def post(kind, value):
        request = urllib.request.Request(
            'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/' + kind,
            data=json.dumps(value).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                     'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)['sha']
    entries = []
    for path in PATHS:
        data = Path(path).read_bytes()
        sha = post('blobs', {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
        assert sha == git('hash-object', path)
        entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha})
    # Always retain blob ids even if the hosted token cannot create a tree.
    record = {'parent': BASE, 'baseTree': BASE_TREE, 'expectedTree': expected_tree, 'entries': entries}
    (STAGE / 'candidate.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print('CANDIDATE_BLOBS ' + json.dumps(record), flush=True)
    tree = post('trees', {'base_tree': BASE_TREE, 'tree': entries})
    assert tree == expected_tree
    sha = post('commits', {'message': 'Fix combined HTTP witness capacity and serialize only pre-dial setup',
                           'tree': tree, 'parents': [BASE]})
    record.update(commit=sha, tree=tree)
    (STAGE / 'candidate.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print('CANDIDATE_COMMIT ' + json.dumps(record), flush=True)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write('sha=' + sha + '\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['apply']:
        apply()
    elif sys.argv[1:] == ['publish']:
        publish()
    else:
        raise SystemExit('expected apply or publish')
