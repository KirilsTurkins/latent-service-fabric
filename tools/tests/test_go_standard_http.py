"""Pinned source and namespace boundaries; actual compilation runs separately."""
from pathlib import Path
import tempfile
import unittest

from tools.go_guest import http
from tools.rust_capsule_project import ROOT


class StandardHttpSourceTests(unittest.TestCase):
    def fixture(self, root):
        directory = root/'goroot/src/net/http'
        directory.mkdir(parents=True)
        for name in http.PREIMAGES:
            (directory/Path(name).name).write_bytes((Path(__file__).parent/'fixtures/go-standard-http'/Path(name).name).read_bytes())
        return root/'goroot'

    def test_private_projection_retains_all_original_sources_and_public_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.fixture(root)
            before = {name:(goroot/'src'/name).read_bytes() for name in http.PREIMAGES}
            selected = http.prepare(goroot, ROOT/'sdk/go-guest', root/'out', 'example.org/arbitrary-developer/v2')
            self.assertEqual({name:(goroot/'src'/name).read_bytes() for name in http.PREIMAGES}, before)
            self.assertEqual(set(selected), {str(goroot/'src/net/http/roundtrip.go'), str(goroot/'src/net/http/transport.go')})
            self.assertIn('"example.org/arbitrary-developer/v2/lsf/streaming"', Path(selected[str(goroot/'src/net/http/roundtrip.go')]).read_text())
            self.assertTrue(all(Path(value).is_relative_to(root/'out') for value in selected.values()))

    def test_every_full_upstream_preimage_is_required_before_creating_outputs(self):
        for changed in http.PREIMAGES:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                goroot = self.fixture(root)
                path = goroot/'src'/changed
                path.write_bytes(path.read_bytes()+b'// changed source\n')
                with self.assertRaisesRegex(ValueError, 'source-drift'):
                    http.prepare(goroot, ROOT/'sdk/go-guest', root/'out', 'outside.test/module')
                self.assertFalse((root/'out').exists())

    def test_default_selects_typed_backend_without_allowing_custom_dialers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.fixture(root)
            original = (goroot/'src/net/http/transport.go').read_text(encoding='utf-8')
            self.assertIn('DialContext: defaultTransportDialContext(&net.Dialer{', original)
            selected = http.prepare(goroot, ROOT/'sdk/go-guest', root/'out', 'outside.test/client')
            transport = Path(selected[str(goroot/'src/net/http/transport.go')]).read_text(encoding='utf-8')
            default = transport.split('var DefaultTransport RoundTripper = &Transport{', 1)[1].split('\n}', 1)[0]
            self.assertIn('DialContext: nil,', default)
            self.assertIn('DisableCompression: true,', default)
            self.assertIn('Proxy: ProxyFromEnvironment,', default)
            backend = Path(selected[str(goroot/'src/net/http/roundtrip.go')]).read_text(encoding='utf-8')
            self.assertIn('if t.DialContext != nil || t.Dial != nil', backend)
            self.assertEqual((goroot/'src/net/http/transport.go').read_text(encoding='utf-8'), original)

    def test_module_names_are_literal_and_cannot_inject_imports_or_paths(self):
        for module in ('../escape', 'example.com//bad', 'quote"injection', 'bad\npath', 'C:\\source', '', 'x'*257):
            with self.subTest(module=module), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaisesRegex(ValueError, 'module-identity'):
                    http.prepare(root/'missing', ROOT/'sdk/go-guest', root/'out', module)
                self.assertFalse((root/'out').exists())

    def test_changed_template_fails_before_publishing_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = self.fixture(root)
            (root/'sdk/runtime').mkdir(parents=True)
            (root/'sdk/runtime/http_transport.go.in').write_text('package changed\n')
            with self.assertRaisesRegex(ValueError, 'template-shape'):
                http.prepare(goroot, root/'sdk', root/'out', 'outside.test/module')
            self.assertFalse((root/'out').exists())


if __name__ == '__main__': unittest.main()
