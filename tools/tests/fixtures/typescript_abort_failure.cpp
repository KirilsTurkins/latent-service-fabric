// Executes emitted abort functions with bounded JS/vector/broker doubles and
// the production native retirement header. Not SpiderMonkey or signed evidence.
#include "native_retirement.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <functional>
#include <memory>
#include <optional>
#include <vector>

struct RootLink;
struct JSContext {
  int pending = 0, stack = 0, status = 0;
  bool trapped = false;
  std::array<RootLink*, 2> roots{};
};
struct Signal;
namespace lsf::typescript::activation {
struct TestOwner { size_t id = 0; };
using NativeObjectRecords = NativeRetirement<TestOwner>;
using NativeObjectLease = NativeLease<NativeObjectRecords>;
using NativeObjectFrameLease = NativeFrameLease<NativeObjectRecords>;
NativeObjectRecords records;
}
namespace native = lsf::typescript::activation;
struct State {
  std::vector<int> order;
  int destroyed = 0, dispatches = 0, null_dereferences = 0;
  int fail_algorithm = 0, fail_dispatch = 0, second_fail_dispatch = 0, trap_dispatch = 0;
  int pending_algorithm = 0, trap_algorithm = 0;
  int error_status = 1;
  int next_default_reason = 100, default_reasons = 0;
  bool fail_reason = false, fail_event = false, success_with_exception = false;
  bool fail_reserve = false, refuse_ack = false;
  bool premature_release = false, unowned = false, early_publication = false;
  int pending_entries = 0, active_roots = 0;
  bool invalid_root_order = false;
  size_t limit = 64, admitted = 0, live = 0, peak = 0, acknowledged = 0;
  size_t reserve_attempts = 0, live_backings = 0;
  std::array<bool, 256> owners{}, backings{};
  std::array<native::NativeObjectRecords::Record*, 256> record{};
  Signal* before_growth = nullptr;
  std::function<void(JSContext*)> on_reason;
  std::function<bool(JSContext*, Signal*)> on_dispatch;
  std::function<bool(JSContext*, int)> on_algorithm;
};
static State state;
void error(JSContext* cx, int value, int stack, int status = 1) {
  cx->pending = value; cx->stack = stack; cx->status = status;
}
// Negative status models JSAPI ForcedReturn: failure, but not catchable.
bool JS_IsExceptionPending(JSContext* cx) { return cx->status > 0; }
void JS_ClearPendingException(JSContext* cx) { cx->pending = 0; cx->stack = 0; cx->status = 0; }
void JS_ReportOutOfMemory(JSContext* cx) { error(cx, 606, 6060, 2); }
static bool checkpoint(JSContext* cx) {
  return native::records.checkpoint([cx](native::TestOwner& owner) {
    state.premature_release |= state.backings[owner.id];
    state.record[owner.id] = nullptr; // the tracking allocation is already gone
    if (state.refuse_ack) { error(cx, 707, 7070); return false; }
    assert(state.owners[owner.id] && state.live);
    state.owners[owner.id] = false;
    --state.live; ++state.acknowledged;
    return true;
  });
}
namespace lsf::typescript::activation {
bool admit_native_object(JSContext* cx, NativeObjectLease& lease) {
  if (records.stopped()) { error(cx, 505, 5050); return false; }
  if (!checkpoint(cx)) return false;
  if (state.live >= state.limit) { error(cx, 505, 5050); return false; }
  const size_t id = ++state.admitted;
  assert(id < state.owners.size());
  state.owners[id] = true;
  ++state.live;
  state.peak = std::max(state.peak, state.live);
  NativeObjectRecords::Record* record = nullptr;
  if (!records.track(TestOwner{id}, record)) { JS_ReportOutOfMemory(cx); return false; }
  state.record[id] = record;
  return lease.bind(record);
}
}
struct Algorithm {
  native::NativeObjectLease native_owner;
  int id;
  explicit Algorithm(int value) : id(value) {}
  ~Algorithm() { ++state.destroyed; }
  bool run(JSContext* cx) {
    if (JS_IsExceptionPending(cx)) ++state.pending_entries;
    state.order.push_back(id);
    if (state.on_algorithm) return state.on_algorithm(cx, id);
    if (state.trap_algorithm == id) { cx->trapped = true; return false; }
    if (state.pending_algorithm == id) { error(cx, 202, id, state.error_status); return true; }
    if (state.fail_algorithm == id) { error(cx, 202, id, state.error_status); return false; }
    return true;
  }
};
struct WeakIndexSet {
  std::vector<Signal*> values;
  std::vector<Signal*>& items() { return values; }
};
struct AlgorithmList : std::vector<std::unique_ptr<Algorithm>> {
  size_t length() const { return size(); }
};
struct Signal {
  int id = 0, reason = 0;
  bool aborted = false;
  WeakIndexSet dependents;
  AlgorithmList algorithms;
};
using HandleObject = Signal*;
using HandleValue = int;
// Mirror the pinned per-kind Rooted stack discipline, not a collector. On a
// bad pop repair the finite model's chain so negative controls report failure
// without undefined behavior in the test itself.
struct RootLink {
  JSContext* cx;
  size_t kind;
  RootLink* previous;
  RootLink(JSContext* context, size_t selected)
      : cx(context), kind(selected), previous(cx->roots[kind]) {
    cx->roots[kind] = this;
    ++state.active_roots;
  }
  RootLink(const RootLink&) = delete;
  ~RootLink() {
    state.invalid_root_order |= cx->roots[kind] != this;
    auto** link = &cx->roots[kind];
    while (*link && *link != this) link = &(*link)->previous;
    assert(*link == this);
    *link = previous;
    --state.active_roots;
  }
};
struct RootedObject {
  RootLink root;
  Signal* object;
  explicit RootedObject(JSContext* cx, Signal* value = nullptr) : root(cx, 0), object(value) {}
  void set(Signal* value) { object = value; }
  operator Signal*() const { return object; }
  RootedObject& operator=(Signal* value) { object = value; return *this; }
  explicit operator bool() const { return object != nullptr; }
  Signal& operator*() const {
    if (!object) { ++state.null_dereferences; static Signal fallback; return fallback; }
    return *object;
  }
};
struct RootedValue {
  RootLink root;
  int value = 0;
  explicit RootedValue(JSContext* cx) : root(cx, 1) {}
  RootedValue(JSContext* cx, int selected) : root(cx, 1), value(selected) {}
  operator int() const { return value; }
  bool isUndefined() const { return value == 0; }
  void setObject(Signal& object) { value = object.reason; }
};
namespace JS {
// Finite eight-cell inline vector double; only its backing allocation is modeled.
class RootedObjectVector {
  JSContext* cx_;
  std::array<Signal*, 8> inline_{};
  std::unique_ptr<Signal*[]> heap_;
  size_t length_ = 0, capacity_ = inline_.size(), owner_ = 0;
public:
  explicit RootedObjectVector(JSContext* cx) : cx_(cx) {}
  ~RootedObjectVector() {
    if (!heap_) return;
    state.premature_release |= owner_ && (!state.owners[owner_] ||
        !state.record[owner_] || !state.record[owner_]->physical);
    heap_.reset();
    --state.live_backings;
    if (owner_) state.backings[owner_] = false;
  }
  size_t capacity() const { return capacity_; }
  bool reserve(size_t count) {
    if (count <= capacity_) return true;
    ++state.reserve_attempts;
    if (state.before_growth && state.before_growth->aborted) state.early_publication = true;
    if (state.fail_reserve) { JS_ReportOutOfMemory(cx_); return false; }
    auto next = std::make_unique<Signal*[]>(count);
    std::copy(begin(), end(), next.get());
    if (!heap_) {
      ++state.live_backings;
      const size_t candidate = state.admitted;
      if (candidate && state.owners[candidate] && !state.backings[candidate]) {
        owner_ = candidate;
        state.backings[owner_] = true;
      } else state.unowned = true;
    }
    heap_ = std::move(next); capacity_ = count;
    return true;
  }
  void infallibleAppend(Signal* value) { assert(length_ < capacity_); begin()[length_++] = value; }
  bool append(const RootedObject& value) {
    if (length_ == capacity_ && !reserve(2 * capacity_)) return false;
    infallibleAppend(value);
    return true;
  }
  bool empty() const { return !length_; }
  Signal** begin() { return heap_ ? heap_.get() : inline_.data(); }
  Signal** end() { return begin() + length_; }
};
// Mirrors the pinned JSAPI save/clear/restore/drop contract, including stack and
// OOM status. The actual production AutoSaveExceptionState remains engine-owned.
class AutoSaveExceptionState {
  JSContext* cx_;
  int pending_, stack_, status_;
  bool armed_ = true;
  RootedValue exception_value_;
  RootedObject exception_stack_;
public:
  explicit AutoSaveExceptionState(JSContext* cx)
      : cx_(cx), pending_(cx->pending), stack_(cx->stack), status_(cx->status),
        exception_value_(cx, cx->pending), exception_stack_(cx) {
    JS_ClearPendingException(cx);
  }
  AutoSaveExceptionState(const AutoSaveExceptionState&) = delete;
  ~AutoSaveExceptionState() { if (armed_ && !JS_IsExceptionPending(cx_)) restore(); }
  void drop() { armed_ = false; }
  void restore() { error(cx_, pending_, stack_, status_); armed_ = false; }
};
constexpr int NullHandleValue = 0;
int StringValue(int) { return 0; }
int ObjectValue(Signal&) { return 0; }
}
namespace mozilla { template<class T> using Maybe = std::optional<T>; }
namespace dom_exception {
struct DOMException {
  static Signal* create(JSContext* cx, const char*, const char*) {
    if (state.fail_reason) { error(cx, 101, 1010); return nullptr; }
    ++state.default_reasons;
    auto hook = std::move(state.on_reason);
    state.on_reason = nullptr;
    if (hook) hook(cx);
    if (cx->trapped) return nullptr;
    static Signal exception;
    exception.reason = ++state.next_default_reason;
    return &exception;
  }
};
}
// Factory internals are exercised separately by the emitted factory controls.
[[maybe_unused]] static Signal* create_abort_exception(JSContext* cx, const char* name) {
  return dom_exception::DOMException::create(cx, name, name);
}
struct Event {
  static Signal* create(JSContext* cx, RootedValue&, int) {
    if (state.fail_event) { error(cx, 303, 3030); return nullptr; }
    static Signal event;
    return &event;
  }
};
struct EventTarget {
  static bool dispatch_event(JSContext* cx, Signal* signal, RootedValue&, RootedValue*) {
    if (JS_IsExceptionPending(cx)) ++state.pending_entries;
    ++state.dispatches;
    state.order.push_back(100 + signal->id);
    if (state.on_dispatch && !state.on_dispatch(cx, signal)) return false;
    if (state.trap_dispatch == signal->id) {
      JS_ClearPendingException(cx); cx->trapped = true; return false;
    }
    if (state.fail_dispatch == signal->id || state.second_fail_dispatch == signal->id) {
      error(cx, state.fail_dispatch == signal->id ? 404 : 405, signal->id, state.error_status);
      return state.success_with_exception;
    }
    return true;
  }
};
#define MOZ_ASSERT(value) assert(value)
struct AbortSignal {
  static int abort_type_atom;
  static bool is_instance(Signal* signal) { return signal != nullptr; }
  static bool is_aborted(Signal* signal) { return signal->aborted; }
  static bool set_reason(JSContext* cx, Signal* signal, int reason) {
    if (!reason) {
      auto* exception = dom_exception::DOMException::create(cx, "AbortError", "AbortError");
      if (!exception) return false;
      reason = exception->reason;
    }
    signal->reason = reason;
    signal->aborted = true;
    return true;
  }
  static int reason(Signal* signal) { return signal->reason; }
  static WeakIndexSet* dependent_signals(Signal* signal) { return &signal->dependents; }
  static AlgorithmList* algorithms(Signal* signal) { return &signal->algorithms; }
  static bool abort(JSContext*, HandleObject, HandleValue);
  static bool run_abort_steps(JSContext*, HandleObject);
};
int AbortSignal::abort_type_atom = 1;

