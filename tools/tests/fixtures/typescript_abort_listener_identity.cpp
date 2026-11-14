// Exact emitted abort Terminator with finite GC/container doubles. The production
// retirement registry is used below; this is not a linked-engine qualification.
#include "sdk/typescript-guest/activation/native_retirement.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <memory>
#include <utility>
#include <vector>

struct JSContext {};
struct JSTracer { unsigned targets = 0, listeners = 0; };
struct JSObject;
using HandleObject = JSObject*;
template<class T> struct Heap {
  T value;
  Heap(T value) : value(value) {}
  operator T() const { return value; }
};
struct RootedObject {
  JSObject* value;
  RootedObject(JSContext*, JSObject* value) : value(value) {}
  operator JSObject*() const { return value; }
};
namespace JS {
inline void TraceEdge(JSTracer* tracer, Heap<JSObject*>*, const char*) { ++tracer->targets; }
}
template<class T> using RefPtr = std::shared_ptr<T>;
struct Owner { unsigned id = 0; bool live = false; };
namespace lsf::typescript::activation {
using NativeObjectRecords = NativeRetirement<Owner>;
using NativeObjectLease = NativeLease<NativeObjectRecords>;
}
using namespace lsf::typescript::activation;
struct EventListener {
  NativeObjectLease native_owner;
  explicit EventListener(NativeObjectLease&& owner) : native_owner(std::move(owner)) {}
  bool removed = false;
  unsigned key = 1;
  void trace(JSTracer* tracer) { ++tracer->listeners; }
};
struct ListenerList {
  std::vector<RefPtr<EventListener>> records;
  auto begin() { return records.begin(); }
  auto end() { return records.end(); }
  void erase(decltype(records)::iterator it) { records.erase(it); }
};
struct JSObject { ListenerList list; };
struct EventTarget {
  static ListenerList* listeners(JSObject* target) { return &target->list; }
};
struct AbortAlgorithm {
  NativeObjectLease native_owner;
  explicit AbortAlgorithm(NativeObjectLease&& owner) : native_owner(std::move(owner)) {}
  virtual ~AbortAlgorithm() = default;
  virtual bool run(JSContext*) = 0;
  virtual void trace(JSTracer*) = 0;
};

// INSERT_EMITTED_ABORT_TERMINATOR

static NativeObjectLease accepted(NativeObjectRecords& records, unsigned id) {
  NativeObjectRecords::Record* record = nullptr;
  if (!records.track(Owner{id, true}, record)) std::abort();
  NativeObjectLease lease;
  if (!lease.bind(record)) std::abort();
  return lease;
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const auto is = [&](const char* name) { return !std::strcmp(argv[1], name); };
  JSContext cx;
  NativeObjectRecords records;
  JSObject target;
  auto listener = std::make_shared<EventListener>(accepted(records, 1));
  target.list.records.push_back(listener);
  auto algorithm = std::make_unique<Terminator>(accepted(records, 2), &target, listener);
  std::weak_ptr<EventListener> physical(listener);
  bool passed = false;
  if (is("exact-removal-and-idempotence")) {
    passed = algorithm->run(&cx) && target.list.records.empty() && listener->removed &&
             algorithm->run(&cx) && records.hasPhysical();
  } else if (is("old-abort-cannot-remove-replacement")) {
    listener->removed = true;
    target.list.records.clear();
    auto replacement = std::make_shared<EventListener>(accepted(records, 3));
    replacement->key = listener->key;
    target.list.records.push_back(replacement);
    passed = algorithm->run(&cx) && target.list.records.size() == 1 &&
             target.list.records[0] == replacement && !replacement->removed;
  } else if (is("detached-record-remains-traced-and-owned")) {
    target.list.records.clear();
    listener.reset();
    JSTracer tracer;
    algorithm->trace(&tracer);
    passed = !physical.expired() && records.hasPhysical() &&
             tracer.targets == 1 && tracer.listeners == 1 && algorithm->run(&cx);
    algorithm.reset();
    passed &= physical.expired() && !records.hasPhysical() && records.hasRetained();
  } else if (is("dispatch-clone-outlives-abort-algorithm")) {
    auto clone = target.list.records;
    listener.reset();
    passed = algorithm->run(&cx) && target.list.records.empty();
    algorithm.reset();
    passed &= !physical.expired() && records.hasPhysical() && clone[0]->removed;
    clone.clear();
    passed &= physical.expired() && !records.hasPhysical();
  } else if (is("refused-ack-retains-physical-custody")) {
    listener.reset();
    passed = algorithm->run(&cx);
    algorithm.reset();
    passed &= physical.expired() && !records.hasPhysical();
    unsigned acks = 0;
    auto refused = [&](Owner&) { ++acks; return false; };
    // Destruction is not itself a fabricated GC completion.
    passed &= records.checkpoint(refused) && acks == 0 && records.hasRetained();
    records.collectionCompleted();
    passed &= !records.checkpoint(refused) && acks == 1 && records.hasRetained() && records.stopped();
  } else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              argv[1], passed ? "true" : "false");
  return passed ? 0 : 1;
}
