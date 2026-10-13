// Bounded selected Abort/Event graphs, admitted before native allocation.
#pragma once
#include "promise_records.h"
#include "native_retirement.h"
#include <utility>

namespace lsf::typescript::activation {
using NativeObjectRecords = NativeRetirement<NativeOwner>;

// A lease is the first data member of its graph wrapper. Its destructor runs
// after callback strings/vectors/weak sets and merely records physical death.
using NativeObjectLease = NativeLease<NativeObjectRecords>;

bool admit_native_object(JSContext*, NativeObjectLease&);

template<class T> using NativeContainer = OwnedNativeContainer<NativeObjectRecords,T>;

template<class T> std::unique_ptr<NativeContainer<T>> make_native_container(JSContext* cx) {
  NativeObjectLease lease;
  if (!admit_native_object(cx, lease)) return nullptr;
  auto output = std::unique_ptr<NativeContainer<T>>(
      new (std::nothrow) NativeContainer<T>(std::move(lease)));
  if (!output) JS_ReportOutOfMemory(cx);
  return output;
}
} // namespace lsf::typescript::activation
