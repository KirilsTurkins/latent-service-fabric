"""Fixed failed artifact, source restoration and finite numeric-only diagnostics."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import diagnose_go_smtp_tls_frames as q

class GoSmtpTlsFramesTests(unittest.TestCase):
    def archive(self, extra='safe'):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name in q.SELECTED:z.writestr(name,b'fixed')
            for n in range(45):z.writestr('log'+str(n)+'.txt',b'public')
            z.writestr(extra,b'public')
        return out.getvalue()
    def test_exact_fixed_archive_and_component_are_required_before_selected_extraction(self):
        raw=self.archive()
        with patch.object(q,'SIZE',len(raw)),patch.object(q,'SHA',q.digest(raw)),patch.object(q,'COMPONENT',q.digest(b'fixed')):
            self.assertEqual(set(q.selected(raw)),set(q.SELECTED))
            with self.assertRaisesRegex(ValueError,'exact-archive'):q.selected(raw[:-1])
            with patch.object(q,'COMPONENT',q.digest(b'other')):
                with self.assertRaisesRegex(ValueError,'exact-component'):q.selected(raw)
    def test_unselected_traversal_and_duplicate_members_also_fail_before_use(self):
        for extra in ('../private',q.SELECTED[0]):
            raw=self.archive(extra)
            with patch.object(q,'SIZE',len(raw)),patch.object(q,'SHA',q.digest(raw)),patch.object(q,'COMPONENT',q.digest(b'fixed')):
                with self.assertRaises(ValueError):q.selected(raw)
    def test_every_original_declared_source_row_must_still_match(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows={}
            for n in range(100):
                name='source'+str(n);(root/name).write_bytes(b'x');rows[name]={'digest':q.digest(b'x'),'size':1}
            with patch.object(q,'ROOT',root):
                q.verify_original(rows)
                (root/'source50').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'original-source-changed'):q.verify_original(rows)
    def test_private_overlay_does_not_enable_dwarf_or_change_limits_and_remains_nonqualification(self):
        source=Path(q.__file__).read_text()
        self.assertIn('frames.overlay_sources(ROOT,private)',source)
        self.assertIn("'dwarfEnabled':False",source)
        self.assertIn("'qualification':False",source)
        self.assertIn("'guestRecompiled':False",source)
        self.assertIn("'nativeFiveRebuilt':False",source)
        self.assertIn('for name,raw in originals.items():(ROOT/name).write_bytes(raw)',source)
        self.assertNotIn('compiler.compile(',source)
        self.assertNotIn('frame.func_name()',source)
        self.assertNotIn('error.to_string()',source)
    def test_existing_numeric_decoder_rejects_symbols_private_fields_and_unbounded_frames(self):
        good={'available':True,'truncated':False,'frames':[{'functionIndex':1,'functionOffset':2,'moduleOffset':3}]}
        def raw(v):return q.frames.PREFIX+json.dumps(v).encode()+b'\n'
        self.assertEqual(q.frames.numeric_frames(raw(good)),good)
        for bad in (dict(good,private='secret'),dict(good,frames=[dict(good['frames'][0],name='private')]),dict(good,frames=good['frames']*33)):
            with self.assertRaises(Exception):q.frames.numeric_frames(raw(bad))

if __name__=='__main__':unittest.main()
