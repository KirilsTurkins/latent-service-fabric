"""Source/data tests only; no local C guest/compiler execution."""
from pathlib import Path
import tempfile,unittest
from tools import c_thread_minimal_fixture as selected,c_thread_runtime_fixture as original
from tools.rust_capsule_project import ROOT,snapshot,read_json

# PR #1582 (00799f8805c0e213958ba25d35fb4e762a514904) added only this
# activation-local fatal-process trap after the finite file ABI was pinned.
EXIT_TRAP_ADDENDUM = b'/* Process completion is unsupported: retain original owners through the\n * activation trap and Store cleanup. No atexit callbacks or stdio flushing.\n */\n_Noreturn void exit(int status) {\n    (void)status;\n    __builtin_trap();\n}\n\n'


def before_exit_trap(raw):
 import hashlib
 if hashlib.sha256(raw).hexdigest() != '8af8989600438fdf5ebe265e3065404f0412270e8dc11b2fee8934de5ba3887f':
  raise AssertionError('closed-file-exact-exit-trap-source')
 if raw.count(EXIT_TRAP_ADDENDUM) != 1:
  raise AssertionError('closed-file-exact-exit-trap-addendum')
 original = raw.replace(EXIT_TRAP_ADDENDUM, b'', 1)
 if hashlib.sha256(original).hexdigest() != '7b825118e32ce9561e8d876c14a0e50e33cad997b5a8599c4112e6f40323212a':
  raise AssertionError('closed-file-original-abi-source')
 return original

def before_body_media(raw):
 import hashlib
 if hashlib.sha256(raw).hexdigest() != '7e7ffd0526c5f474329a1136dd10942783abe77190416e69c6893d1e1c2085c3':
  raise AssertionError('libfetch-body-media-exact-source')
 changes = ((b'    const size_t media_length = content_type ? strnlen(content_type, 257) : 0;\n', b'    /* The pinned frontend only uses Content-Type when body is non-NULL. */\n    const size_t media_length = body && content_type ? strnlen(content_type, 257) : 0;\n'), (b'    if (content_type) {\n        metadata.body_media_type.is_some = true;\n', b'    if (body && content_type) {\n        metadata.body_media_type.is_some = true;\n'))
 for previous, current in reversed(changes):
  if raw.count(current) != 1: raise AssertionError('libfetch-body-media-exact-addendum')
  raw = raw.replace(current, previous, 1)
 if hashlib.sha256(raw).hexdigest() != 'b757ebb3ec8633b1f792333fef598a10bc6d724cfe340e2d45415ed2385cd96a':
  raise AssertionError('libfetch-body-media-prior-source')
 return raw


