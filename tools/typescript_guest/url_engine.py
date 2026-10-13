"""Exact maintained pure URL derivation; no Blob/worker/random/HTTP owner."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once

CPP = 'StarlingMonkey/builtins/web/url.cpp'
HEADER = 'StarlingMonkey/builtins/web/url.h'
RUST_HEADER = 'StarlingMonkey/crates/rust-url/rust-url.h'
RUST = 'StarlingMonkey/crates/rust-url/src/lib.rs'
PREIMAGES = {CPP: '54fb313fd2f84d34fd5d1edc7a4eb8e5c39fbf4e81fac3b0408efba21afb3d01',
             HEADER: 'f0ac8e6d76a6f04abec33b71c2b5fa9e4e9aa92818f487150c2561c0d367e810',
             RUST_HEADER: '98f2a64bfb98a9963001906be2823eae8132b8bc3b77f7b99157fe0d572f8c0c',
             RUST: '636538d53710dd506d3cba59a3157cc8f728d7e20ffe2d49dce690441405b380'}


def derive(original: dict[str, bytes], owner: bytes) -> tuple[dict[str, bytes], dict]:
    if set(original) != set(PREIMAGES) or not owner:
        raise ValueError('exact-maintained-URL-source-required')
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError('unreviewed-maintained-URL-source:' + name)
    header = original[HEADER]
    header = replace_once(header, b'BuiltinNoConstructor<URLSearchParams>',
        b'BuiltinImpl<URLSearchParams, FinalizableClassPolicy>', 'params-finalizable-native-owner')
    header = replace_once(header, b'class_name = "URLSearchParams";\n\n  enum class Slots : uint8_t { Url, Params, Count };',
        b'class_name = "URLSearchParams";\n\n  enum class Slots : uint8_t { Url, Params, Owner, Parent, Count };', 'params-owner-and-strong-parent')
    header = replace_once(header, b'  static bool constructor(JSContext *cx, unsigned argc, JS::Value *vp);\n};',
        b'  static bool constructor(JSContext *cx, unsigned argc, JS::Value *vp);\n'
        b'  static void finalize(JS::GCContext *gcx, JSObject *self);\n};', 'params-finalizer-declaration')
    header = replace_once(header, b'JS::HandleObject self, jsurl::JSUrl *url);',
        b'JS::HandleObject self, jsurl::JSUrl *url, JS::HandleObject parent);', 'params-linked-parent-argument')
    header = replace_once(header, b'class_name = "URL";\n\n  enum class Slots : uint8_t { Url, Params, Count };',
        b'class_name = "URL";\n\n  enum class Slots : uint8_t { Url, Params, Owner, Count };', 'URL-owner-slot')
    header = replace_once(header, b'  static JSObject *getObjectURL(std::string &url);\n', b'', 'no-object-URL-store-API')
    for name in ('URL', 'URLSearchParams', 'URLSearchParamsIterator'):
        anchor = f'  static constexpr const char *class_name = "{name}";\n'.encode()
        header = replace_once(header, anchor, anchor +
            b'  static bool is_instance(const JSObject* object);\n'
            b'  static bool is_instance(JS::Value value);\n', 'native-parser-brand:' + name)

    source = original[CPP]
    for include in (b'#include "blob.h"\n', b'#include "file.h"\n',
                    b'#include "worker-location.h"\n', b'#include "crypto/uuid.h"\n'):
        source = replace_once(source, include, b'', 'pure-URL-unselected-include')
    source = replace_once(source, b'#include "url.h"\n',
        b'#include "url.h"\n#include "native_url_owner.h"\n#include "native_url_inputs.h"\n', 'native-URL-owner-header')
    source = replace_once(source, b'using blob::Blob;\nusing file::File;\nusing worker_location::WorkerLocation;\n',
        b'''using lsf::typescript::activation::NativeUrl;
using lsf::typescript::activation::NativeParams;
using lsf::typescript::activation::UrlGraph;
using lsf::typescript::activation::make_native_container;
using lsf::typescript::activation::admit_native_object;
using lsf::typescript::activation::UrlInput;
using lsf::typescript::activation::url_input;
using lsf::typescript::activation::url_query_bound;
using lsf::typescript::activation::url_params_growth;
using lsf::typescript::activation::url_params_normalization;
using lsf::typescript::activation::url_backing_bound;
using lsf::typescript::activation::url_mutate;

namespace {
NativeUrl* native_url(JSObject* self) {
  auto value = JS::GetReservedSlot(self, std::to_underlying(URL::Slots::Owner));
  return value.isUndefined() ? nullptr : static_cast<NativeUrl*>(value.toPrivate());
}
}
''', 'pure-parser-owner-types')
    branded = b''
    for name, slot in (('URL', 'Owner'), ('URLSearchParams', 'Params')):
        branded += f'''bool {name}::is_instance(const JSObject* object) {{
  if (!object || JS::GetClass(object) != &class_) return false;
  auto backing = JS::GetReservedSlot(const_cast<JSObject*>(object), std::to_underlying(Slots::{slot}));
  return !backing.isUndefined() && backing.toPrivate() != nullptr;
}}
bool {name}::is_instance(JS::Value value) {{
  return value.isObject() && is_instance(&value.toObject());
}}

'''.encode()
    branded += b'''bool URLSearchParamsIterator::is_instance(const JSObject* object) {
  return object && JS::GetClass(object) == &class_ &&
      JS::GetReservedSlot(const_cast<JSObject*>(object), std::to_underlying(Slots::Params)).isObject();
}
bool URLSearchParamsIterator::is_instance(JS::Value value) {
  return value.isObject() && is_instance(&value.toObject());
}

'''
    source = replace_once(source, b'bool URLSearchParamsIterator::next(', branded + b'bool URLSearchParamsIterator::next(',
                          'native-parser-receiver-before-private-slot-access')
    start = source.index(b'static PersistentRooted<JS::GCHashMap<UrlKey,')
    end = source.index(b'const jsurl::JSUrl *URL::url(', start)
    source = source[:start] + b'''bool URL::createObjectURL(JSContext* cx, unsigned, JS::Value*) {
  JS_ReportErrorASCII(cx, "fetch-profile-object-URL-not-supported");
  return false;
}
bool URL::revokeObjectURL(JSContext* cx, unsigned, JS::Value*) {
  JS_ReportErrorASCII(cx, "fetch-profile-object-URL-not-supported");
  return false;
}

''' + source[end:]
    source = replace_once(source, b'  URL_STORE.init(cx);\n', b'', 'no-object-URL-store-initialization')
    source = replace_once(source, b'''  auto *params = jsurl::new_params();
  JS::SetReservedSlot(self, std::to_underlying(Slots::Params), JS::PrivateValue(params));''',
        b'''  auto owner = make_native_container<std::unique_ptr<jsurl::JSUrlSearchParams,
      lsf::typescript::activation::ParamsDelete>>(cx);
  if (!owner) return nullptr;
  owner->value.reset(jsurl::new_params());
  auto* params = owner->value.get();
  if (!params) { JS_ReportOutOfMemory(cx); return nullptr; }
  JS::SetReservedSlot(self, std::to_underlying(Slots::Owner), JS::PrivateValue(owner.release()));
  JS::SetReservedSlot(self, std::to_underlying(Slots::Params), JS::PrivateValue(params));''', 'standalone-params-affine-owner')
    source = replace_once(source, b'JS::HandleObject self, jsurl::JSUrl *url) {\n\n  jsurl::JSUrlSearchParams *params = jsurl::url_search_params(url);',
        b'''JS::HandleObject self, jsurl::JSUrl *url, JS::HandleObject parent) {
  auto* owner = native_url(parent);
  if (!owner) { JS_ReportErrorASCII(cx, "URL-native-parent-owner-required"); return nullptr; }
  // The Rust linked box is destroyed by its URL graph, not its JS alias.
  // Keep this additional real allocation charged until that actual destruction.
  if (!owner->value.params_admitted) {
    if (!admit_native_object(cx, owner->value.params_lease)) return nullptr;
    owner->value.params_admitted = true;
  }
  jsurl::JSUrlSearchParams *params = jsurl::url_search_params(url);''', 'linked-params-admit-before-allocation')
    source = replace_once(source, b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Params), JS::PrivateValue(params));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));\n\n  return self;\n}',
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Params), JS::PrivateValue(params));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Parent), JS::ObjectValue(*parent));\n\n'
        b'  return self;\n}', 'linked-params-strong-JS-parent')
    source = replace_once(source, b'params = URLSearchParams::create(cx, url_search_params_instance, url_mut(self));',
        b'params = URLSearchParams::create(cx, url_search_params_instance, url_mut(self), self);', 'linked-params-parent-call')
    source = replace_once(source, b'''  JS::RootedObject urlSearchParamsInstance(cx, JS_NewObjectForConstructor(cx, &class_, args));
  JS::RootedObject self(cx, create(cx, urlSearchParamsInstance, args.get(0)));''',
        b'''  JS::RootedObject urlSearchParamsInstance(cx, JS_NewObjectForConstructor(cx, &class_, args));
  if (!urlSearchParamsInstance) return false;
  JS::RootedValue initial(cx, args.get(0));
  if (initial.isUndefined()) initial.setString(JS_GetEmptyString(cx));
  JS::RootedObject self(cx, create(cx, urlSearchParamsInstance, initial));''', 'params-default-and-constructor-failure')
    source = replace_once(source, b'bool URLSearchParams::init_class(JSContext *cx, JS::HandleObject global) {',
        b'''void URLSearchParams::finalize(JS::GCContext*, JSObject* self) {
  auto owner = JS::GetReservedSlot(self, std::to_underlying(Slots::Owner));
  if (!owner.isUndefined()) delete static_cast<NativeParams*>(owner.toPrivate());
}

bool URLSearchParams::init_class(JSContext *cx, JS::HandleObject global) {''', 'params-physical-finalizer')
    source = replace_once(source, b'''  jsurl::JSUrl *url = nullptr;
  if (base) {
    url = jsurl::new_jsurl_with_base(&url_str, base);
  } else {
    url = jsurl::new_jsurl(&url_str);
  }

  if (!url) {''', b'''  auto owner = make_native_container<UrlGraph>(cx);
  if (!owner) return nullptr;
  owner->value.value.reset(base ? jsurl::new_jsurl_with_base(&url_str, base)
                               : jsurl::new_jsurl(&url_str));
  auto* url = owner->value.value.get();
  if (!url) {''', 'URL-affine-parser-owner')
    source = replace_once(source, b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));\n\n  return self;\n}',
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Owner), JS::PrivateValue(owner.release()));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));\n\n'
        b'  return self;\n}', 'URL-owning-slot-after-success')
    old = b'''  auto *url =
      static_cast<jsurl::JSUrl *>(JS::GetReservedSlot(self, std::to_underlying(Slots::Url)).toPrivate());
  jsurl::free_jsurl(url);'''
    source = replace_once(source, old, b'  delete native_url(self);', 'URL-real-graph-destruction-before-lease')
    source = replace_once(source, b'''  jsurl::JSUrl *base = nullptr;

  if (!base_val.isUndefined()) {''',
        b'''  jsurl::JSUrl *base = nullptr;
  std::unique_ptr<NativeUrl> base_owner;
  if (!base_val.isUndefined()) {''', 'temporary-base-affine-owner')
    source = replace_once(source, b'    base = jsurl::new_jsurl(&str);\n',
        b'''    base_owner = make_native_container<UrlGraph>(cx);
    if (!base_owner) return nullptr;
    base_owner->value.value.reset(jsurl::new_jsurl(&str));
    base = base_owner->value.value.get();
''', 'temporary-base-admit-before-parser')
    source = source.replace(b'core::encode_spec_string(', b'url_input(')
    source = replace_once(source, b'jsurl::SpecString validate(', b'UrlInput validate(', 'owned-validated-parameter-input')
    source = source.replace(b'jsurl::SpecString key', b'UrlInput key')
    key_conversion = b'  auto *const params = URLSearchParams::get_params(self);\n\n  auto value = url_input(cx, val);'
    if source.count(key_conversion) != 2:
        raise ValueError('pinned-URL-append-and-set-conversion-shape')
    source = source.replace(key_conversion,
        b'  auto *const params = URLSearchParams::get_params(self);\n  if (!key.data) return false;\n\n  auto value = url_input(cx, val);')
    source = replace_once(source, b'maybe_consume_sequence_or_record<jsurl::SpecString,',
        b'maybe_consume_sequence_or_record<UrlInput,', 'owned-sequence-conversion-input')
    source = replace_once(source, b'append_impl(cx, self, value,', b'append_impl(cx, self, std::move(value),',
        'move-owned-append-key')
    for function in ('append', 'set'):
        source = replace_once(source, f'  jsurl::params_{function}(params, key, value);'.encode(),
            (f'  auto linked = JS::GetReservedSlot(self, std::to_underlying(URLSearchParams::Slots::Url));\n'
             f'  if (!key.data || !url_params_growth(cx, params, key.len, value.len, linked.isUndefined() ? nullptr : static_cast<jsurl::JSUrl*>(linked.toPrivate()))) return false;\n'
             f'  jsurl::params_{function}(params, key.release(), value.release());').encode(),
            'transfer-only-after-bounded-' + function)
    source = replace_once(source, b'  jsurl::params_set(params, name, value);',
        b'  auto linked = JS::GetReservedSlot(self, std::to_underlying(URLSearchParams::Slots::Url));\n'
        b'  if (!url_params_growth(cx, params, name.len, value.len, linked.isUndefined() ? nullptr : static_cast<jsurl::JSUrl*>(linked.toPrivate()))) return false;\n'
        b'  jsurl::params_set(params, name.release(), value.release());', 'bounded-direct-set-transfer')
    for function in ('delete', 'delete_kv'):
        call = (b'    jsurl::params_delete(params, &name);' if function == 'delete' else
                b'    jsurl::params_delete_kv(params, &name, &value);')
        source = replace_once(source, call,
            b'    auto linked = JS::GetReservedSlot(self, std::to_underlying(Slots::Url));\n'
            b'    if (!url_params_normalization(cx, params, linked.isUndefined() ? nullptr : static_cast<jsurl::JSUrl*>(linked.toPrivate()))) return false;\n' + call,
            'bounded-normalization-before-' + function)
    source = replace_once(source, b'  jsurl::params_sort(params);',
        b'  auto linked = JS::GetReservedSlot(self, std::to_underlying(Slots::Url));\n'
        b'  if (!url_params_normalization(cx, params, linked.isUndefined() ? nullptr : static_cast<jsurl::JSUrl*>(linked.toPrivate()))) return false;\n'
        b'  jsurl::params_sort(params);', 'bounded-normalization-before-sort')
    source = replace_once(source, b'    jsurl::params_init(params, &init);',
        b'    if (init.len > lsf::typescript::activation::URL_INPUT_BYTES / 3) {\n'
        b'      JS_ReportErrorASCII(cx, "fetch-profile-URL-query-growth-limit"); return nullptr;\n    }\n'
        b'    if (!url_query_bound(cx, init.data, init.len)) return nullptr;\n'
        b'    jsurl::params_init(params, &init);', 'constructor-query-pair-preflight')
    source = replace_once(source, b'  jsurl::JSUrlSearchParams *params = jsurl::url_search_params(url);',
        b'  if (!url_backing_bound(cx, url)) return nullptr;\n'
        b'  jsurl::JSUrlSearchParams *params = jsurl::url_search_params(url);', 'linked-query-capacity-before-expansion')
    source = replace_once(source, b'    jsurl::SpecString str = url_input(', b'    auto str = url_input(',
        'retain-borrowed-setter-input-owner')
    source = replace_once(source, b'''  const jsurl::CVec<jsurl::SpecSlice> values = jsurl::params_get_all(params, &name);

  JS::RootedObject result(cx, JS::NewArrayObject(cx, values.len));''',
        b'''  // Borrow each maintained parser entry; the old allocating CVec has no
  // destructor in this FFI. No native temporary survives the JS copies.
  JS::RootedObject result(cx, JS::NewArrayObject(cx, 0));''', 'get-all-no-unowned-FFI-vector')
    source = replace_once(source, b'''  for (size_t i = 0; i < values.len; i++) {
    const jsurl::SpecSlice value = values.ptr[i];''',
        b'''  size_t output = 0;
  for (size_t i = 0; i < jsurl::params_size(const_cast<jsurl::JSUrlSearchParams*>(params)); i++) {
    jsurl::JSSearchParam entry;
    jsurl::params_at(params, i, &entry);
    if (entry.done || entry.name.len != name.len ||
        (name.len && std::memcmp(entry.name.data, name.data, name.len))) continue;
    const jsurl::SpecSlice value = entry.value;''', 'get-all-borrowed-parser-enumeration')
    source = replace_once(source, b'    if (!JS_SetElement(cx, result, i, str_val)) {',
        b'    if (!JS_SetElement(cx, result, output++, str_val)) {', 'get-all-dense-matching-elements')
    source = replace_once(source, b'  jsurl::SpecString slice = origin(cx, self);',
        b'''  jsurl::SpecString slice = origin(cx, self);
  struct OwnedOrigin {
    jsurl::SpecString value;
    ~OwnedOrigin() { jsurl::free_spec_string(value); }
  } owned{slice};''', 'origin-actual-Rust-destructor-on-every-exit')
    source = replace_once(source, b'    jsurl::set_##field(url, &str);',
        b'    if (!url_mutate(cx, url, &str, jsurl::set_##field, std::string_view(#field) == "href")) return false;',
        'bounded-shadow-setter-before-real-mutation')
    source = replace_once(source, b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Owner), JS::PrivateValue(owner.release()));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));',
        b'  if (!url_backing_bound(cx, url)) return nullptr;\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Owner), JS::PrivateValue(owner.release()));\n'
        b'  JS::SetReservedSlot(self, std::to_underlying(Slots::Url), JS::PrivateValue(url));', 'bounded-normalized-URL-before-exposure')
    source = replace_once(source, b'    base = base_owner->value.value.get();\n',
        b'    base = base_owner->value.value.get();\n'
        b'    if (base && !url_backing_bound(cx, base)) return nullptr;\n', 'bounded-temporary-base')
    destructor = b'''
// Return ownership to the same Rust String destructor that created this FFI
// value. The C++ caller cannot infer Rust's allocator from pointer/capacity.
#[no_mangle]
pub extern "C" fn free_spec_string(value: SpecString) {
    drop(value);
}
'''
    rust = replace_once(original[RUST], b'/// This type exists to transfer &str-likes over FFI.',
        destructor + b'\n/// This type exists to transfer &str-likes over FFI.', 'exact-Rust-String-owner-drop')
    rust_header = replace_once(original[RUST_HEADER], b'SpecSlice params_to_string(const JSUrlSearchParams *params);',
        b'SpecSlice params_to_string(const JSUrlSearchParams *params);\n\nvoid free_spec_string(SpecString value);',
        'generated-additive-String-destructor-declaration')
    result = {CPP: source, HEADER: header, RUST: rust, RUST_HEADER: rust_header,
              'lsf/native_url_owner.h': owner}
    return result, {'profile': 'spidermonkey-activation-promises-clocks-fetch-v1',
        'originalSource': identity(original), 'derivedSource': identity(result),
        'ordinaryImportProfileChanged': False, 'objectURLSupported': False,
        'BlobFileWorkerRandomSelected': False, 'originalNativeObjectCeiling': 64,
        'acknowledgementOutsideGCRequired': True, 'qualification': 'unknown',
        'maximumURLInputAndBackingBytes': 8192, 'maximumQueryPairs': 256,
        'signedLSFComponentQualified': False}
