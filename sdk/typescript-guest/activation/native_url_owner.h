// Exact native parser backing graphs; finalizers acknowledge no host token.
#pragma once
#include "native_objects.h"
#include "rust-url.h"

namespace lsf::typescript::activation {
struct UrlDelete {
  void operator()(jsurl::JSUrl* value) const { jsurl::free_jsurl(value); }
};
struct ParamsDelete {
  void operator()(jsurl::JSUrlSearchParams* value) const { jsurl::free_params(value); }
};
struct UrlGraph {
  NativeObjectLease params_lease; // freed after the URL and its linked params
  bool params_admitted = false;
  std::unique_ptr<jsurl::JSUrl, UrlDelete> value;
};
using NativeUrl = NativeContainer<UrlGraph>;
using NativeParams = NativeContainer<std::unique_ptr<jsurl::JSUrlSearchParams, ParamsDelete>>;
} // namespace lsf::typescript::activation
