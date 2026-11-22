// Execute emitted lazy AbortSignal storage with real native ownership helpers.
// JS slots/vector failures are finite doubles, not SpiderMonkey qualification.
#include "native_retirement.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <new>
#include <utility>
#include <vector>

static void* watched = nullptr;
static bool backing_freed = false;
static unsigned nothrow_calls = 0, fail_nothrow_at = 0;
void* operator new(std::size_t size) {
  if (void* pointer = std::malloc(size ? size : 1)) return pointer;
  throw std::bad_alloc();
}
void* operator new(std::size_t size, const std::nothrow_t&) noexcept {
  if (++nothrow_calls == fail_nothrow_at) return nullptr;
  return std::malloc(size ? size : 1);
}
void operator delete(void* pointer) noexcept {
  if (pointer && pointer == watched) backing_freed = true;
  std::free(pointer);
}
void operator delete(void* pointer, std::size_t) noexcept { ::operator delete(pointer); }
void operator delete(void* pointer, const std::nothrow_t&) noexcept { ::operator delete(pointer); }

struct JSContext { const char* error = nullptr; };
bool JS_IsExceptionPending(JSContext* cx) { return cx->error != nullptr; }
void JS_ReportOutOfMemory(JSContext* cx) { cx->error = "out-of-memory"; }
#define MOZ_ASSERT(value) assert(value)
struct Value {
  void* pointer = nullptr;
  bool isNullOrUndefined() const { return pointer == nullptr; }
  void* toPrivate() const { assert(pointer); return pointer; }
};
struct JSObject { std::array<Value, 8> slots{}; bool aborted = false; };
using HandleObject = JSObject*;
namespace JS {
struct GCContext {};
Value GetReservedSlot(JSObject* object, unsigned slot) { return object->slots[slot]; }
void SetReservedSlot(JSObject* object, unsigned slot, Value value) { object->slots[slot] = value; }
Value UndefinedValue() { return {}; }
Value NullValue() { return {}; }
Value FalseValue() { return {}; }
Value PrivateValue(void* value) { return {value}; }
}
using JS::SetReservedSlot;
namespace js { template<class T> using UniquePtr = std::unique_ptr<T>; }

namespace lsf::typescript::activation {
struct Owner { unsigned id = 0; };
using NativeObjectRecords = NativeRetirement<Owner>;
using NativeObjectLease = NativeLease<NativeObjectRecords>;
NativeObjectRecords records;
unsigned live = 0, next = 1, admissions = 0, acks = 0;
bool refuse_ack = false, early_ack = false;
std::array<bool, 1024> tokens{};
bool checkpoint() {
  return records.checkpoint([](Owner& owner) {
    if (refuse_ack) return false;
    early_ack |= watched && !backing_freed;
    assert(tokens[owner.id] && live);
    tokens[owner.id] = false; --live; ++acks;
    return true;
  });
}
bool admit_native_object(JSContext* cx, NativeObjectLease& lease) {
  ++admissions;
  if (records.stopped() || !checkpoint()) { cx->error = "retirement-denied"; return false; }
  if (live == 64) { cx->error = "native-limit"; return false; }
  assert(next < tokens.size());
  const Owner owner{next++}; tokens[owner.id] = true; ++live;
  NativeObjectRecords::Record* record = nullptr;
  if (!records.track(owner, record)) { JS_ReportOutOfMemory(cx); return false; }
  return lease.bind(record);
}
// INSERT_NATIVE_CONTAINER_FACTORY
}
namespace native = lsf::typescript::activation;

