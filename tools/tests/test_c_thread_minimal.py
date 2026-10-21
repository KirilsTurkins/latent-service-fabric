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
   self.assertEqual(set(left),set(right));self.assertEqual(len(left),63)
   self.assertEqual([n for n in left if left[n]!=right[n]],['src/main.c'])
   self.assertEqual(read_json(a/'capsule-project.json'),read_json(b/'capsule-project.json'))
   self.assertIn(b'greet: async func',right['wit/world.wit'])
  self.assertEqual(selected.MODES,('application-error','minimal-c11','minimal-pthread','c11','pthread'))
if __name__=='__main__':unittest.main()