def before_head_metadata(path, raw):
 import hashlib
 if path.rsplit('/', 1)[-1] == 'http.c': raw = before_body_media(raw)
 changes = {'http.c': ('b757ebb3ec8633b1f792333fef598a10bc6d724cfe340e2d45415ed2385cd96a', '14f71c8141d2170f757b9c78a6b206095cb3d0ad86958de501f5e2a3663bc70e', ((b'static bool content_length(const latent_http_streaming_list_header_t *headers, size_t *length, bool *known) {\n    bool found = false;\n    *length = SIZE_MAX; /* The original libfetch unknown-length sentinel. */\n    *known = false;\n    for (size_t i = 0; i < headers->len; ++i) {\n        const latent_http_streaming_header_t *header = &headers->ptr[i];\n        static const char name[] = "content-length";\n        if (header->name.len != sizeof(name) - 1) continue;\n        bool match = true;\n        for (size_t at = 0; at < sizeof(name) - 1; ++at) {\n            uint8_t value = header->name.ptr[at];\n            if (value >= \'A\' && value <= \'Z\') value += \'a\' - \'A\';\n            if (value != (uint8_t)name[at]) match = false;\n        }\n        if (!match) continue;\n        if (found || !header->value.len) return false;\n        found = true;\n        size_t value = 0;\n        for (size_t at = 0; at < header->value.len; ++at) {\n            uint8_t digit = header->value.ptr[at];\n            if (digit < \'0\' || digit > \'9\' || value > (SIZE_MAX - (digit - \'0\')) / 10) return false;\n            value = value * 10 + digit - \'0\';\n        }\n        *length = value;\n    }\n    *known = found;\n    return true;\n}\n', b'static bool content_length(const latent_http_streaming_list_header_t *headers, bool head,\n                           size_t *length, off_t *representation_size, bool *known) {\n    bool found = false;\n    *length = SIZE_MAX; /* The original libfetch unknown-length sentinel. */\n    *representation_size = (off_t)-1;\n    *known = false;\n    for (size_t i = 0; i < headers->len; ++i) {\n        const latent_http_streaming_header_t *header = &headers->ptr[i];\n        static const char name[] = "content-length";\n        if (header->name.len != sizeof(name) - 1) continue;\n        bool match = true;\n        for (size_t at = 0; at < sizeof(name) - 1; ++at) {\n            uint8_t value = header->name.ptr[at];\n            if (value >= \'A\' && value <= \'Z\') value += \'a\' - \'A\';\n            if (value != (uint8_t)name[at]) match = false;\n        }\n        if (!match) continue;\n        if (found || !header->value.len) return false;\n        found = true;\n        uint64_t value = 0;\n        for (size_t at = 0; at < header->value.len; ++at) {\n            uint8_t digit = header->value.ptr[at];\n            if (digit < \'0\' || digit > \'9\' || value > ((uint64_t)INT64_MAX - (digit - \'0\')) / 10) return false;\n            value = value * 10 + digit - \'0\';\n        }\n        /* HEAD describes a representation, not bytes to buffer. The stat\n         * size can therefore exceed wasm32 size_t. Keep URL.length at its\n         * unknown sentinel when that field cannot represent the value. */\n        if (value > SIZE_MAX && !head) return false;\n        *length = value > SIZE_MAX ? SIZE_MAX : (size_t)value;\n        *representation_size = (off_t)value;\n    }\n    *known = found;\n    return true;\n}\n'), (b'    const bool valid_length = content_length(&completed.val.ok.headers, &length, &known_length);\n    off_t actual_offset = 0, representation_size = known_length ? (off_t)length : (off_t)-1;\n', b'    off_t representation_size;\n    const bool valid_length = content_length(&completed.val.ok.headers,\n        operation == LATENT_HTTP_STREAMING_METHOD_HEAD, &length, &representation_size, &known_length);\n    off_t actual_offset = 0;\n'))), 'UPSTREAM.json': ('117a3dfa1f5be24be75496362dd2aa7757888afda4c02cf101b1cd6ba6881085', '5f7795e7318f9e931aa0fef5f8e05368e69d24b26fca22471ec4302bdb245237', ((b'Validated Content-Length, or signed off_t -1 if absent. No buffering/replay to invent length.', b'Validated Content-Length up to the signed off_t maximum, or signed off_t -1 if absent. For HEAD, a value larger than size_t is reported in url_stat while URL.length remains the SIZE_MAX unknown sentinel. Other methods require a size_t-representable length. No buffering/replay to invent length.'),))}
 digest, previous_digest, replacements = changes[path.rsplit('/', 1)[-1]]
 if hashlib.sha256(raw).hexdigest() != digest:
  raise AssertionError('libfetch-head-metadata-exact-source')
 for previous, current in reversed(replacements):
  if raw.count(current) != 1: raise AssertionError('libfetch-head-metadata-exact-addendum')
  raw = raw.replace(current, previous, 1)
 if hashlib.sha256(raw).hexdigest() != previous_digest:
  raise AssertionError('libfetch-head-metadata-prior-source')
 return raw


def before_host_boundary(raw):
 import hashlib
 if hashlib.sha256(raw).hexdigest() != '7e7ffd0526c5f474329a1136dd10942783abe77190416e69c6893d1e1c2085c3':
  raise AssertionError('libfetch-host-boundary-exact-source')
 raw = before_head_metadata('http.c', raw)
 if hashlib.sha256(raw).hexdigest() != '14f71c8141d2170f757b9c78a6b206095cb3d0ad86958de501f5e2a3663bc70e':
  raise AssertionError('libfetch-host-boundary-exact-source')
 current = b'    /* Host and document are separate libfetch fields. Do not let a URL\n     * component delimiter in the host change the requested document. */\n    if (memchr(url->host, \'/\', host) || memchr(url->host, \'?\', host) ||\n        memchr(url->host, \'#\', host) || memchr(url->host, \'@\', host) ||\n        memchr(url->host, \'\\\\\', host)) {\n        failure(FETCH_URL, EINVAL, "Invalid constructed HTTP host"); return NULL;\n    }\n'
 if raw.count(current) != 1:
  raise AssertionError('libfetch-host-boundary-exact-addendum')
 raw = raw.replace(current, b'', 1)
 if hashlib.sha256(raw).hexdigest() != '1418689760e50035c1bb3cc1979e5170a2cc11fa763a5f87889102e9684b0b03':
  raise AssertionError('libfetch-host-boundary-prior-source')
 return raw