static bool refuse_append = false, fail_listener_init = false;
static unsigned algorithms_created = 0, algorithms_destroyed = 0;
static unsigned lists_created = 0, lists_destroyed = 0, weak_sets = 0;
struct AbortAlgorithm {
  native::NativeObjectLease owner;
  unsigned id;
  AbortAlgorithm(native::NativeObjectLease&& lease, unsigned value)
      : owner(std::move(lease)), id(value) { ++algorithms_created; }
  ~AbortAlgorithm() { ++algorithms_destroyed; }
};
struct AlgorithmList {
  std::vector<js::UniquePtr<AbortAlgorithm>> values;
  AlgorithmList() { ++lists_created; }
  ~AlgorithmList() { ++lists_destroyed; }
  bool append(js::UniquePtr<AbortAlgorithm>&& value) {
    if (refuse_append) return false;
    assert(values.size() < 16);
    values.push_back(std::move(value)); return true;
  }
  size_t length() const { return values.size(); }
};
struct WeakIndexSet {
  bool initialized = false;
  void init(JSContext*) { assert(!initialized); initialized = true; ++weak_sets; }
  ~WeakIndexSet() { if (initialized) --weak_sets; }
};
struct ListenerList {};
struct EventTarget {
  static bool init(JSContext* cx, JSObject* object) {
    if (fail_listener_init) { JS_ReportOutOfMemory(cx); return false; }
    auto list = native::make_native_container<ListenerList>(cx);
    if (!list) return false;
    object->slots[0] = JS::PrivateValue(list.release()); return true;
  }
  static void finalize(JS::GCContext*, JSObject* object) {
    delete static_cast<native::NativeContainer<ListenerList>*>(object->slots[0].pointer);
    object->slots[0] = {};
  }
};
// RootedObject only needs construction and pointer conversion in these methods.
#undef MOZ_ASSERT
#define MOZ_ASSERT(value) assert(value)
struct RootedSignal {
  JSObject* object;
  RootedSignal(JSContext*, JSObject* value) : object(value) {}
  operator JSObject*() const { return object; }
  explicit operator bool() const { return object != nullptr; }
};
using RootedObject = RootedSignal;
static JSObject* last_created = nullptr;
JSObject* JS_NewObjectWithGivenProto(JSContext*, int*, int) {
  last_created = new JSObject; return last_created;
}
struct AbortSignal {
  using AlgorithmList = ::AlgorithmList;
  using OwnedAlgorithmList = native::NativeContainer<AlgorithmList>;
  using OwnedWeakSet = native::NativeContainer<WeakIndexSet>;
  enum class Slots : unsigned { Algorithms = 1, Reason, Dependent, SourceSignals, DependentSignals, OnAbort, OnAbortListener };
  static inline int class_ = 0, proto_obj = 0;
  static bool is_instance(JSObject* object) { return object != nullptr; }
  static bool is_aborted(JSObject* object) { return object->aborted; }
  static AlgorithmList* algorithms(JSObject*);
  static bool add_algorithm(JSContext*, HandleObject, js::UniquePtr<AbortAlgorithm>);
  static JSObject* create(JSContext*);
  static void finalize(JS::GCContext*, JSObject*);
};
// INSERT_EMITTED_FUNCTIONS

