"""Source/data tests only; no local C guest/compiler execution."""
from pathlib import Path
import tempfile,unittest
from tools import c_thread_minimal_fixture as selected,c_thread_runtime_fixture as original
from tools.rust_capsule_project import ROOT,snapshot,read_json
class CThreadMinimal(unittest.TestCase):
 def test_minimal_overlay_preserves_every_original_byte_and_full_standard_lifecycle_calls(self):
  raw=(ROOT/(original.FIXTURE+'main.c')).read_bytes();derived=selected.selected_source(raw)
  self.assertEqual(derived.replace(selected.FUNCTIONS,b'',1).replace(selected.CASES,b'',1),raw)
  self.assertEqual(selected.CASES.count(b'entered_after_create = minimal_entered;'),2)
  self.assertNotIn(b'require(minimal_entered == 0 && errno == 23);',selected.CASES)
  self.assertIn(b'minimal-pthread:42:1:create=0',selected.CASES)
  self.assertIn(b'minimal-pthread:42:1:create=1',selected.CASES)
  self.assertIn(b'minimal-c11:42:1:create=0',selected.CASES)
  self.assertIn(b'minimal-c11:42:1:create=1',selected.CASES)
  self.assertIn(b'pthread_join(child, &actual) == 0 && actual == &argument',selected.CASES)
  self.assertIn(b'thrd_join(child, &actual) == thrd_success && actual == 42',selected.CASES)
  self.assertNotIn(b'pthread_',selected.FUNCTIONS.split(b'static void *minimal_pthread')[1].split(b'}')[0].split(b'{')[1])
  for altered in(raw+b'\n',raw.replace(b'errno = 23;',b'errno = 24;')):
   with self.assertRaisesRegex(ValueError,'original-main-preimage'):selected.selected_source(altered)
 def test_only_application_main_changes_and_all_original_limits_profile_wit_remain_exact(self):
  with tempfile.TemporaryDirectory()as temp:
   a=original.prepare(Path(temp)/'original');b=selected.prepare(Path(temp)/'minimal')
   left,right=snapshot(a),snapshot(b)
   self.assertEqual(set(left),set(right))
   # The shared SDK added seven captured libfetch inputs. Preserve the original
   # 65-file envelope and compare every added input with its maintained source.
   libfetch={'vendor/lsf/sdk/c-guest/'+name for name in (
    'include/fetch.h','src/libfetch/UPSTREAM.json','src/libfetch/common.h',
    'src/libfetch/fetch.c','src/libfetch/http.c',
    'src/libfetch/upstream/common.h','src/libfetch/upstream/fetch.h')}
   self.assertTrue(libfetch <= set(left))
   self.assertEqual(len(set(left)-libfetch),65)
   for name in sorted(libfetch):
    self.assertEqual(left[name],(ROOT/name.removeprefix('vendor/lsf/')).read_bytes(),name)
   self.assertEqual([n for n in left if left[n]!=right[n]],['src/main.c'])
   self.assertEqual(read_json(a/'capsule-project.json'),read_json(b/'capsule-project.json'))
   self.assertIn(b'greet: async func',right['wit/world.wit'])
  self.assertEqual(selected.MODES,('application-error','minimal-c11','minimal-pthread','c11','pthread'))
if __name__=='__main__':unittest.main()
