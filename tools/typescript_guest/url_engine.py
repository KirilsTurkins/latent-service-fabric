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
        b'#include "url.h"\n#include "native_url_owner.h"\n', 'native-URL-owner-header')
    source = replace_once(source, b'using blob::Blob;\nusing file::File;\nusing worker_location::WorkerLocation;\n',
        b'''using lsf::typescript::activation::NativeUrl;
using lsf::typescript::activation::NativeParams;
using lsf::typescript::activation::UrlGraph;
using lsf::typescript::activation::make_native_container;
using lsf::typescript::activation::admit_native_object;

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
    result = {CPP: source, HEADER: header, 'lsf/native_url_owner.h': owner}
    return result, {'profile': 'spidermonkey-activation-promises-clocks-fetch-v1',
        'originalSource': identity(original), 'derivedSource': identity(result),
        'ordinaryImportProfileChanged': False, 'objectURLSupported': False,
        'BlobFileWorkerRandomSelected': False, 'originalNativeObjectCeiling': 64,
        'acknowledgementOutsideGCRequired': True, 'qualification': 'unknown',
        'signedLSFComponentQualified': False}