def before_http_status_categories(raw):
 import hashlib
 raw = before_host_boundary(raw)
 if hashlib.sha256(raw).hexdigest() != '1418689760e50035c1bb3cc1979e5170a2cc11fa763a5f87889102e9684b0b03':
  raise AssertionError('libfetch-http-status-exact-source')
 changes = (
  (b'', b"/* Keep the upstream libfetch categories for actual HTTP errors.\n * This does not retry a request or change the profile's existing errno values. */\nstatic int http_status_category(uint16_t status) {\n    switch (status) {\n    case 400: case 405: case 406: case 411: case 413: case 414: case 415:\n    case 501: case 505:\n        return FETCH_PROTO;\n    case 402: case 407:\n        return FETCH_AUTH;\n    case 408: case 504:\n        return FETCH_TIMEOUT;\n    case 409:\n        return FETCH_EXISTS;\n    case 416:\n        return FETCH_UNAVAIL;\n    case 503:\n        return FETCH_TEMP;\n    default:\n        return FETCH_SERVER;\n    }\n}\n\n"),
  (b'        else failure(FETCH_SERVER, EIO, "HTTP server returned an error response");', b'        else failure(http_status_category(status), EIO, "HTTP server returned an error response");'),
 )
 for previous, current in reversed(changes):
  if raw.count(current) != 1:
   raise AssertionError('libfetch-http-status-exact-addendum')
  raw = raw.replace(current, previous, 1)
 if hashlib.sha256(raw).hexdigest() != '906a26d42fad5eb071b02191282f1a3da60a8cfa117782cd125a34f6ad02ab1d':
  raise AssertionError('libfetch-http-status-prior-source')
 return raw

def before_fragment_target(raw):
 import hashlib
 raw = before_http_status_categories(raw)
 if hashlib.sha256(raw).hexdigest() != '906a26d42fad5eb071b02191282f1a3da60a8cfa117782cd125a34f6ad02ab1d':
  raise AssertionError('libfetch-fragment-target-exact-source')
 changes = (
  (b'    const size_t path = strnlen(url->doc, LSF_FETCH_URL_BYTES + 1);',
   b'    const size_t document = strnlen(url->doc, LSF_FETCH_URL_BYTES + 1);'),
  (b'    if (path > LSF_FETCH_URL_BYTES || host == sizeof(url->host) ||\n        path + host + scheme + 10 > LSF_FETCH_URL_BYTES) {',
   b'    if (document > LSF_FETCH_URL_BYTES || host == sizeof(url->host) ||\n        document + host + scheme + 10 > LSF_FETCH_URL_BYTES) {'),
  (b'', b"    /* A literal fragment is client-side only. Keep encoded %23 and queries\n     * intact, without modifying the caller's original parsed URL. */\n    const char *fragment = memchr(url->doc, '#', document);\n    const size_t path = fragment ? (size_t)(fragment - url->doc) : document;\n"),
  (b'    if (url->port) snprintf(text, path + host + scheme + 11, "%s://%s:%d%s", url->scheme, url->host, url->port, url->doc);\n    else snprintf(text, path + host + scheme + 11, "%s://%s%s", url->scheme, url->host, url->doc);',
   b'    if (url->port) snprintf(text, path + host + scheme + 11, "%s://%s:%d%.*s", url->scheme, url->host, url->port, (int)path, url->doc);\n    else snprintf(text, path + host + scheme + 11, "%s://%s%.*s", url->scheme, url->host, (int)path, url->doc);'),
 )
 for previous, current in reversed(changes):
  if raw.count(current) != 1:
   raise AssertionError('libfetch-fragment-target-exact-addendum')
  raw = raw.replace(current, previous, 1)
 if hashlib.sha256(raw).hexdigest() != 'b3bc3ee9c9299b56f92d8b768da82ca062cd2087796e770d78c7aee53bddb41c':
  raise AssertionError('libfetch-fragment-target-prior-source')
 return raw

