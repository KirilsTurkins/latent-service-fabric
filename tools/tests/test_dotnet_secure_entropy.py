"""Pinned PAL behavior, finite scalar lowering and explicit entropy authority."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.dotnet_guest import entropy
from tools.dotnet_guest.runtime import CLOCK, RANDOM
from tools import dotnet_standard_entropy_fixture as fixture, dotnet_standard_entropy_probe as probe
from tools.rust_capsule_project import ROOT


class SecureEntropyPort(unittest.TestCase):
    def test_descriptor_binds_both_exact_pinned_entrypoints_and_public_scalar_abi(self):
        source = ROOT / 'sdk/dotnet-guest/tools/native-entropy'
        self.assertEqual(json.loads((source / 'upstream.json').read_bytes()), entropy.UPSTREAM)
        self.assertEqual(entropy.PROFILE, 'dotnet-native-entropy-v2')
        self.assertEqual(entropy.UPSTREAM['secureAbi'], {
            'returnSuccess': 0, 'returnFailure': -1, 'maximumLength': 65536,
            'interface': 'latent:random/random@0.1.0', 'operation': 'u64-value',
            'resultBytes': 16, 'payloadOffset': 8})
        self.assertEqual(entropy.WRAPS, {entropy.WRAP, entropy.SECURE_WRAP})
        self.assertEqual(entropy.UPSTREAM['revision'], '8449ba666dd991e495d8363d9852f18eb86a1aa1')

    def test_closed_wasi_secure_random_denial_is_preserved(self):
        source = (ROOT / 'sdk/dotnet-guest/runtime/closed_support.rs').read_text()
        self.assertIn('WASI entropy is unsupported; import latent:random/random explicitly', source)
        native = (ROOT / 'sdk/dotnet-guest/tools/native-entropy/entropy.c').read_text()
        self.assertIn('import_module("latent:random/random@0.1.0")', native)
        self.assertNotIn('random_random_get_random_bytes', native)
        self.assertNotIn('random_insecure_get_insecure_random_u64', native)

    def test_existing_bytes_policy_must_produce_a_typed_denial_before_secure_grant(self):
        from tools.phase2_operator_process import WorkflowError
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=Mock())
            target = {'service': 'examples/my-greeting', 'generation': 3, 'grants': [
                {'capability': CLOCK, 'policy': 'clock'}, {'capability': RANDOM, 'policy': 'hash-seed'}]}
            node = SimpleNamespace(startup_record={'providers': [{
                'id': probe.noncrypto.PROVIDER, 'profile': probe.noncrypto.PROFILE,
                'configurationDigest': 'sha256:' + 'a' * 64}]})
            denied = {'processReaped': True, 'response': {'data': {'consumption': {'effectCount': 0}}}}
            original_binding = {'tenant': 'examples', 'id': probe.noncrypto.BINDING,
                'recordKind': 'provider-binding', 'revoked': False, 'generation': '17',
                'document': {'formatVersion': 1, 'tenant': 'examples', 'capability': RANDOM,
                    'providerProfile': probe.noncrypto.PROFILE, 'configurationDigest': 'sha256:' + 'a' * 64,
                    'configurationEpoch': 1, 'restriction': {'operations': ['bytes']}}}
            client.call.return_value = {'outcomeKnown': True, 'category': 'success',
                                        'data': {'policy': original_binding}}
            result = {'invocations': [], 'providerIdle': []}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.assert_value') as assertion, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}), \
                    patch('tools.rust_capsule_node.deploy', return_value=target) as deploy:
                targets = {'greeting': target}
                probe.grant(client, node, Path(temporary), targets, {'greeting': 'publication:exact'}, result)
                assertion.assert_called_once_with(client, denied, [{'ok': fixture.expected('denied')}])
                self.assertEqual(client.call.call_count, 3)
                mutation = client.call.call_args_list[1].args
                self.assertEqual(mutation[-2:], ('--expected-generation', '17'))
                self.assertEqual(result['dotnetStandardEntropyAuthority']['originalBinding'], original_binding)
                selected = deploy.call_args.kwargs['grants']
                self.assertEqual(selected, [{'capability': CLOCK, 'policy': 'clock'},
                    {'capability': RANDOM, 'policy': 'secure-entropy-allow'}])
                policy = result['dotnetStandardEntropyAuthority']['policy']['rules'][0]
                self.assertEqual(policy['operations'], ['bytes', 'u64-value'])
                self.assertEqual(policy['ceiling'], {'operations': 4096, 'inputBytes': 8,
                    'outputBytes': 32768, 'wallTimeMillis': 5000})
                self.assertEqual(policy['publications'], ['publication:exact'])
            client.call.reset_mock()
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.assert_value', side_effect=WorkflowError('wrong ordinary result')), \
                    patch('tools.rust_capsule_node.deploy') as deploy:
                with self.assertRaisesRegex(WorkflowError, 'wrong ordinary result'):
                    probe.grant(client, node, Path(temporary), {'greeting': target},
                                {'greeting': 'publication:exact'}, {'invocations': [], 'providerIdle': []})
                client.call.assert_not_called()
                deploy.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'actual C reference requires the Linux toolchain')
    def test_actual_native_reference_checks_lengths_bytes_errors_clear_and_separate_noncrypto(self):
        compiler = shutil.which('cc')
        if compiler is None:
            self.fail('Linux owning qualification requires the native C reference compiler')
        source = ROOT / 'sdk/dotnet-guest/tools/native-entropy/entropy.c'
        with tempfile.TemporaryDirectory(prefix='lsf-secure-entropy-reference-') as temporary:
            root = Path(temporary)
            (root / 'wasi').mkdir()
            (root / 'wasi/wasip2.h').write_text('''#include <stddef.h>
#include <stdint.h>
typedef struct { uint8_t *ptr; size_t len; } wasip2_list_u8_t;
void random_insecure_get_insecure_random_bytes(uint64_t, wasip2_list_u8_t *);
void wasip2_list_u8_free(wasip2_list_u8_t *);
''')
            harness = root / 'reference.c'
            harness.write_text('''#include <assert.h>
#include <stdlib.h>
#include "entropy.c"
static unsigned calls, fail_at, failures, insecure_calls, freed;
void lsf_random_u64(lsf_random_u64_result *out) {
    assert(((uintptr_t)out & 7) == 0);
    ++calls;
    out->tag = calls == fail_at ? 1 : 0;
    out->value = out->tag ? failures : UINT64_C(0x0807060504030201);
}
void random_insecure_get_insecure_random_bytes(uint64_t length, wasip2_list_u8_t *out) {
    ++insecure_calls; out->len = (size_t)length;
    out->ptr = malloc(out->len); memset(out->ptr, 0x71, out->len);
}
void wasip2_list_u8_free(wasip2_list_u8_t *value) { ++freed; free(value->ptr); }
int main(void) {
    uint8_t data[65538];
    memset(data, 0x5a, sizeof(data));
    assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(0, 0) == 0);
    assert(calls == 0);
    assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(0, 1) == -1);
    assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(data, -1) == -1);
    assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(data, 65537) == -1);
    assert(calls == 0 && data[0] == 0x5a && data[65537] == 0x5a);
    const int lengths[] = {1, 8, 9, 32, 257, 4096, 65536};
    for (unsigned test = 0; test < sizeof(lengths)/sizeof(lengths[0]); ++test) {
        int length = lengths[test]; calls = 0;
        memset(data, 0x5a, sizeof(data));
        assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(data + 1, length) == 0);
        assert(calls == (unsigned)(length + 7) / 8);
        for (int i = 0; i < length; ++i) assert(data[i + 1] == i % 8 + 1);
        assert(data[0] == 0x5a && data[length + 1] == 0x5a);
    }
    for (failures = 0; failures < 3; ++failures) {
        for (fail_at = 1; fail_at <= 33; fail_at += 32) {
            calls = 0; memset(data, 0x5a, sizeof(data));
            assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(data + 1, 257) == -1);
            assert(calls == fail_at);
            for (int i = 1; i <= 257; ++i) assert(data[i] == 0);
            assert(data[0] == 0x5a && data[258] == 0x5a);
        }
    }
    fail_at = calls = 0;
    assert(__wrap_SystemNative_GetCryptographicallySecureRandomBytes(data, 9) == 0 && calls == 2);
    assert(insecure_calls == 0 && freed == 0);
    __wrap_SystemNative_GetNonCryptographicallySecureRandomBytes(data, 9);
    assert(insecure_calls == 1 && freed == 1 && calls == 2);
    for (int i = 0; i < 9; ++i) assert(data[i] == 0x71);
    return 0;
}
''')
            shutil.copyfile(source, root / 'entropy.c')
            subprocess.run([compiler, '-std=c11', '-O2', '-Wno-attributes', '-I', str(root),
                            str(harness), '-o', str(root / 'reference')], check=True,
                           capture_output=True, timeout=30)
            subprocess.run([str(root / 'reference')], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
