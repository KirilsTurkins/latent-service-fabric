// Finite collection model executing emitted constructors and production leases.
// This is not SpiderMonkey, an LSF broker, or signed-component qualification.
#include "native_retirement.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <type_traits>
#include <vector>

namespace std {
template<class E> constexpr underlying_type_t<E> to_underlying(E value) {
  return static_cast<underlying_type_t<E>>(value);
}
}
struct JSContext { const char* error = nullptr; };
struct Value {
  void* pointer = nullptr;
  bool isNullOrUndefined() const { return !pointer; }
  void* toPrivate() const { return pointer; }
};
struct JSObject {
  std::array<Value, 8> slots{};
  bool abort = false, reachable = true;
};
using HandleObject = JSObject*;
struct RootedObject {
  JSObject* object;
  RootedObject(JSContext*, JSObject* value) : object(value) {}
  operator JSObject*() const { return object; }
};
static bool initialized = true, in_gc = false, host_in_gc = false;
static bool finish_collection = true, refuse_ack = false;
static unsigned collections = 0, allocations = 0, bodies = 0, prepared = 0;
static std::vector<std::unique_ptr<JSObject>> objects;
bool JS_IsExceptionPending(JSContext* cx) { return cx->error != nullptr; }
void JS_ReportErrorASCII(JSContext* cx, const char* value) { cx->error = value; }
void JS_ReportOutOfMemory(JSContext* cx) { cx->error = "oom"; }
static bool effects_allowed(JSContext*) { return initialized; }
namespace JS {
struct GCContext {};
enum class GCOptions { Normal };
enum class GCReason { API };
Value UndefinedValue() { return {}; }
Value NullValue() { return {}; }
Value FalseValue() { return {}; }
Value PrivateValue(void* value) { return {value}; }
Value GetReservedSlot(JSObject* object, size_t slot) { return object->slots.at(slot); }
void SetReservedSlot(JSObject* object, size_t slot, Value value) { object->slots.at(slot) = value; }
void PrepareForFullGC(JSContext*) { ++prepared; }
void NonIncrementalGC(JSContext*, GCOptions, GCReason);
}
using JS::SetReservedSlot;
#define MOZ_ASSERT(value) assert(value)
JSObject* JS_NewObjectWithGivenProto(JSContext*, const int* kind, int) {
  ++allocations;
  auto object = std::make_unique<JSObject>();
  object->abort = *kind == 1;
  auto* result = object.get();
  objects.push_back(std::move(object));
  return result;
}
namespace lsf::typescript::activation {
struct NativeOwner { unsigned id = 0; bool live = false; };
using NativeObjectRecords = NativeRetirement<NativeOwner>;
using NativeObjectLease = NativeLease<NativeObjectRecords>;
NativeObjectRecords native_objects;
struct Accounting {
  unsigned live = 0, limit = 64, next = 0, acknowledged = 0;
  std::array<bool, 2048> tokens{};
  bool beforeAllocate(JSContext* cx, NativeOwner& owner) {
    host_in_gc |= in_gc;
    if (live == limit) { cx->error = "native-register-denied"; return false; }
    assert(!owner.live && next + 1 < tokens.size());
    owner = {++next, true}; tokens[next] = true; ++live;
    return true;
  }
  bool acknowledge(JSContext* cx, NativeOwner& owner) {
    host_in_gc |= in_gc;
    assert(owner.live && tokens[owner.id] && live);
    if (refuse_ack) { cx->error = "native-settle-denied"; return false; }
    tokens[owner.id] = false; owner.live = false; --live; ++acknowledged;
    return true;
  }
  unsigned liveNative() const { return live; }
} promise_accounting;
bool acknowledge_promise_retirement(JSContext* cx) {
  return native_objects.checkpoint([cx](NativeOwner& owner) {
    return promise_accounting.acknowledge(cx, owner);
  });
}
// INSERT_PRESSURE_HELPER
// INSERT_COLLECTION_BOUNDARY
// INSERT_PREPARE_BOUNDARY
// INSERT_ADMISSION
// INSERT_CONTAINER_FACTORY
}
namespace native = lsf::typescript::activation;
struct Body {
  Body() { ++bodies; }
  ~Body() { --bodies; }
};
struct WeakIndexSet : Body { void init(JSContext*) {} };
using AlgorithmList = Body;
using ListenerList = Body;
using OwnedAlgorithmList = native::NativeContainer<AlgorithmList>;
using OwnedWeakSet = native::NativeContainer<WeakIndexSet>;
using OwnedListenerList = native::NativeContainer<ListenerList>;
struct EventTarget {
  enum class Slots { Listeners };
  static constexpr int class_ = 0, proto_obj = 0;
  static bool is_instance(JSObject* value) { return value != nullptr; }
  static JSObject* create(JSContext*);
  static bool init(JSContext*, HandleObject);
  static void finalize(JS::GCContext*, JSObject*);
};
struct AbortSignal {
  enum class Slots { Listeners, Reason, Algorithms, Dependent, SourceSignals, DependentSignals, OnAbort, OnAbortListener };
  static constexpr int class_ = 1, proto_obj = 0;
  static bool is_instance(JSObject* value) { return value && value->abort; }
  static JSObject* create(JSContext*);
  static void finalize(JS::GCContext*, JSObject*);
};
// INSERT_CONSTRUCTORS
// INSERT_FINALIZERS
void JS::NonIncrementalGC(JSContext*, GCOptions, GCReason) {
  assert(!in_gc); in_gc = true; ++collections;
  for (auto& object : objects) {
    if (!object || object->reachable) continue;
    if (object->abort) AbortSignal::finalize(nullptr, object.get());
    else EventTarget::finalize(nullptr, object.get());
    object.reset();
  }
  if (finish_collection) native::native_objects.collectionCompleted();
  in_gc = false;
}
static bool make_graphs(JSContext* cx, unsigned count, bool reachable) {
  for (unsigned i = 0; i < count; ++i) {
    auto* object = AbortSignal::create(cx);
    if (!object) return false;
    object->reachable = reachable;
  }
  return true;
}
static void collect(JSContext* cx) {
  JS::PrepareForFullGC(cx);
  JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JSContext cx;
  bool passed = false;
  const char* mode = argv[1];
  if (!std::strcmp(mode, "synchronous-turnover")) {
    passed = make_graphs(&cx, 100, false) && collections > 0 && native::promise_accounting.live <= 64;
  } else if (!std::strcmp(mode, "fanout-after-dead-graphs")) {
    std::vector<std::unique_ptr<native::NativeContainer<Body>>> retained;
    for (unsigned i = 0; i < 4; ++i) retained.push_back(native::make_native_container<Body>(&cx));
    passed = make_graphs(&cx, 5, false) && make_graphs(&cx, 10, true);
    for (unsigned i = 0; i < 11 && passed; ++i) {
      auto owner = native::make_native_container<Body>(&cx);
      passed = owner != nullptr;
      retained.push_back(std::move(owner));
    }
    passed = passed && native::promise_accounting.live == 55 && collections > 0;
  } else if (!std::strcmp(mode, "all-reachable-remains-exhausted")) {
    passed = make_graphs(&cx, 16, true) && !AbortSignal::create(&cx) &&
      native::promise_accounting.live == 64 && native::promise_accounting.acknowledged == 0;
  } else if (!std::strcmp(mode, "event-construction-collects")) {
    for (unsigned i = 0; i < 100; ++i) {
      auto* object = EventTarget::create(&cx);
      if (!object) break;
      object->reachable = false;
      passed = i == 99 && collections > 0;
    }
  } else if (!std::strcmp(mode, "admission-does-not-collect")) {
    passed = make_graphs(&cx, 16, true);
    for (auto& object : objects) if (object) object->reachable = false;
    const unsigned before = collections;
    auto refused = native::make_native_container<Body>(&cx);
    passed = passed && !refused && collections == before && native::promise_accounting.live == 64;
  } else if (!std::strcmp(mode, "entry-pending") || !std::strcmp(mode, "snapshot")) {
    passed = make_graphs(&cx, 8, true);
    const unsigned before = allocations, gc = collections, live = native::promise_accounting.live;
    const bool pending = !std::strcmp(mode, "entry-pending");
    if (pending) cx.error = "original-error"; else initialized = false;
    passed = passed && !AbortSignal::create(&cx) && !EventTarget::create(&cx) && allocations == before &&
      collections == gc && native::promise_accounting.live == live &&
      (!pending || !std::strcmp(cx.error, "original-error"));
  } else if (!std::strcmp(mode, "acknowledgement-failure")) {
    passed = make_graphs(&cx, 8, true);
    for (auto& object : objects) if (object) object->reachable = false;
    refuse_ack = true;
    const unsigned before = allocations;
    passed = passed && !AbortSignal::create(&cx) && allocations == before &&
      native::promise_accounting.live == 32 && native::native_objects.stopped();
    const unsigned gc = collections;
    cx.error = nullptr;
    passed = passed && !EventTarget::create(&cx) && collections == gc && allocations == before;
  } else if (!std::strcmp(mode, "no-release-before-collection-end")) {
    passed = make_graphs(&cx, 16, true);
    for (auto& object : objects) if (object) object->reachable = false;
    finish_collection = false;
    passed = passed && !AbortSignal::create(&cx) && native::promise_accounting.live == 64 &&
      native::promise_accounting.acknowledged == 0 && bodies == 0;
  } else return 2;
  initialized = true; refuse_ack = false; finish_collection = true; cx.error = nullptr;
  for (auto& object : objects) if (object) object->reachable = false;
  collect(&cx);
  passed = native::acknowledge_promise_retirement(&cx) && passed;
  passed = passed && !native::native_objects.hasRetained() && native::promise_accounting.live == 0 &&
    !host_in_gc && bodies == 0 && prepared == collections;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", mode, passed ? "true" : "false");
  return passed ? 0 : 1;
}