def before_unsolicited_partial(raw):
 import hashlib
 raw = before_fragment_target(raw)
 # Reconstruct the exact previously reviewed Range source before applying its
 # historical inverse. Reject partial or unreviewed changes first.
 if hashlib.sha256(raw).hexdigest() != 'b3bc3ee9c9299b56f92d8b768da82ca062cd2087796e770d78c7aee53bddb41c':
  raise AssertionError('libfetch-unsolicited-partial-exact-source')
 changes = (
  (b'                     const char *method, const char *content_type, const char *body) {\n    if ((stat', b'                     const char *method, const char *content_type, const char *body) {\n    const off_t requested_offset = url ? url->offset : 0;\n    if ((stat'),
  (b'(url && (url->offset < 0 || (url->offset > 0 && strcmp(method, "GET")))))', b'(url && (requested_offset < 0 || (requested_offset > 0 && strcmp(method, "GET")))))'),
  (b'    if (url->offset > 0) {\n        int written = snprintf(range_value, sizeof(range_value), "bytes=%lld-", (long long)url->offset);', b'    if (requested_offset > 0) {\n        int written = snprintf(range_value, sizeof(range_value), "bytes=%lld-", (long long)requested_offset);'),
  (b'        valid_range = operation == LATENT_HTTP_STREAMING_METHOD_GET && known_length &&', b'        /* Subtract after ordering to avoid an overflowing range end. */\n        valid_range = operation == LATENT_HTTP_STREAMING_METHOD_GET && requested_offset > 0 && known_length &&'),
  (b'            actual_offset <= url->offset && partial_length == length;', b'            actual_offset <= requested_offset &&\n            (uint64_t)requested_offset - (uint64_t)actual_offset < (uint64_t)partial_length &&\n            partial_length == length;'),
 )
 for previous, current in reversed(changes):
  if raw.count(current) != 1:
   raise AssertionError('libfetch-unsolicited-partial-exact-addendum')
  raw = raw.replace(current, previous, 1)
 if hashlib.sha256(raw).hexdigest() != 'c81b948e74babf3edbc97a25473597daf24cba87ce48abda828f2e753c64185d':
  raise AssertionError('libfetch-unsolicited-partial-prior-source')
 return raw

def before_range(path, raw):
 import hashlib,json
 if path.rsplit('/', 1)[-1] == 'http.c': raw = before_unsolicited_partial(raw)
 elif path.rsplit('/', 1)[-1] == 'UPSTREAM.json': raw = before_head_metadata(path, raw)
 inverse=(ROOT/'tools/tests/fixtures/c-libfetch-range/inverse.json').read_bytes()
 if hashlib.sha256(inverse).hexdigest() != 'fad42989a1ffd18242a5de1e5f8027a0040827e4b392616ee643892de2ddb68c':
  raise AssertionError('libfetch-range-inverse-identity')
 entry=json.loads(inverse)[path.rsplit('/', 1)[-1]]
 if hashlib.sha256(raw).hexdigest() != entry['source_sha256']:
  raise AssertionError('libfetch-range-exact-source')
 lines=raw.decode('utf-8').splitlines(keepends=True)
 previous=len(lines)
 for start,end,original in reversed(entry['hunks']):
  if not 0 <= start <= end <= previous: raise AssertionError('libfetch-range-inverse-order')
  lines[start:end]=original.splitlines(keepends=True)
  previous=start
 result=''.join(lines).encode('utf-8')
 if hashlib.sha256(result).hexdigest() != entry['previous_sha256']:
  raise AssertionError('libfetch-range-prior-source')
 return result

def before_head_stat(path, raw):
 import hashlib
 raw = before_range(path, raw)
 changes = {
  'http.c': ('6d762b7001e35c32582a5a5e7bb3c4be2313ebaa6522d20ae298bd9ce29f6d6f', (
   (b'    if ((stat && strcmp(method, "GET")) || fetchAuthMethod || fetchDebug || fetchTimeout < 0) { unsupported(); return NULL; }',
    b'    if ((stat && strcmp(method, "GET") && strcmp(method, "HEAD")) ||\n        fetchAuthMethod || fetchDebug || fetchTimeout < 0) { unsupported(); return NULL; }'),
   (b'int fetchStatHTTP(struct url *url, struct url_stat *stat, const char *flags) { (void)url; (void)stat; (void)flags; unsupported(); return -1; }',
    b'int fetchStatHTTP(struct url *url, struct url_stat *stat, const char *flags) {\n    struct url_stat result;\n    FILE *file = request(url, stat ? &result : NULL, flags, "HEAD", NULL, NULL);\n    if (!file) return -1;\n    /* The returned body is a real provider owner even for HEAD. Preserve an\n     * abort failure and only publish metadata after it has been closed. */\n    if (fclose(file) != 0) return -1;\n    if (stat) *stat = result;\n    return 0;\n}'))),
  'UPSTREAM.json': ('6b58f1d1838b48f611120d2437b20f2b07614dbc2cb600f5526369d4809b3088', (
   (b'Only optional url_stat on the existing successful HTTP GET. Standalone Stat, range and conditional requests remain unsupported.',
    b'Optional url_stat on successful HTTP GET and standalone Stat via a separately authorized HEAD request. Range and conditional requests remain unsupported.'),)),
 }
 digest, replacements = changes[path.rsplit('/', 1)[-1]]
 if hashlib.sha256(raw).hexdigest() != digest:
  raise AssertionError('libfetch-head-stat-exact-source')
 for original, current in replacements:
  if raw.count(current) != 1: raise AssertionError('libfetch-head-stat-exact-addendum')
  raw = raw.replace(current, original, 1)
 return raw