// INSERT_EMITTED_ABORT_FUNCTION

// INSERT_EMITTED_ABORT_STEPS_FUNCTION

static void add(Signal& signal, int id) { signal.algorithms.push_back(std::make_unique<Algorithm>(id)); }
struct Graph {
  Signal root;
  std::array<Signal, 12> dependents;
  size_t count;
  explicit Graph(size_t length = 12, int base = 1) : count(length) {
    assert(count <= dependents.size());
    root.id = base; add(root, 10 * base + 1);
    for (size_t i = 0; i < count; ++i) {
      auto& signal = dependents[i];
      signal.id = base + 1 + static_cast<int>(i);
      add(signal, 10 * signal.id + 1);
      root.dependents.values.push_back(&signal);
    }
  }
  bool reasons(int value) const {
    if (!root.aborted || root.reason != value) return false;
    for (size_t i = 0; i < count; ++i)
      if (!dependents[i].aborted || dependents[i].reason != value) return false;
    return true;
  }
  bool unchanged() const {
    if (root.aborted || root.reason || root.algorithms.size() != 1) return false;
    for (size_t i = 0; i < count; ++i)
      if (dependents[i].aborted || dependents[i].reason || dependents[i].algorithms.size() != 1) return false;
    return true;
  }
};
static bool fanout_case(const char* name) {
  auto is = [name](const char* value) { return !std::strcmp(name, value); };
  JSContext cx;
  Graph graph(is("fanout-inline") || is("fanout-default-reentry") ? 3 : 12);
  state.before_growth = &graph.root;
  bool callback_checked = false, all_ready = true;
  state.on_dispatch = [&](JSContext* context, Signal*) {
    callback_checked = true;
    all_ready &= graph.reasons(7);
    native::records.collectionCompleted();
    if (!checkpoint(context)) return false;
    return true;
  };
  if (is("fanout-refusal")) state.limit = 0;
  if (is("fanout-reserve-failure") || is("fanout-recovery")) state.fail_reserve = true;
  if (is("fanout-all-aborted")) {
    for (auto& signal : graph.dependents) { signal.aborted = true; signal.reason = 99; }
    state.limit = 0;
    state.on_dispatch = nullptr;
  }
  if (is("fanout-first-error") || is("fanout-error-then-trap")) state.fail_dispatch = graph.root.id;
  if (is("fanout-first-error")) state.second_fail_dispatch = graph.dependents[0].id;
  if (is("fanout-dependent-error")) state.fail_dispatch = graph.dependents[0].id;
  if (is("fanout-trap")) state.trap_dispatch = graph.root.id;
  if (is("fanout-error-then-trap")) state.trap_dispatch = graph.dependents[0].id;
  if (is("fanout-success-with-error")) { state.fail_dispatch = graph.root.id; state.success_with_exception = true; }
  if (is("fanout-default-reentry")) {
    state.on_dispatch = nullptr;
    bool inner_ok = false;
    state.on_reason = [&](JSContext* context) { inner_ok = AbortSignal::abort(context, &graph.root, 73); };
    const bool ok = AbortSignal::abort(&cx, &graph.root, 0);
    const bool verified = ok && inner_ok && graph.reasons(73) && state.dispatches == 4 &&
                          state.default_reasons == 1 && state.admitted == 0 && !cx.pending;
    return checkpoint(&cx) && verified && !state.live && !state.unowned && !state.premature_release;
  }
  if (is("fanout-nested") || is("fanout-nested-refusal")) {
    Graph inner(12, 30);
    const bool refuse = is("fanout-nested-refusal");
    state.limit = refuse ? 1 : 2;
    bool nested = false, inner_result = false, nested_unchanged = false;
    state.on_dispatch = [&](JSContext* context, Signal* signal) {
      all_ready &= graph.reasons(7);
      if (signal != &graph.root) return true;
      nested = true;
      state.before_growth = &inner.root;
      inner_result = AbortSignal::abort(context, &inner.root, 8);
      nested_unchanged = inner.unchanged();
      state.before_growth = &graph.root;
      return inner_result;
    };
    const bool ok = AbortSignal::abort(&cx, &graph.root, 7);
    bool verified = nested && all_ready && graph.reasons(7) && !state.pending_entries;
    if (refuse) verified &= !ok && !inner_result && nested_unchanged && cx.pending == 505 &&
                            state.peak == 1 && state.dispatches == 13;
    else verified &= ok && inner_result && inner.reasons(8) && !cx.pending && state.peak == 2 &&
                     state.dispatches == 26;
    JS_ClearPendingException(&cx);
    verified &= checkpoint(&cx) && !state.live;
    if (refuse) {
      state.on_dispatch = nullptr; state.before_growth = &inner.root;
      verified &= AbortSignal::abort(&cx, &inner.root, 8) && inner.reasons(8) && checkpoint(&cx);
    }
    return verified && !state.live && !state.unowned && !state.premature_release && !state.early_publication;
  }
  if (is("fanout-repeated")) {
    state.limit = 1;
    state.on_dispatch = nullptr;
    for (int turn = 0; turn < 32; ++turn) {
      Graph next;
      state.before_growth = &next.root;
      if (!AbortSignal::abort(&cx, &next.root, 7) || !next.reasons(7) || !checkpoint(&cx)) return false;
    }
    return state.admitted == 32 && state.acknowledged == 32 && state.peak == 1 &&
           !state.live && !state.live_backings && !state.unowned && !state.premature_release;
  }
  const bool ok = AbortSignal::abort(&cx, &graph.root, 7);
  bool verified = false;
  if (is("fanout-refusal"))
    verified = !ok && cx.pending == 505 && graph.unchanged() && !state.dispatches &&
               !state.reserve_attempts && !state.admitted;
  else if (is("fanout-reserve-failure") || is("fanout-recovery")) {
    verified = !ok && cx.pending == 606 && graph.unchanged() && !state.dispatches &&
               state.admitted == 1 && state.live == 1 && !native::records.hasPhysical();
    if (is("fanout-recovery")) {
      state.fail_reserve = false; JS_ClearPendingException(&cx);
      verified &= AbortSignal::abort(&cx, &graph.root, 7) && graph.reasons(7) &&
                  state.admitted == 2 && state.peak == 1 && all_ready;
    }
  } else if (is("fanout-all-aborted")) {
    verified = ok && !cx.pending && state.dispatches == 1 && graph.root.reason == 7 &&
               !state.admitted && !state.reserve_attempts;
    for (const auto& signal : graph.dependents) verified &= signal.reason == 99 && signal.algorithms.size() == 1;
  } else if (is("fanout-first-error") || is("fanout-dependent-error") || is("fanout-success-with-error")) {
    const int first = is("fanout-dependent-error") ? graph.dependents[0].id : graph.root.id;
    verified = !ok && cx.pending == 404 && cx.stack == first && cx.status == 1 &&
               state.dispatches == 13 && graph.reasons(7) && !state.pending_entries && all_ready;
  } else if (is("fanout-trap") || is("fanout-error-then-trap")) {
    verified = !ok && cx.trapped && !cx.pending && !cx.stack && !cx.status &&
               state.dispatches == (is("fanout-trap") ? 1 : 2) && graph.reasons(7) && !state.pending_entries;
  } else if (is("fanout-inline") || is("fanout-heap") || is("fanout-ack-refusal")) {
    verified = ok && !cx.pending && callback_checked && all_ready && graph.reasons(7) &&
               state.dispatches == static_cast<int>(graph.count + 1) &&
               state.admitted == (is("fanout-inline") ? 0U : 1U);
  } else return false;
  if (is("fanout-ack-refusal")) {
    state.refuse_ack = true;
    verified &= !checkpoint(&cx) && state.live == 1 && native::records.hasRetained() &&
                !native::records.hasPhysical() && native::records.stopped();
    Graph later; state.before_growth = &later.root;
    JS_ClearPendingException(&cx);
    verified &= !AbortSignal::abort(&cx, &later.root, 7) && later.unchanged() && state.admitted == 1;
    state.refuse_ack = false;
  }
  JS_ClearPendingException(&cx);
  return checkpoint(&cx) && verified && !state.live && !state.live_backings &&
         !state.unowned && !state.premature_release && !state.early_publication;
}
// Additional engine-audit boundaries. These still model JS/GC and host imports;
// the real-engine harness is a separate qualification layer.
static bool audit_case(const char* selected) {
  const auto is = [selected](const char* name) { return std::strcmp(selected, name) == 0; };
  JSContext cx;
  size_t count = 9;
  if (is("audit-boundary-empty") || is("audit-default-growth")) count = 0;
  if (is("audit-boundary-inline")) count = 8;
  Graph graph(count);
  state.before_growth = &graph.root;
  bool verified = false;
  if (is("audit-entry-pending") || is("audit-already-pending") || is("audit-steps-entry-pending")) {
    if (is("audit-already-pending")) { graph.root.aborted = true; graph.root.reason = 73; }
    error(&cx, 0, 1234); // throwing undefined is pending, despite its value
    const bool result = is("audit-steps-entry-pending")
        ? AbortSignal::run_abort_steps(&cx, &graph.root)
        : AbortSignal::abort(&cx, &graph.root, 7);
    verified = !result && cx.pending == 0 && cx.stack == 1234 && cx.status == 1 &&
               !state.dispatches && state.order.empty() && !state.admitted &&
               graph.root.aborted == is("audit-already-pending");
  } else if (is("audit-steps-dispatch-pending")) {
    state.fail_dispatch = graph.root.id;
    state.success_with_exception = true;
    verified = !AbortSignal::run_abort_steps(&cx, &graph.root) && cx.pending == 404 &&
               cx.stack == graph.root.id && state.dispatches == 1;
  } else if (is("audit-algorithm-pending") || is("audit-algorithm-fatal")) {
    add(graph.root, 12); add(graph.root, 13);
    if (is("audit-algorithm-pending")) state.pending_algorithm = 12;
    else state.trap_algorithm = 12;
    const bool result = AbortSignal::abort(&cx, &graph.root, 7);
    verified = !result && graph.reasons(7) && !state.pending_entries;
    if (is("audit-algorithm-pending")) verified &= cx.pending == 202 && cx.stack == 12 &&
        cx.status == 1 && state.dispatches == 10 && graph.root.algorithms.size() == 1 &&
        graph.root.algorithms[0]->id == 12 &&
        std::find(state.order.begin(), state.order.end(), 13) != state.order.end();
    else verified &= !JS_IsExceptionPending(&cx) && cx.trapped && !state.dispatches &&
        graph.root.algorithms.size() == 2 && graph.root.algorithms[0]->id == 12 &&
        graph.root.algorithms[1]->id == 13 && state.order == std::vector<int>({11, 12});
  } else if (is("audit-first-oom") || is("audit-later-oom") || is("audit-undefined-exception") ||
             is("audit-oom-then-fatal") || is("audit-forced-return-after-error")) {
    state.on_dispatch = [&](JSContext* context, Signal* signal) {
      if (signal == &graph.root) {
        error(context, is("audit-undefined-exception") ? 0 : (is("audit-later-oom") ? 404 : 606),
              1234, is("audit-first-oom") || is("audit-oom-then-fatal") ? 2 : 1);
        return false;
      }
      if (signal == &graph.dependents[0]) {
        if (is("audit-oom-then-fatal") || is("audit-forced-return-after-error")) {
          context->trapped = true;
          if (is("audit-forced-return-after-error")) context->status = -1;
          return false;
        }
        error(context, is("audit-later-oom") ? 606 : 405, 9999, is("audit-later-oom") ? 2 : 1);
        return false;
      }
      return true;
    };
    const bool result = AbortSignal::abort(&cx, &graph.root, 7);
    verified = !result && graph.reasons(7) && !state.pending_entries;
    if (is("audit-oom-then-fatal") || is("audit-forced-return-after-error"))
      verified &= cx.trapped && !JS_IsExceptionPending(&cx) && !cx.stack && state.dispatches == 2 &&
                  cx.status == (is("audit-forced-return-after-error") ? -1 : 0);
    else verified &= cx.stack == 1234 && state.dispatches == 10 &&
        cx.pending == (is("audit-undefined-exception") ? 0 : (is("audit-later-oom") ? 404 : 606)) &&
        cx.status == (is("audit-first-oom") ? 2 : 1);
  } else if (is("audit-nested-dependent-error") || is("audit-nested-ack-refusal") ||
             is("audit-first-error-then-ack-refusal")) {
    Graph inner(9, 30);
    bool inner_result = false, inner_retained = false;
    const bool refuse = !is("audit-nested-dependent-error");
    if (is("audit-first-error-then-ack-refusal")) state.fail_dispatch = graph.root.id;
    state.on_dispatch = [&](JSContext* context, Signal* signal) {
      if (!refuse && signal == &inner.dependents[0]) { error(context, 808, 8080, 3); return false; }
      if (signal != &graph.dependents[0]) return true;
      state.before_growth = &inner.root;
      inner_result = AbortSignal::abort(context, &inner.root, 8);
      state.before_growth = &graph.root;
      if (!refuse) return inner_result;
      state.refuse_ack = true;
      const bool accepted = checkpoint(context);
      inner_retained = !accepted && state.live == 2 && state.live_backings == 1 &&
                       native::records.hasPhysical() && native::records.hasRetained();
      return accepted;
    };
    const bool result = AbortSignal::abort(&cx, &graph.root, 7);
    verified = !result && graph.reasons(7) && inner.reasons(8) && state.dispatches == 20 &&
               state.peak == 2 && !state.pending_entries;
    if (refuse) verified &= inner_result && inner_retained &&
        cx.pending == (is("audit-first-error-then-ack-refusal") ? 404 : 707) &&
        cx.stack == (is("audit-first-error-then-ack-refusal") ? graph.root.id : 7070) &&
        native::records.stopped() && state.live == 2 && !state.live_backings;
    else verified &= !inner_result && cx.pending == 808 && cx.stack == 8080 && cx.status == 3;
    state.refuse_ack = false;
  } else if (is("audit-graph-mutation")) {
    Signal late;
    late.id = 99; add(late, 991);
    state.on_dispatch = [&](JSContext* context, Signal* signal) {
      if (signal != &graph.root) return true;
      // The physical fan-out snapshot must retain removed dependents and not
      // grow when a callback mutates the source graph.
      graph.root.dependents.values.clear();
      graph.root.dependents.values.push_back(&late);
      return AbortSignal::abort(context, &graph.dependents[0], 99);
    };
    verified = AbortSignal::abort(&cx, &graph.root, 7) && graph.reasons(7) && !late.aborted &&
               late.algorithms.size() == 1 && state.dispatches == 10 && state.admitted == 1;
  } else if (is("audit-default-growth") || is("audit-default-shrink")) {
    state.on_reason = [&](JSContext*) {
      if (is("audit-default-growth")) {
        graph.count = 9;
        for (size_t i = 0; i < graph.count; ++i) {
          graph.dependents[i].id = 2 + static_cast<int>(i);
          add(graph.dependents[i], 21 + 10 * static_cast<int>(i));
          graph.root.dependents.values.push_back(&graph.dependents[i]);
        }
      } else { graph.root.dependents.values.pop_back(); graph.count = 8; }
    };
    const bool result = AbortSignal::abort(&cx, &graph.root, 0);
    verified = result && graph.reasons(101) && state.default_reasons == 1 &&
               state.dispatches == static_cast<int>(graph.count + 1) &&
               state.admitted == (is("audit-default-growth") ? 1U : 0U);
    if (is("audit-default-shrink")) verified &= !graph.dependents[8].aborted;
  } else if (is("audit-default-reentry-failure") || is("audit-default-reentry-fatal")) {
    bool inner_result = true;
    if (is("audit-default-reentry-failure")) state.fail_dispatch = graph.root.id;
    else state.trap_dispatch = graph.root.id;
    state.on_reason = [&](JSContext* context) { inner_result = AbortSignal::abort(context, &graph.root, 73); };
    const bool result = AbortSignal::abort(&cx, &graph.root, 0);
    verified = !result && !inner_result && graph.reasons(73) && state.admitted == 1 &&
               state.default_reasons == 1 && !state.pending_entries;
    if (is("audit-default-reentry-failure")) verified &= cx.pending == 404 && cx.stack == 1 &&
        state.dispatches == 10;
    else verified &= cx.trapped && !JS_IsExceptionPending(&cx) && state.dispatches == 1;
  } else if (is("audit-boundary-empty") || is("audit-boundary-inline") || is("audit-boundary-heap")) {
    verified = AbortSignal::abort(&cx, &graph.root, 7) && graph.reasons(7) &&
               state.dispatches == static_cast<int>(count + 1) &&
               state.admitted == (count > 8 ? 1U : 0U) &&
               state.live == state.admitted && !state.acknowledged &&
               !native::records.hasPhysical() && !state.live_backings;
  } else return false;
  JS_ClearPendingException(&cx);
  verified &= checkpoint(&cx) && state.live == 0 && !state.live_backings &&
              state.admitted == state.acknowledged && !state.unowned &&
              !state.premature_release && !state.early_publication;
  return verified;
}
static bool algorithm_custody_case(const char* selected) {
  const auto is = [selected](const char* value) { return std::strcmp(selected, value) == 0; };
  JSContext cx;
  Signal signal;
  signal.id = 1;
  for (int id = 1; id <= 6; ++id) {
    add(signal, id);
    if (!native::admit_native_object(&cx, signal.algorithms.back()->native_owner)) return false;
  }
  bool all_captures_live = true, reentry_ok = true;
  const bool fatal = is("algorithms-later-fatal");
  const bool ack_refusal = is("algorithms-ack-refusal");
  const bool event_failure = is("algorithms-event-failure");
  const bool undefined_error = is("algorithms-undefined-first");
  const bool oom_first = is("algorithms-oom-first");
  state.on_algorithm = [&](JSContext* context, int id) {
    // Earlier completed algorithms still physically exist throughout the drain.
    all_captures_live &= state.destroyed == 0 && state.live == 6;
    for (const auto& record : signal.algorithms) all_captures_live &= bool(record);
    reentry_ok &= AbortSignal::abort(context, &signal, 99) && signal.reason == 7;
    if (id == 2) { error(context, undefined_error ? 0 : 202, 2222, oom_first ? 2 : 1); return false; }
    if (id == 4) {
      if (fatal) { context->trapped = true; return false; }
      error(context, 606, 4444, 2); return false;
    }
    return true;
  };
  state.fail_event = event_failure;
  state.fail_dispatch = 1; // later catchable dispatch error must not replace #2
  const bool ok = AbortSignal::abort(&cx, &signal, 7);
  bool verified = !ok && all_captures_live && reentry_ok && !state.pending_entries;
  if (fatal) verified &= cx.trapped && !JS_IsExceptionPending(&cx) && !state.dispatches &&
      state.order == std::vector<int>({1,2,3,4}) && state.destroyed == 2;
  else verified &= cx.pending == (undefined_error ? 0 : 202) && cx.stack == 2222 &&
      cx.status == (oom_first ? 2 : 1) && state.destroyed == 4 &&
      state.order == (event_failure ? std::vector<int>({1,2,3,4,5,6}) : std::vector<int>({1,2,3,4,5,6,101}));
  std::vector<int> retained;
  for (const auto& algorithm : signal.algorithms) retained.push_back(algorithm->id);
  verified &= retained == (fatal ? std::vector<int>({2,4,5,6}) : std::vector<int>({2,4}));
  // These calls are explicit finite GC/host doubles, never an engine witness.
  JS_ClearPendingException(&cx);
  native::records.collectionCompleted();
  state.refuse_ack = ack_refusal;
  verified &= checkpoint(&cx) != ack_refusal && native::records.hasPhysical();
  if (ack_refusal) verified &= state.live == 6 && cx.pending == 707;
  else verified &= state.live == retained.size();
  state.refuse_ack = false;
  JS_ClearPendingException(&cx);
  verified &= checkpoint(&cx) && state.live == retained.size();
  signal.algorithms.clear();
  verified &= !native::records.hasPhysical() && state.live == retained.size();
  verified &= checkpoint(&cx) && state.live == retained.size(); // no collection invented
  native::records.collectionCompleted();
  verified &= checkpoint(&cx) && state.live == 0 && state.admitted == state.acknowledged &&
      state.destroyed == 6 && !state.premature_release;
  return verified;
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const char* selected = argv[1];
  bool passed = false;
  if (!std::strncmp(selected, "algorithms-", 11)) passed = algorithm_custody_case(selected);
  else if (!std::strncmp(selected, "audit-", 6)) passed = audit_case(selected);
  else if (!std::strncmp(selected, "fanout-", 7)) passed = fanout_case(selected);
  else {
    Signal root, first, second;
    root.id = 1; first.id = 2; second.id = 3;
    add(root, 11); add(root, 12); add(root, 13);
    if (!std::strcmp(selected, "already-aborted")) root.aborted = true;
    if (!std::strcmp(selected, "reason-failure")) state.fail_reason = true;
    if (!std::strcmp(selected, "event-failure")) state.fail_event = true;
    if (!std::strcmp(selected, "algorithm-failure")) state.fail_algorithm = 12;
    if (!std::strcmp(selected, "dispatch-failure") || !std::strcmp(selected, "dependent-continuation")) state.fail_dispatch = 1;
    if (!std::strcmp(selected, "dependent-continuation") || !std::strcmp(selected, "default-reason") ||
        !std::strcmp(selected, "explicit-reason")) {
      add(first, 21); add(first, 22); add(second, 31);
      root.dependents.values = {&first, &second};
    }
    JSContext cx;
    const bool omitted = !std::strcmp(selected, "default-reason") || !std::strcmp(selected, "reason-failure");
    const bool result = AbortSignal::abort(&cx, &root, omitted ? 0 : 1);
    const std::vector<int> root_work{11, 12, 13};
    if (!std::strcmp(selected, "success"))
      passed = result && root.aborted && state.order == std::vector<int>({11, 12, 13, 101}) &&
               state.destroyed == 3 && root.algorithms.empty() && state.dispatches == 1 && !cx.pending;
    else if (!std::strcmp(selected, "dispatch-failure"))
      passed = !result && root.aborted && state.order == std::vector<int>({11, 12, 13, 101}) &&
               state.destroyed == 3 && root.algorithms.empty() && state.dispatches == 1 && cx.pending == 404;
    else if (!std::strcmp(selected, "event-failure"))
      passed = !result && root.aborted && state.order == root_work && state.destroyed == 3 &&
               root.algorithms.empty() && !state.dispatches && !state.null_dereferences && cx.pending == 303;
    else if (!std::strcmp(selected, "reason-failure"))
      passed = !result && !root.aborted && state.order.empty() && !state.destroyed &&
               root.algorithms.size() == 3 && !state.dispatches && cx.pending == 101;
    else if (!std::strcmp(selected, "algorithm-failure"))
      passed = !result && root.aborted && state.order == std::vector<int>({11, 12, 13, 101}) &&
               state.destroyed == 2 && root.algorithms.size() == 1 && root.algorithms[0]->id == 12 &&
               state.dispatches == 1 && cx.pending == 202 && cx.stack == 12 && !state.pending_entries;
    else if (!std::strcmp(selected, "dependent-continuation"))
      passed = !result && root.aborted && first.aborted && second.aborted &&
               state.order == std::vector<int>({11, 12, 13, 101, 21, 22, 102, 31, 103}) &&
               state.destroyed == 6 && state.dispatches == 3 && cx.pending == 404 &&
               cx.stack == 1 && !state.pending_entries;
    else if (!std::strcmp(selected, "default-reason") || !std::strcmp(selected, "explicit-reason"))
      passed = result && root.aborted && first.aborted && second.aborted && root.reason != 0 &&
               first.reason == root.reason && second.reason == root.reason &&
               state.default_reasons == (!std::strcmp(selected, "default-reason") ? 1 : 0) &&
               state.order == std::vector<int>({11, 12, 13, 101, 21, 22, 102, 31, 103}) &&
               state.destroyed == 6 && state.dispatches == 3 && !cx.pending;
    else if (!std::strcmp(selected, "already-aborted"))
      passed = result && root.aborted && state.order.empty() && !state.destroyed &&
               root.algorithms.size() == 3 && !state.dispatches && !cx.pending;
    else return 2;
  }
  passed &= !state.invalid_root_order && state.active_roots == 0;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
