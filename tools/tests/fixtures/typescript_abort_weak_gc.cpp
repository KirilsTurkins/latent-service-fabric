// Execute the emitted WeakIndexSet, AbortSignal trace, and listener predicate.
// The collector below is a finite phase/relocation double, not SpiderMonkey.
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <optional>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#include "sdk/typescript-guest/activation/native_retirement.h"

namespace std { template<class E> constexpr auto to_underlying(E value) { return static_cast<underlying_type_t<E>>(value); } }
#define MOZ_ASSERT(x) assert(x)
#define MOZ_RELEASE_ASSERT(x) assert(x)
struct JSObject;
struct JSTracer {
  enum Phase { Mark, Sweep, Move } phase = Mark;
  bool isMarkingTracer() const { return phase == Mark; }
};
static unsigned wrong_phase = 0, invalid_reads = 0, barrier_during_trace = 0;
static bool in_trace = false;
struct CacheBase;
struct JSRuntime { CacheBase* head = nullptr; unsigned size = 0; };
struct JSContext { JSRuntime* runtime; };
inline JSRuntime* JS_GetRuntime(JSContext* cx) { return cx->runtime; }
struct CacheBase {
  JSRuntime* runtime;
  CacheBase* previous = nullptr;
  CacheBase* next = nullptr;
  explicit CacheBase(JSRuntime* rt) : runtime(rt) {
    next = rt->head;
    if (next) next->previous = this;
    rt->head = this;
    ++rt->size;
  }
  virtual ~CacheBase() {
    if (previous) previous->next = next; else runtime->head = next;
    if (next) next->previous = previous;
    --runtime->size;
  }
  virtual void sweep(JSTracer*) = 0;
};
namespace mozilla {
template<class T> struct Maybe {
  std::optional<T> value;
  explicit operator bool() const { return value.has_value(); }
  template<class... Args> void emplace(Args&&... args) { value.emplace(std::forward<Args>(args)...); }
  T* operator->() { return &*value; }
  const T* operator->() const { return &*value; }
};
}
static void mark(JSObject*, JSTracer*);
static bool live(JSObject*);
static JSObject* relocated(JSObject*);
namespace js { struct SystemAllocPolicy {}; }
namespace JS {
template<class T> class Heap {
  T ptr = nullptr;
public:
  Heap() = default;
  Heap(T value) : ptr(value) {}
  T unbarrieredGet() const { return ptr; }
  operator T() const { if (in_trace) ++barrier_during_trace; return ptr; }
  void set(T value) { ptr = value; }
};
static void TraceEdge(JSTracer* trc, Heap<JSObject*>* edge, const char*) {
  if (trc->phase == JSTracer::Move) edge->set(relocated(edge->unbarrieredGet()));
  else mark(edge->unbarrieredGet(), trc);
}
template<class T, size_t, class> struct GCVector : std::vector<T> {
  using Base = std::vector<T>;
  T* begin() { return this->data(); }
  T* end() { return this->empty() ? this->data() : this->data()+this->size(); }
  const T* begin() const { return this->data(); }
  const T* end() const { return this->empty() ? this->data() : this->data()+this->size(); }
  bool append(JSObject* value) { this->emplace_back(value); return true; }
  template<class Predicate> void eraseIf(Predicate predicate) {
    Base::erase(std::remove_if(Base::begin(), Base::end(), predicate), Base::end());
  }
  void trace(JSTracer* trc) { for (auto& edge : *this) TraceEdge(trc, &edge, "vector"); }
  bool traceWeak(JSTracer* trc) {
    if (trc->phase != JSTracer::Sweep && trc->phase != JSTracer::Move) { ++wrong_phase; return true; }
    for (auto& edge : *this) edge.set(relocated(edge.unbarrieredGet()));
    if (trc->phase == JSTracer::Sweep) eraseIf([](const auto& edge) { return !live(edge.unbarrieredGet()); });
    return !this->empty();
  }
};
template<class T> class WeakCache final : public CacheBase {
  T value;
public:
  explicit WeakCache(JSRuntime* rt) : CacheBase(rt) {}
  T& get() { return value; }
  const T& get() const { return value; }
  void sweep(JSTracer* trc) override { value.traceWeak(trc); }
};
}

