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
   import hashlib
   added_sdk = {
    'vendor/lsf/sdk/c-guest/include/fetch.h': 'd76b1cbb55925fd81258a4f37f3e76d50a8e3a24c9e08d96cfbff3ca7e09dbf4',
    'vendor/lsf/sdk/c-guest/src/libfetch/common.h': '3fd471f5d8c7f08bf3d9fdcbbc1c0496cdc07fac29766442410cc3ae127db792',
    'vendor/lsf/sdk/c-guest/src/libfetch/fetch.c': 'e161caef3dd62b8ae90748f30ff89fb5e14328e9abf8f56efdc6bc2bc0cbb426',
    'vendor/lsf/sdk/c-guest/src/libfetch/http.c': '61e9ca20c90e9065c3e0e99b075b4c7aa304d496b91db87bcb2d2aa5c82d5867',
    'vendor/lsf/sdk/c-guest/src/libfetch/UPSTREAM.json': '3f18638501217b6532275c972e0681b978c78afe833c2265779e7b66b4d479df',
    'vendor/lsf/sdk/c-guest/src/libfetch/upstream/fetch.h': 'f3bce6b530b4b6f18e93abdb2864605e50e616917d0e0b01f8677e36b6964956',
    'vendor/lsf/sdk/c-guest/src/libfetch/upstream/common.h': '2ba826d9eefbe788cbd0e1d08a54a46e228eee7842e57a21e9971ed9e1200b43',
   }
   # Reviewed finite file ABI/GET metadata addendum; old seven pins remain below.
   current_addendum = {'vendor/lsf/sdk/c-guest/src/closed-file-abi.c': '7b825118e32ce9561e8d876c14a0e50e33cad997b5a8599c4112e6f40323212a', 'vendor/lsf/sdk/c-guest/src/libfetch/upstream/musl-COPYRIGHT': 'f9bc4423732350eb0b3f7ed7e91d530298476f8fec0c6c427a1c04ade22655af', 'vendor/lsf/sdk/c-guest/src/libfetch/http.c': 'f3f495e024a79d5221c0fd42b321c33105295c90d085756e8a36af5f8f89f5a2', 'vendor/lsf/sdk/c-guest/src/libfetch/UPSTREAM.json': 'e137aef2ca8901ce260c5aed164d0eec6d5c46ef94e1f0a61b408d757f0606a2'}
   for path, expected in current_addendum.items():
    self.assertEqual(left[path], right[path], path)
    self.assertEqual(hashlib.sha256(left[path]).hexdigest(), expected, path)
    if path in added_sdk:
     added_sdk[path] = expected
    else:
     del left[path]; del right[path]
   for path, expected in added_sdk.items():
    self.assertEqual(left[path], right[path], path)
    self.assertEqual(hashlib.sha256(left[path]).hexdigest(), expected, path)
    del left[path]; del right[path]
   self.assertEqual(set(left),set(right));self.assertEqual(len(left),65)
   self.assertEqual([n for n in left if left[n]!=right[n]],['src/main.c'])
   self.assertEqual(read_json(a/'capsule-project.json'),read_json(b/'capsule-project.json'))
   self.assertIn(b'greet: async func',right['wit/world.wit'])
  self.assertEqual(selected.MODES,('application-error','minimal-c11','minimal-pthread','c11','pthread'))
if __name__=='__main__':unittest.main()
