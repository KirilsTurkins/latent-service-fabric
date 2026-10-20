"""Pinned derivation and resource-owner boundaries; native execution is separate."""
import hashlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import network, network_context, runtime, sdk

FIXTURES = Path(__file__).parent / 'fixtures/go_network'
SDK = runtime.ROOT / 'sdk/go-guest'


class GoNetworkSourceTests(unittest.TestCase):
    def generated(self):
        return (FIXTURES / 'streams-generated.go.txt').read_text(encoding='utf-8')

    def goroot(self, root):
        for name in network.PREIMAGES:
            target = root / 'src' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((FIXTURES / name).read_bytes())
        return root

    def module(self, root, source=None, package='latent_network_streams'):
        target = root / package / 'wit_bindings.go'
        target.parent.mkdir(parents=True)
        target.write_text(source if source is not None else self.generated(), encoding='utf-8', newline='\n')
        return target

    def test_actual_generated_identity_requires_managed_v5_without_installing_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            self.assertFalse(network_context.selected(root, 'go-component-async-v1'))
            self.module(root)
            for profile in ('go-component-async-v1', 'go-component-activation-v1',
                            'go-component-activation-v4', False, None):
                with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'requires-managed-v5'):
                    network_context.selected(root, profile)
            self.assertTrue(network_context.selected(root, 'go-component-activation-v5'))
            self.assertFalse((root / 'lsf').exists())

    def test_unknown_version_or_interface_and_aliased_or_duplicate_package_fail_closed(self):
        original = self.generated()
        for source, package in ((original.replace('@0.1.0 ', '@9.0.0 '), 'latent_network_streams'),
                                (original.replace('/streams@', '/other@'), 'latent_network_streams'),
                                (original, 'arbitrary_alias')):
            with self.subTest(package=package), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.module(root, source, package)
                with self.assertRaises(ValueError):
                    network_context.selected(root, 'go-component-activation-v5')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.module(root)
            self.module(root, package='duplicate')
            with self.assertRaisesRegex(ValueError, 'package-identity'):
                network_context.selected(root, 'go-component-activation-v5')

    def test_original_canonical_marshalling_and_original_entry_points_are_preserved(self):
        original = self.generated()
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         '21d79d0d1efdf115b9082a364abe40cb30256f3b197416f57f15cbec94e9319a')
        changed = network_context.generated_source(original)
        first = changed.index('\n\nfunc ConnectContext(')
        self.assertEqual(changed[:first].replace('\tlsfNetworkContext "context"\n', ''), original)
        for name in network_context.PREIMAGES:
            self.assertEqual(changed.count('func ' + name + 'Context('), 1)
            body = re.search(r'(?ms)^func ' + name + r'Context\(.*?^\}', changed)[0]
            self.assertLess(body.index('if ctx.Err()'), body.index('runtime.Pinner'))
            self.assertIn('ctx.Err() == lsfNetworkContext.DeadlineExceeded', body)
            self.assertIn('StreamError{Code: ErrorCodeTimeout}', body)
            self.assertLess(body.index('if status != 2'), body.index('switch uint8('))
            self.assertLess(body.index('defer pinner.Unpin()'), body.index('SubtaskWaitContext'))

    def test_every_generated_function_preimage_and_single_derivation_is_required(self):
        original = self.generated()
        for name in network_context.PREIMAGES:
            changed = re.sub(r'(func ' + name + r'\([^\n]+\{\n)',
                             r'\1\tpanic("changed marshalling")\n', original, count=1)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'source-drift:' + name):
                network_context.generated_source(changed)
        with self.assertRaisesRegex(ValueError, 'already-derived'):
            network_context.generated_source(network_context.generated_source(original))

    def test_close_restores_only_untransferred_own_handle_and_cancellation_keeps_uncertainty(self):
        changed = network_context.generated_source(self.generated())
        close = re.search(r'(?ms)^func CloseContext\(.*?^\}', changed)[0]
        self.assertEqual(close.count('target.TakeHandle()'), 1)
        self.assertEqual(close.count('target.SetHandle(argumentHandle)'), 1)
        self.assertIn('status == witAsync.LSF_HTTP_START_CANCELLED { target.SetHandle(argumentHandle) }', close)
        self.assertNotIn('LSF_HTTP_RETURN_CANCELLED { target.SetHandle', close)
        for name in network_context.PREIMAGES:
            body = re.search(r'(?ms)^func ' + name + r'Context\(.*?^\}', changed)[0]
            self.assertEqual('MayHaveApplied: true' in body, name in network_context.MAY_APPLY)
            self.assertEqual('status != witAsync.LSF_HTTP_START_CANCELLED' in body,
                             name in network_context.MAY_APPLY)
            self.assertNotIn('AcceptedPrefixBytes:', body[:body.index('var result')])

    def test_actual_install_creates_owned_facade_without_raw_resource_constructors_or_gc_drop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.module(root)
            self.assertFalse(sdk.install(SDK, root, network_context=True))
            aliases = (root / 'lsf/network/types.go').read_text()
            self.assertNotRegex(aliases, r'type (Connection|Chunk) = raw\.')
            self.assertNotIn('FromOwnHandle', aliases)
            self.assertNotIn('runtime.AddCleanup', raw.read_text())
            self.assertIn('func ConnectContext(', raw.read_text())
            self.assertEqual((root / 'lsf/network/owner.go').read_bytes(),
                             (SDK / 'capabilities/network-owner.go.in').read_bytes())
            self.assertEqual((root / 'lsf/ownership/owner.go').read_bytes(),
                             (SDK / 'ownership/owner.go').read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.module(root)
            with self.assertRaisesRegex(ValueError, 'requires-selected-context'):
                sdk.install(SDK, root)

    def test_no_declared_stream_preserves_the_ordinary_sdk_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(sdk.install(SDK, root))
            self.assertFalse((root / 'lsf/network').exists())
            self.assertEqual((root / 'lsf/ownership/owner.go').read_bytes(),
                             (SDK / 'ownership/owner.go').read_bytes())

    def test_incomplete_or_nonboolean_dispatcher_selection_cannot_publish_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in (True, 1, 'yes', None):
                with self.subTest(value=value), patch.object(runtime, 'checked_sources', return_value={}):
                    with self.assertRaisesRegex(ValueError, 'network-requires-complete'):
                        runtime.overlay(root / 'goroot', root / 'out', network_context=value)
                    self.assertFalse((root / 'out').exists())
            with patch.object(runtime, 'checked_sources', return_value={}):
                with self.assertRaisesRegex(ValueError, 'network-requires-complete-managed-v5'):
                    runtime.overlay(root / 'goroot', root / 'out', network_context=True,
                        activation=True, checkpoints=True, timers=True, initializers=True)
                self.assertFalse((root / 'out').exists())

    def test_precancelled_close_preserves_owner_and_final_drop_is_never_claimed_no_effect(self):
        source = (SDK / 'capabilities/network.go.in').read_text()
        close = re.search(r'(?ms)^func \(c \*Connection\) CloseContext\(.*?^\}', source)[0]
        self.assertLess(close.index('if ctx.Err()'), close.index('beginClose()'))
        self.assertLess(close.index('defer value.Drop()'), close.index('raw.CloseContext(ctx, value)'))
        self.assertIn('r.Err().Code == ErrorCodeCancelled', close)
        self.assertIn('ErrorCodeUncertain, MayHaveApplied: true', close)

    def test_full_upstream_preimages_are_required_before_any_overlay_is_created(self):
        for name in network.PREIMAGES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                goroot = self.goroot(root / 'go')
                path = goroot / 'src' / name
                path.write_bytes(path.read_bytes() + b'// unreviewed source\n')
                with self.assertRaisesRegex(ValueError, 'source-drift'):
                    network.prepare(goroot, SDK, root / 'out', 'example.org/module')
                self.assertFalse((root / 'out').exists())

    def test_real_pinned_dial_projection_bypasses_ambient_resolution_without_editing_upstream(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.goroot(root / 'go')
            before = {name: (goroot / 'src' / name).read_bytes() for name in network.PREIMAGES}
            replacements = network.prepare(goroot, SDK, root / 'out', 'outside.example/developer/v2')
            self.assertEqual(before, {name: (goroot / 'src' / name).read_bytes() for name in network.PREIMAGES})
            self.assertEqual(set(replacements), {str(goroot / 'src' / name) for name in network.PREIMAGES})
            text = Path(replacements[str(goroot / 'src/net/dial.go')]).read_text()
            body = re.search(r'(?ms)^func \(d \*Dialer\) DialContext\(.*?^\}', text)[0]
            self.assertIn('return lsfStreamDial(ctx, d, network, address)', body)
            self.assertNotIn('resolveAddrList', body)
            self.assertNotIn('dialParallel', body)
            self.assertIn('"outside.example/developer/v2/lsf/network"', text)
            self.assertIn('\t"internal/nettrace"', text)
            self.assertIn('ctx.Value(nettrace.TraceKey{})', text)  # retained upstream dialSerial
            original = before['net/dial.go'].decode()
            self.assertIn('d.resolver().resolveAddrList', original)
            self.assertNotIn('lsfStreamDial', original)

    def test_standalone_dns_and_concrete_tcp_are_closed_unsupported_without_os_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.goroot(root / 'go')
            replacements = network.prepare(goroot, SDK, root / 'out', 'example.org/app')
            lookup = Path(replacements[str(goroot / 'src/net/lookup.go')]).read_text()
            self.assertIn('\t_ "internal/stringslite"', lookup)
            self.assertNotIn('stringslite.', lookup)
            names = ('LookupHost', 'LookupIPAddr', 'LookupIP', 'LookupNetIP', 'LookupCNAME',
                     'LookupSRV', 'LookupMX', 'LookupNS', 'LookupTXT', 'LookupAddr')
            for name in names:
                body = re.search(r'(?ms)^func \(r \*Resolver\) ' + name + r'\(.*?^\}', lookup)[0]
                self.assertIn('errors.ErrUnsupported', body)
                self.assertNotIn('r.lookup', body)
            port = re.search(r'(?ms)^func \(r \*Resolver\) LookupPort\(.*?^\}', lookup)[0]
            self.assertIn('parsePort(service)', port)
            self.assertIn('if needsLookup { return 0, errors.ErrUnsupported }', port)
            tcp = Path(replacements[str(goroot / 'src/net/tcpsock.go')]).read_text()
            self.assertIn('Err: lsfStreamUnsupported()',
                re.search(r'(?ms)^func DialTCP\(.*?^\}', tcp)[0])

    def test_injection_or_changed_template_cannot_publish_a_projection(self):
        for module in ('../escape', 'example//bad', 'quote"bad', 'line\nbad', '', 'x' * 257):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaisesRegex(ValueError, 'module-identity'):
                    network.prepare(root / 'absent', SDK, root / 'out', module)
                self.assertFalse((root / 'out').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.goroot(root / 'go')
            template = root / 'sdk/runtime/net_stream.go.in'
            template.parent.mkdir(parents=True)
            template.write_text('package changed\n')
            with self.assertRaisesRegex(ValueError, 'template-shape'):
                network.prepare(goroot, root / 'sdk', root / 'out', 'example.org/app')
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