class CThreadMinimal(unittest.TestCase):
 def test_body_media_inverse_requires_exact_reviewed_source(self):
  import hashlib
  raw=(ROOT/'sdk/c-guest/src/libfetch/http.c').read_bytes()
  self.assertEqual(hashlib.sha256(before_body_media(raw)).hexdigest(),
                   'b757ebb3ec8633b1f792333fef598a10bc6d724cfe340e2d45415ed2385cd96a')
  altered=raw.replace(b'body && content_type ? strnlen', b'body || content_type ? strnlen')
  self.assertNotEqual(altered, raw)
  for candidate in (raw+b'\n', altered):
   with self.assertRaisesRegex(AssertionError, 'libfetch-body-media-exact-source'):
    before_body_media(candidate)

 def test_head_metadata_inverse_requires_exact_reviewed_source(self):
  import hashlib
  raw=(ROOT/'sdk/c-guest/src/libfetch/http.c').read_bytes()
  self.assertEqual(hashlib.sha256(before_head_metadata('http.c', raw)).hexdigest(),
                   '14f71c8141d2170f757b9c78a6b206095cb3d0ad86958de501f5e2a3663bc70e')
  altered=raw.replace(b'value > SIZE_MAX && !head', b'value >= SIZE_MAX && !head')
  self.assertNotEqual(altered, raw)
  for candidate in (raw+b'\n', altered):
   with self.assertRaisesRegex(AssertionError, 'libfetch-body-media-exact-source'):
    before_head_metadata('http.c', candidate)
  metadata=(ROOT/'sdk/c-guest/src/libfetch/UPSTREAM.json').read_bytes()
  self.assertEqual(hashlib.sha256(before_head_metadata('UPSTREAM.json', metadata)).hexdigest(),
                   '5f7795e7318f9e931aa0fef5f8e05368e69d24b26fca22471ec4302bdb245237')

 def test_host_boundary_inverse_requires_exact_reviewed_source(self):
  import hashlib
  raw=(ROOT/'sdk/c-guest/src/libfetch/http.c').read_bytes()
  self.assertEqual(hashlib.sha256(before_host_boundary(raw)).hexdigest(),
                   '1418689760e50035c1bb3cc1979e5170a2cc11fa763a5f87889102e9684b0b03')
  altered=raw.replace(b"memchr(url->host, '?', host)",b"memchr(url->host, 'x', host)")
  self.assertNotEqual(altered, raw)
  for candidate in (raw+b'\n', altered):
   with self.assertRaisesRegex(AssertionError,'libfetch-host-boundary-exact-source'):
    before_host_boundary(candidate)
 def test_http_status_inverse_requires_exact_reviewed_source(self):
  import hashlib
  raw=(ROOT/'sdk/c-guest/src/libfetch/http.c').read_bytes()
  self.assertEqual(hashlib.sha256(before_http_status_categories(raw)).hexdigest(),
                   '906a26d42fad5eb071b02191282f1a3da60a8cfa117782cd125a34f6ad02ab1d')
  altered_category=raw.replace(b'case 503:\n        return FETCH_TEMP;',b'case 503:\n        return FETCH_SERVER;')
  self.assertNotEqual(altered_category, raw)
  for altered in (raw+b'\n', altered_category):
   with self.assertRaisesRegex(AssertionError,'libfetch-host-boundary-exact-source'):
    before_http_status_categories(altered)
 def test_unsolicited_partial_inverse_requires_exact_reviewed_source(self):
  import hashlib
  raw=(ROOT/'sdk/c-guest/src/libfetch/http.c').read_bytes()
  self.assertEqual(hashlib.sha256(before_unsolicited_partial(raw)).hexdigest(),
                   'c81b948e74babf3edbc97a25473597daf24cba87ce48abda828f2e753c64185d')
  for altered in (raw+b'\n',raw.replace(b'requested_offset > 0 && known_length',b'requested_offset >= 0 && known_length'),raw.replace(b'actual_offset < (uint64_t)partial_length',b'actual_offset <= (uint64_t)partial_length')):
   with self.assertRaisesRegex(AssertionError,'libfetch-host-boundary-exact-source'):
    before_unsolicited_partial(altered)
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
   # The outside-client port adds only a trapping process-exit entry. Keep
   # the historical file-ABI pin below after an exact, authenticated inverse.
   closed = 'vendor/lsf/sdk/c-guest/src/closed-file-abi.c'
   self.assertEqual(left[closed], right[closed])
   self.assertEqual(hashlib.sha256(left[closed]).hexdigest(),
                    '8af8989600438fdf5ebe265e3065404f0412270e8dc11b2fee8934de5ba3887f')
   exit_addendum = b'/* Process completion is unsupported: retain original owners through the\n * activation trap and Store cleanup. No atexit callbacks or stdio flushing.\n */\n_Noreturn void exit(int status) {\n    (void)status;\n    __builtin_trap();\n}\n\n'
   self.assertEqual(left[closed].count(exit_addendum), 1)
   for path, expected in current_addendum.items():
    self.assertEqual(left[path], right[path], path)
    # Preserve the original adjacency check and the exact whole-source inverse.
    if path.endswith('/closed-file-abi.c'):
     before = b'static int file_unsupported(void) {\n    errno = ENOTSUP;\n    return -1;\n}\n\n'
     following = b'int open(const char *path, int flags, ...) {\n'
     self.assertEqual(left[path].count(before + EXIT_TRAP_ADDENDUM + following), 1, path)
    # Compare current fixtures first; invert only the reviewed fatal-process addition.
    is_stat = path.endswith('/libfetch/http.c') or path.endswith('/libfetch/UPSTREAM.json')
    preserved = (before_exit_trap(left[path]) if path.endswith('/closed-file-abi.c') else
                 before_head_stat(path, left[path]) if is_stat else left[path])
    self.assertEqual(hashlib.sha256(preserved).hexdigest(), expected, path)
    if path in added_sdk:
     added_sdk[path] = hashlib.sha256(left[path]).hexdigest() if is_stat else expected
    else:
     del left[path]; del right[path]
   for path, expected in added_sdk.items():
    self.assertEqual(left[path], right[path], path)
    self.assertEqual(hashlib.sha256(left[path]).hexdigest(), expected, path)
    del left[path]; del right[path]
   # New SDK files are allowed only when both complete project inventories
   # contain the same paths and identical bytes outside the application main.
   self.assertEqual(set(left),set(right))
   self.assertEqual([n for n in left if left[n]!=right[n]],['src/main.c'])
   self.assertEqual(read_json(a/'capsule-project.json'),read_json(b/'capsule-project.json'))
   self.assertIn(b'greet: async func',right['wit/world.wit'])
  self.assertEqual(selected.MODES,('application-error','minimal-c11','minimal-pthread','c11','pthread'))
 def test_file_abi_addendum_refuses_missing_duplicate_modified_and_unrelated_source_drift(self):
  raw = (ROOT/'sdk/c-guest/src/closed-file-abi.c').read_bytes()
  self.assertEqual(raw.count(EXIT_TRAP_ADDENDUM), 1)
  self.assertEqual(before_exit_trap(raw), raw.replace(EXIT_TRAP_ADDENDUM, b'', 1))
  changed = {
   'missing': raw.replace(EXIT_TRAP_ADDENDUM, b'', 1),
   'duplicate': raw.replace(EXIT_TRAP_ADDENDUM, EXIT_TRAP_ADDENDUM*2, 1),
   'changed-trap': raw.replace(b'    __builtin_trap();', b'    abort();', 1),
   'changed-file-errno': raw.replace(b'errno = ENOTSUP;', b'errno = EIO;', 1),
   'extra-source': raw + b'\n',
  }
  for label, altered in changed.items():
   with self.subTest(label=label):
    self.assertNotEqual(altered, raw)
    with self.assertRaisesRegex(AssertionError, 'closed-file-exact-exit-trap-source'):
     before_exit_trap(altered)
if __name__=='__main__':unittest.main()
