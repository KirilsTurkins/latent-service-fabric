// Native embedding ABI for the exact opt-in SpiderMonkey source derivation.
// Intrinsic allocation/settlement invoke these hooks; maintained weak-GC APIs
// observe object retirement without changing the original object/class ABI.
// Application Promise constructors and Promise.prototype.then remain original.
#pragma once
#include "js/TypeDecls.h"
#include "js/RootingAPI.h"

namespace JS {
struct ActivationPromiseHooks {
  // Reserve the original native owner before any Promise/object metadata
  // allocation. A refusal sets an exception and admits no Promise object.
  bool (*beforeAllocate)(JSContext*, void** record);
  void (*allocationFailed)(void* record);
  void (*created)(JSContext*, JSObject*, void* record);
  void (*settled)(JSContext*, JSObject*);
  // Pending reactions retain captures even if no job is yet executable. Their
  // task/queue/native ownership is reserved before the intrinsic record exists.
  bool (*beforeReactionAllocate)(JSContext*, void** record);
  void (*reactionAllocationFailed)(void* record);
  void (*reactionCreated)(JSContext*, JSObject*, void* record);
  void* (*reactionRecord)(JSContext*, JSObject*);
  // Thenable resolution uses original native job functions instead of a
  // pending reaction object. Reserve their captured-frame owners before the
  // function is allocated, with the same weak-GC/collection-end discipline.
  bool (*beforeNativeJobAllocate)(JSContext*, void** record);
  void (*nativeJobAllocationFailed)(void* record);
  void (*nativeJobCreated)(JSContext*, JSObject*, void* record);
  void* (*nativeJobRecord)(JSContext*, JSObject*);
};

// The embedding installs this once before content evaluation. Its lifetime
// covers the JSContext and its GC; it is never application-configurable.
extern JS_PUBLIC_API bool SetActivationPromiseHooks(
    JSContext*, const ActivationPromiseHooks*);
// Read only the private record on an original intrinsic reaction-job closure.
// A null result identifies another native job; no application property is read.
extern JS_PUBLIC_API bool ActivationReactionRecordForJob(
    JSContext*, HandleObject, void** record);
} // namespace JS
