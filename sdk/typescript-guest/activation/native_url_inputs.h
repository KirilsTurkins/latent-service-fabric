// Closed variable backing capacity, independent of the Native64 object charge.
#pragma once
#include "encode.h"
#include "native_url_owner.h"
#include "rust-url.h"
#include "js/CharacterEncoding.h"
#include "js/String.h"
#include <memory>

namespace lsf::typescript::activation {
inline constexpr size_t URL_INPUT_BYTES = 8192;
inline constexpr size_t URL_QUERY_PAIRS = 256;

struct UrlInput : jsurl::SpecString {
  UrlInput() : jsurl::SpecString(nullptr, 0, 0) {}
  explicit UrlInput(jsurl::SpecString input) : jsurl::SpecString(input) {}
  UrlInput(const UrlInput&) = delete;
  UrlInput(UrlInput&& input) : jsurl::SpecString(input) { input.data = nullptr; }
  ~UrlInput() { if (data) js_free(data); }
  jsurl::SpecString release() {
    auto output = static_cast<jsurl::SpecString>(*this);
    data = nullptr;
    return output; // Only actual by-value Rust transfer owns this input now.
  }
};

inline UrlInput url_input(JSContext* cx, JS::HandleValue input) {
  JS::RootedString text(cx, JS::ToString(cx, input));
  if (!text) return {};
  // Reject before linearizing or allocating the UTF-8/native parser buffer.
  if (JS_GetStringLength(text) > URL_INPUT_BYTES) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-input-byte-limit"); return {};
  }
  auto* linear = JS_EnsureLinearString(cx, text);
  if (!linear) return {};
  if (JS::GetDeflatedUTF8StringLength(linear) > URL_INPUT_BYTES) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-input-byte-limit"); return {};
  }
  JS::RootedValue converted(cx, JS::StringValue(text));
  return UrlInput(core::encode_spec_string(cx, converted));
}

inline bool url_query_bound(JSContext* cx, const uint8_t* data, size_t length) {
  size_t pairs = length ? 1 : 0;
  for (size_t index = 0; index < length; ++index) if (data[index] == '&') ++pairs;
  if (pairs > URL_QUERY_PAIRS) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-query-pair-limit"); return false;
  }
  return true;
}

inline bool url_params_growth(JSContext* cx, jsurl::JSUrlSearchParams* params,
                              size_t name, size_t value, jsurl::JSUrl* parent) {
  const size_t current = jsurl::params_to_string(params).len;
  // Form encoding expands each UTF-8 byte by at most three. Preflight the
  // complete retained representation before either Rust vector/string grows.
  if (jsurl::params_size(params) >= URL_QUERY_PAIRS || current > URL_INPUT_BYTES ||
      name > URL_INPUT_BYTES / 3 || value > URL_INPUT_BYTES / 3 ||
      3 * (name + value) + 2 > URL_INPUT_BYTES - current) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-query-growth-limit"); return false;
  }
  const size_t maximum_query = current + 3 * (name + value) + 2;
  if (parent) {
    const size_t base = jsurl::href(parent).len - jsurl::search(parent).len;
    if (base >= URL_INPUT_BYTES || maximum_query + 1 > URL_INPUT_BYTES - base) {
      JS_ReportErrorASCII(cx, "fetch-profile-URL-linked-query-growth-limit"); return false;
    }
  }
  return true;
}

inline bool url_params_normalization(JSContext* cx, jsurl::JSUrlSearchParams* params,
                                     jsurl::JSUrl* parent) {
  // Existing decoded entries are already bounded. This owned parser cache is
  // at most their admitted form representation; it is not an FFI allocation.
  const size_t query = jsurl::params_to_string(params).len;
  if (query > URL_INPUT_BYTES || jsurl::params_size(params) > URL_QUERY_PAIRS) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-query-growth-limit"); return false;
  }
  if (parent) {
    const size_t base = jsurl::href(parent).len - jsurl::search(parent).len;
    // sort/delete may change raw query spelling to form encoding even when
    // pair count decreases. Refuse that expansion before changing either view.
    if (base >= URL_INPUT_BYTES || query + 1 > URL_INPUT_BYTES - base) {
      JS_ReportErrorASCII(cx, "fetch-profile-URL-linked-query-growth-limit"); return false;
    }
  }
  return true;
}

inline bool url_backing_bound(JSContext* cx, jsurl::JSUrl* value) {
  const auto href = jsurl::href(value);
  const auto query = jsurl::search(value);
  if (href.len > URL_INPUT_BYTES) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-backing-byte-limit"); return false;
  }
  // Linked form serialization may encode each retained query byte three times.
  // Bound it before constructing its lazy Rust vector/cache, on every URL path.
  if (query.len > URL_INPUT_BYTES / 3) {
    JS_ReportErrorASCII(cx, "fetch-profile-URL-query-growth-limit"); return false;
  }
  return url_query_bound(cx, query.data, query.len);
}

inline bool url_mutate(JSContext* cx, jsurl::JSUrl* value, const jsurl::SpecString* input,
                      void (*mutate)(jsurl::JSUrl*, const jsurl::SpecString*), bool whole_href) {
  auto shadow = make_native_container<UrlGraph>(cx);
  if (!shadow) return false;
  if (whole_href) {
    shadow->value.value.reset(jsurl::new_jsurl(input));
  } else {
    auto href = jsurl::href(value);
    jsurl::SpecString original(const_cast<uint8_t*>(href.data), href.len, 0);
    shadow->value.value.reset(jsurl::new_jsurl(&original));
    if (shadow->value.value) mutate(shadow->value.value.get(), input);
  }
  if (!shadow->value.value) {
    JS_ReportErrorASCII(cx, "URL-setter-invalid-URL"); return false;
  }
  // Parse/mutate only the bounded temporary graph first. A rejected byte/pair
  // expansion cannot alter the original or its linked params representation.
  if (!url_backing_bound(cx, shadow->value.value.get())) return false;
  mutate(value, input);
  return true;
}
} // namespace lsf::typescript::activation