// INSERT_EMITTED_WEAK_SET

struct Listener { bool removed = false; std::string type = "abort"; JSObject* captured = nullptr; };
using List = std::vector<std::shared_ptr<Listener>>;
struct Algorithms : std::vector<JSObject*> {
  void trace(JSTracer* trc) { for (auto* captured : *this) mark(captured, trc); }
};
struct JSObject {
  bool marked = false, aborted = false, poisoned = false;
  JSObject* forwarded = nullptr;
  WeakIndexSet* sources = nullptr;
  WeakIndexSet* dependents = nullptr;
  Algorithms* algorithms = nullptr;
  List list;
};
namespace JS {
struct Value { bool empty = true; bool isNullOrUndefined() const { return empty; } };
static Value GetReservedSlot(JSObject* object, unsigned slot) {
  if (object->poisoned) ++invalid_reads;
  return {slot == 0 ? !object->sources : slot == 1 ? !object->dependents : !object->algorithms};
}
}
struct EventTarget {
  static List* listeners(JSObject* self) { return &self->list; }
  static bool has_listener(JSObject*, const char*);
  static void trace(JSTracer* trc, JSObject* self) {
    for (const auto& listener : self->list) if (listener->captured) mark(listener->captured, trc);
  }
};
struct AbortSignal {
  enum class Slots { SourceSignals, DependentSignals, Algorithms };
  static bool is_instance(JSObject* self) { return self != nullptr; }
  static bool is_aborted(JSObject* self) { if (self->poisoned) ++invalid_reads; return self->aborted; }
  static WeakIndexSet* source_signals(JSObject* self) { return self->sources; }
  static WeakIndexSet* dependent_signals(JSObject* self) { return self->dependents; }
  static Algorithms* algorithms(JSObject* self) { return self->algorithms; }
  static void trace(JSTracer*, JSObject*);
};

// INSERT_EMITTED_LISTENER_PREDICATE
// INSERT_EMITTED_SIGNAL_TRACE