std::unique_ptr<AbortAlgorithm> algorithm(JSContext* cx, unsigned id) {
  native::NativeObjectLease lease;
  if (!native::admit_native_object(cx, lease)) return nullptr;
  return std::make_unique<AbortAlgorithm>(std::move(lease), id);
}
void destroy(JSObject* object) {
  JS::GCContext gc;
  AbortSignal::finalize(&gc, object);
  delete object;
}
void collect() { native::records.collectionCompleted(); assert(native::checkpoint()); }

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JSContext cx;
  const char* name = argv[1];
  bool passed = false;
  if (!std::strcmp(name, "empty-signal")) {
    auto* signal = AbortSignal::create(&cx);
    passed = signal && !AbortSignal::algorithms(signal) && lists_created == 0 && native::live == 3 && weak_sets == 2;
    destroy(signal);
    passed &= native::live == 3 && weak_sets == 0 && native::acks == 0;
    collect(); passed &= native::live == 0;
  } else if (!std::strcmp(name, "first-and-second-algorithm")) {
    auto* signal = AbortSignal::create(&cx);
    passed = AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 1));
    auto* original = signal->slots[1].pointer;
    passed &= lists_created == 1 && native::live == 5;
    passed &= AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 2));
    passed &= signal->slots[1].pointer == original && lists_created == 1 && native::live == 6;
    passed &= AbortSignal::algorithms(signal)->length() == 2;
    watched = original;
    destroy(signal);
    passed &= backing_freed && native::live == 6 && algorithms_destroyed == 2 && lists_destroyed == 1;
    collect(); passed &= !native::early_ack && native::live == 0;
  } else if (!std::strcmp(name, "quota-refusal")) {
    auto* signal = AbortSignal::create(&cx);
    auto item = algorithm(&cx, 1);
    std::vector<std::unique_ptr<native::NativeObjectLease>> fillers;
    while (native::live < 64) {
      auto lease = std::make_unique<native::NativeObjectLease>();
      assert(native::admit_native_object(&cx, *lease)); fillers.push_back(std::move(lease));
    }
    const bool added = AbortSignal::add_algorithm(&cx, signal, std::move(item));
    passed = !added && cx.error &&
             !std::strcmp(cx.error, "native-limit") && !signal->slots[1].pointer &&
             native::live == 64 && algorithms_destroyed == 1 && lists_created == 0;
    fillers.clear(); destroy(signal); collect(); passed &= native::live == 0;
  } else if (!std::strcmp(name, "allocation-refusal") || !std::strcmp(name, "first-append-refusal")) {
    auto* signal = AbortSignal::create(&cx);
    auto item = algorithm(&cx, 1);
    // The real factory first allocates its owner record, then container storage.
    if (!std::strcmp(name, "allocation-refusal")) fail_nothrow_at = nothrow_calls + 2;
    else refuse_append = true;
    const bool added = AbortSignal::add_algorithm(&cx, signal, std::move(item));
    passed = !added && cx.error &&
             !std::strcmp(cx.error, "out-of-memory") && !signal->slots[1].pointer &&
             native::live == 5 && algorithms_destroyed == 1 && lists_destroyed == lists_created;
    fail_nothrow_at = 0; refuse_append = false;
    collect(); passed &= native::live == 3;
    cx.error = nullptr;
    passed &= AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 2)) && native::live == 5;
    destroy(signal); collect(); passed &= native::live == 0;
  } else if (!std::strcmp(name, "existing-append-refusal")) {
    auto* signal = AbortSignal::create(&cx);
    assert(AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 1)));
    auto* original = signal->slots[1].pointer;
    refuse_append = true;
    const bool added = AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 2));
    passed = !added &&
             signal->slots[1].pointer == original && lists_created == 1 &&
             AbortSignal::algorithms(signal)->values[0]->id == 1 && algorithms_destroyed == 1;
    collect(); passed &= native::live == 5;
    destroy(signal); collect(); passed &= native::live == 0;
  } else if (!std::strcmp(name, "pending-exception") || !std::strcmp(name, "already-aborted")) {
    auto* signal = AbortSignal::create(&cx);
    auto item = algorithm(&cx, 1);
    if (!std::strcmp(name, "pending-exception")) cx.error = "original";
    else signal->aborted = true;
    const auto before = native::admissions;
    const bool added = AbortSignal::add_algorithm(&cx, signal, std::move(item));
    passed = !added && native::admissions == before &&
             !signal->slots[1].pointer && lists_created == 0 && algorithms_destroyed == 1;
    if (cx.error) passed &= !std::strcmp(cx.error, "original");
    destroy(signal); collect(); passed &= native::live == 0;
  } else if (!std::strcmp(name, "partial-signal")) {
    fail_listener_init = true;
    passed = !AbortSignal::create(&cx) && native::live == 2 && lists_created == 0;
    destroy(last_created); collect(); passed &= native::live == 0 && weak_sets == 0;
  } else if (!std::strcmp(name, "failed-ack-retains-owner")) {
    auto* signal = AbortSignal::create(&cx);
    assert(AbortSignal::add_algorithm(&cx, signal, algorithm(&cx, 1)));
    destroy(signal); native::records.collectionCompleted(); native::refuse_ack = true;
    passed = !native::checkpoint() && native::live == 5 && native::records.stopped();
    native::refuse_ack = false;
    passed &= native::checkpoint() && native::live == 0;
  } else if (!std::strcmp(name, "ten-signal-recovery-capacity")) {
    // The observed export owns 13 other native records and ten real listeners.
    // These finite leases model only that already-live demand; never signed proof.
    std::array<native::NativeObjectLease, 23> existing;
    for (auto& lease : existing) assert(native::admit_native_object(&cx, lease));
    std::array<JSObject*, 10> graph{};
    for (auto& signal : graph) signal = AbortSignal::create(&cx);
    std::vector<std::unique_ptr<native::NativeObjectLease>> fillers;
    while (native::live < 64) {
      auto lease = std::make_unique<native::NativeObjectLease>();
      assert(native::admit_native_object(&cx, *lease)); fillers.push_back(std::move(lease));
    }
    native::NativeObjectLease refused;
    passed = !fillers.empty() && !native::admit_native_object(&cx, refused);
    fillers.clear(); collect(); cx.error = nullptr;
    std::array<native::NativeObjectLease, 3> continuation;
    for (auto& lease : continuation) passed &= native::admit_native_object(&cx, lease);
    for (auto* signal : graph) destroy(signal);
  } else return 2;
  passed &= !native::early_ack;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", name, passed ? "true" : "false");
  return passed ? 0 : 1;
}
