import json
from pathlib import Path
import tempfile
import unittest

from tools import dotnet_http_library_edges_fixture as fixture
from tools import dotnet_published_http_fixture as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, digest, inventory, read_file


class LibraryBodyErrorFixture(unittest.TestCase):
    def test_only_application_transport_error_handling_and_normal_template_digest_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            plain=original.project(Path(temporary)/'plain')
            fixed=fixture.project(Path(temporary)/'fixed')
            old=read_file(plain/'src/Main.cs');new=read_file(fixed/'src/Main.cs')
            self.assertEqual(new.replace(fixture.AFTER,fixture.BEFORE,1),old)
            self.assertEqual(new.count(fixture.AFTER),1)
            self.assertEqual(inventory({p.relative_to(plain/'vendor/lsf').as_posix():p.read_bytes() for p in (plain/'vendor/lsf').rglob('*') if p.is_file()}),
                             inventory({p.relative_to(fixed/'vendor/lsf').as_posix():p.read_bytes() for p in (fixed/'vendor/lsf').rglob('*') if p.is_file()}))
            before=json.loads(read_file(plain/'sdk-lock.json'));after=json.loads(read_file(fixed/'sdk-lock.json'))
            self.assertEqual(after['template']['sourceDigest'],digest(new))
            after['template']['sourceDigest']=before['template']['sourceDigest']
            self.assertEqual(before,after)
            self.assertEqual(read_file(plain/'capsule-project.json'),read_file(fixed/'capsule-project.json'))

    def test_unknown_application_source_is_refused_before_any_derivation(self):
        source=read_file(ROOT/original.ROOT_SOURCE)
        for changed in (source+b'\n',source.replace(b'new FlurlClient()',b'new FlurlClient(null)'),
                        fixture.managed_source(source),bytearray(source)):
            with self.subTest(kind=type(changed).__name__),self.assertRaisesRegex(WorkflowError,'application-preimage'):
                fixture.managed_source(changed)
