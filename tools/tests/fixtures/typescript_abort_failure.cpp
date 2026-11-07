// Executes the emitted abort and abort-steps functions with bounded doubles.
// It is not a SpiderMonkey, GC, provider, or signed-component qualification.
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

struct JSContext { int pending = 0; };
struct State {
  std::vector<int> order;
  int destroyed = 0, dispatches = 0, null_dereferences = 0;
  int fail_algorithm = 0, fail_dispatch = 0;
  bool fail_reason = false, fail_event = false;
};
static State state;

struct Algorithm {
  int id;
  explicit Algorithm(int value) : id(value) {}
  ~Algorithm() { ++state.destroyed; }
  bool run(JSContext* cx) {
    state.order.push_back(id);
    if (state.fail_algorithm == id) { cx->pending = 202; return false; }
    return true;
  }
};
struct Signal;
struct WeakIndexSet {
  std::vector<Signal*> values;
  std::vector<Signal*>& items() { return values; }
};
struct Signal {
  int id = 0;
  bool aborted = false;
  WeakIndexSet dependents;
  std::vector<std::unique_ptr<Algorithm>> algorithms;
};
using HandleObject = Signal*;
using HandleValue = int;
struct RootedObject {
  Signal* object;
  RootedObject(JSContext*, Signal* value) : object(value) {}
  operator Signal*() const { return object; }
  explicit operator bool() const { return object != nullptr; }
  Signal& operator*() const {
    if (!object) { ++state.null_dereferences; static Signal fallback; return fallback; }
    return *object;
  }
};
struct RootedValue {
  explicit RootedValue(JSContext*) {}
  RootedValue(JSContext*, int) {}
};
namespace JS {
struct RootedObjectVector {
  std::vector<Signal*> values;
  explicit RootedObjectVector(JSContext*) {}
  bool append(RootedObject value) { values.push_back(value); return true; }
  bool empty() const { return values.empty(); }
  auto begin() { return values.begin(); }
  auto end() { return values.end(); }
};
constexpr int NullHandleValue = 0;
int StringValue(int) { return 0; }
int ObjectValue(Signal&) { return 0; }
}
struct Event {
  static Signal* create(JSContext* cx, RootedValue&, int) {
    if (state.fail_event) { cx->pending = 303; return nullptr; }
    static Signal event;
    return &event;
  }
};
struct EventTarget {
  static bool dispatch_event(JSContext* cx, Signal* signal, RootedValue&, RootedValue*) {
    ++state.dispatches;
    state.order.push_back(100 + signal->id);
    if (state.fail_dispatch == signal->id) { cx->pending = 404; return false; }
    return true;
  }
};
#define MOZ_ASSERT(value) assert(value)
struct AbortSignal {
  static int abort_type_atom;
  static bool is_instance(Signal* signal) { return signal != nullptr; }
  static bool is_aborted(Signal* signal) { return signal->aborted; }
  static bool set_reason(JSContext* cx, Signal* signal, int) {
    if (state.fail_reason) { cx->pending = 101; return false; }
    signal->aborted = true;
    return true;
  }
  static WeakIndexSet* dependent_signals(Signal* signal) { return &signal->dependents; }
  static std::vector<std::unique_ptr<Algorithm>>* algorithms(Signal* signal) {
    return &signal->algorithms;
  }
  static bool abort(JSContext*, HandleObject, HandleValue);
  static bool run_abort_steps(JSContext*, HandleObject);
};
int AbortSignal::abort_type_atom = 1;

// INSERT_EMITTED_ABORT_FUNCTION

// INSERT_EMITTED_ABORT_STEPS_FUNCTION

static void add(Signal& signal, int id) { signal.algorithms.push_back(std::make_unique<Algorithm>(id)); }
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const char* selected = argv[1];
  Signal root, first, second;
  root.id = 1; first.id = 2; second.id = 3;
  add(root, 11); add(root, 12); add(root, 13);
  if (!std::strcmp(selected, "already-aborted")) root.aborted = true;
  if (!std::strcmp(selected, "reason-failure")) state.fail_reason = true;
  if (!std::strcmp(selected, "event-failure")) state.fail_event = true;
  if (!std::strcmp(selected, "algorithm-failure")) state.fail_algorithm = 12;
  if (!std::strcmp(selected, "dispatch-failure") || !std::strcmp(selected, "dependent-continuation"))
    state.fail_dispatch = 1;
  if (!std::strcmp(selected, "dependent-continuation")) {
    add(first, 21); add(first, 22); add(second, 31);
    root.dependents.values = {&first, &second};
  }
  JSContext cx;
  const bool result = AbortSignal::abort(&cx, &root, 1);
  bool passed = false;
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
    passed = !result && root.aborted && state.order == std::vector<int>({11, 12}) && !state.destroyed &&
             root.algorithms.size() == 3 && !state.dispatches && cx.pending == 202;
  else if (!std::strcmp(selected, "dependent-continuation"))
    passed = result && root.aborted && first.aborted && second.aborted &&
             state.order == std::vector<int>({11, 12, 13, 101, 21, 22, 102, 31, 103}) &&
             state.destroyed == 6 && state.dispatches == 3 && cx.pending == 404;
  else if (!std::strcmp(selected, "already-aborted"))
    passed = result && root.aborted && state.order.empty() && !state.destroyed &&
             root.algorithms.size() == 3 && !state.dispatches && !cx.pending;
  else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