static void mark(JSObject* object, JSTracer* trc) {
  if (!object || object->marked) return;
  object->marked = true;
  const bool before = in_trace;
  in_trace = true;
  AbortSignal::trace(trc, object);
  in_trace = before;
}
static bool live(JSObject* object) { return object && object->marked; }
static JSObject* relocated(JSObject* object) { return object && object->forwarded ? object->forwarded : object; }
static void sweep(JSRuntime& runtime, JSTracer::Phase phase = JSTracer::Sweep) {
  JSTracer trc{phase};
  for (auto* cache = runtime.head; cache; cache = cache->next) cache->sweep(&trc);
}
static void initialize(WeakIndexSet& set, JSContext* cx) {
#if SELECTED_WEAK_SET
  set.init(cx);
#else
  (void)set; (void)cx;
#endif
}
using Records = lsf::typescript::activation::NativeRetirement<unsigned>;
using Lease = lsf::typescript::activation::NativeLease<Records>;
using Owned = lsf::typescript::activation::OwnedNativeContainer<Records, WeakIndexSet>;
static std::unique_ptr<Owned> owned_set(JSContext* cx, Records& records, unsigned token) {
  Records::Record* record = nullptr;
  assert(records.track(token, record));
  Lease lease;
  assert(lease.bind(record));
  auto result = std::make_unique<Owned>(std::move(lease));
  initialize(result->value, cx);
  return result;
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const auto is = [&](const char* s) { return std::strcmp(argv[1], s) == 0; };
  JSRuntime runtime;
  JSContext cx{&runtime};
  Records records;
  auto sources = owned_set(&cx, records, 11);
  auto dependents = owned_set(&cx, records, 12);
  bool passed = true;
  JSObject root, dependent, captured;
  Algorithms algorithms;
  root.dependents = &dependents->value;
  dependent.sources = &sources->value;
  dependent.algorithms = &algorithms;
  assert(root.dependents->insert(&dependent));
  assert(dependent.sources->insert(&root));
  auto listener = std::make_shared<Listener>();
  if (is("observed-listener") || is("removed-listener") || is("nonabort-listener") ||
      is("aborted-dependent") || is("listener-removal-next-collection") || is("captured-source"))
    dependent.list.push_back(listener);
  if (is("removed-listener")) listener->removed = true;
  if (is("nonabort-listener")) listener->type = "unrelated";
  if (is("aborted-dependent") || is("aborted-failed-algorithm") || is("failed-algorithm-drained-next-collection")) dependent.aborted = true;
  if (is("observed-algorithm") || is("aborted-failed-algorithm") || is("failed-algorithm-drained-next-collection")) algorithms.push_back(&captured);
  if (is("captured-source")) listener->captured = &root;
  JSTracer tracer;
  if (is("custody-refused-ack")) {
    passed &= runtime.size == 2;
    unsigned acks = 0;
    auto ack = [&](unsigned) { ++acks; return true; };
    records.collectionCompleted(); // finite engine callback, NOT production GC
    passed &= records.checkpoint(ack) && acks == 0;
    sources.reset(); dependents.reset();
    passed &= runtime.size == 0 && !runtime.head;
    passed &= records.checkpoint(ack) && acks == 0;
    records.collectionCompleted(); // actual production path is engine-driven
    unsigned refused = 0;
    passed &= !records.checkpoint([&](unsigned token) { refused = token; return false; });
    std::vector<unsigned> observed;
    passed &= records.hasRetained() && records.checkpoint([&](unsigned token) { observed.push_back(token); return true; });
    passed &= observed.size() == 2 && observed[0] == refused && observed[0] != observed[1] && !records.hasRetained();
  } else if (is("relocation-before-inspection")) {
    JSObject moved;
    moved.marked = true;
    dependent.poisoned = true; dependent.forwarded = &moved;
    tracer.phase = JSTracer::Move;
    in_trace = true;
    AbortSignal::trace(&tracer, &root);
    in_trace = false;
    sweep(runtime, JSTracer::Move);
    passed &= root.dependents->items().front().unbarrieredGet() == &moved;
  } else if (is("partial-object")) {
    JSObject partial;
    mark(&partial, &tracer); sweep(runtime);
    passed &= partial.marked;
  } else if (is("heap-unobserved")) {
    std::vector<JSObject> others(9);
    for (auto& object : others) assert(root.dependents->insert(&object));
    mark(&root, &tracer); sweep(runtime);
    passed &= root.dependents->items().empty();
    for (const auto& object : others) passed &= !object.marked;
  } else if (is("source-is-weak") || is("captured-source")) {
    mark(&dependent, &tracer); sweep(runtime);
    passed &= root.marked == is("captured-source");
    passed &= dependent.sources->items().empty() == is("source-is-weak");
  } else if (is("unobserved") || is("observed-listener") || is("observed-algorithm") ||
             is("removed-listener") || is("nonabort-listener") || is("aborted-dependent") ||
             is("listener-removal-next-collection") || is("aborted-failed-algorithm") ||
             is("failed-algorithm-drained-next-collection")) {
    const bool retained = is("observed-listener") || is("listener-removal-next-collection") || !algorithms.empty();
    mark(&root, &tracer); sweep(runtime);
    passed &= dependent.marked == retained;
    passed &= root.dependents->items().empty() == !retained;
    passed &= captured.marked == !algorithms.empty();
    if (is("listener-removal-next-collection") || is("failed-algorithm-drained-next-collection")) {
      listener->removed = true;
      algorithms.clear();
      root.marked = dependent.marked = false;
      mark(&root, &tracer); sweep(runtime);
      passed &= !dependent.marked && root.dependents->items().empty();
    }
  } else return 2;
  passed &= !wrong_phase && !invalid_reads && !barrier_during_trace;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", argv[1], passed ? "true" : "false");
  return passed ? 0 : 1;
}
