// Executes the emitted create_with_signals transaction. Finite allocation/GC
// doubles test backlink publication, not real engine collection or byte costs.
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <type_traits>
#include <vector>
#if __cplusplus < 202302L
namespace std { template<class T> constexpr underlying_type_t<T> to_underlying(T v) { return static_cast<underlying_type_t<T>>(v); } }
#endif
struct Signal;
using JSObject = Signal;
struct JSContext { bool pending = false; };
struct Control { int stage = 0, reserves = 0, fail_stage = 0, fail_reserve = 0; bool stage_failed = false; };
static Control control;
struct WeakVec {
  std::vector<Signal*> entries;
  bool backlinks = false;
  auto begin() { return entries.begin(); }
  auto end() { return entries.end(); }
  size_t length() const { return entries.size(); }
  bool reserve(size_t n) {
    if (backlinks && ++control.reserves == control.fail_reserve) return false;
    entries.reserve(n); return true;
  }
  void infallibleAppend(Signal* value) { assert(entries.size() < entries.capacity()); entries.push_back(value); }
};
struct WeakIndexSet {
  WeakVec value;
  bool staged = false;
  bool insert(Signal* signal) {
    if (std::find(value.begin(), value.end(), signal) != value.end()) return true;
    if (staged && ++control.stage == control.fail_stage) { control.stage_failed = true; return false; }
    if (!value.reserve(value.length() + 1)) return false;
    value.infallibleAppend(signal); return true;
  }
  WeakVec& items() { return value; }
};
struct Signal { bool aborted = false, dependent = false; int reason = 0; WeakIndexSet sources, dependents; };
struct Value { Signal* object; Signal& toObject() const { return *object; } };
struct HandleValueArray {
  const std::vector<Value>& values;
  size_t length() const { return values.size(); }
  const Value& operator[](size_t i) const { return values[i]; }
};
struct RootedObject {
  Signal* object;
  RootedObject(JSContext*, Signal* obj) : object(obj) {}
  operator Signal*() const { return object; }
  explicit operator bool() const { return object; }
  Signal* get() const { return object; }
};
static std::unique_ptr<Signal> result_signal;
static bool JS_IsExceptionPending(JSContext* cx) { return cx->pending; }
static void JS_ReportOutOfMemory(JSContext* cx) { cx->pending = true; }
namespace JS { [[maybe_unused]] static bool TrueValue() { return true; } }
struct AbortSignal {
  enum class Slots { Reason, Dependent };
  static Signal* create(JSContext*) {
    result_signal = std::make_unique<Signal>(); result_signal->sources.staged = true;
    return result_signal.get();
  }
  static bool is_aborted(Signal* signal) { return signal->aborted; }
  static bool is_dependent(Signal* signal) { return signal->dependent; }
  static int reason(Signal* signal) { return signal->reason; }
  static WeakIndexSet* source_signals(Signal* signal) { return &signal->sources; }
  static WeakIndexSet* dependent_signals(Signal* signal) { return &signal->dependents; }
  static Signal* create_with_signals(JSContext*, HandleValueArray);
};
static void SetReservedSlot(Signal* signal, int slot, int value) {
  if (slot == std::to_underlying(AbortSignal::Slots::Reason)) { signal->reason = value; signal->aborted = true; }
  else signal->dependent = value != 0;
}
#define MOZ_ASSERT(x) assert(x)
// INSERT_EMITTED_GRAPH_CREATION
int main(int argc, char** argv) {
  if (argc < 2) return 2;
  const bool stage_failure = !std::strcmp(argv[1], "stage-failure");
  const bool reserve_failure = !std::strcmp(argv[1], "reserve-failure");
  const bool early_abort = !std::strcmp(argv[1], "already-aborted");
  const bool empty = !std::strcmp(argv[1], "empty");
  const bool pending = !std::strcmp(argv[1], "entry-pending");
  const int fail_at = argc == 3 ? std::atoi(argv[2]) : 0;
  Signal roots[9], existing, nested;
  nested.dependent = true;
  std::vector<Value> inputs;
  for (auto& root : roots) {
    root.dependents.value.backlinks = true;
    root.dependents.value.entries.push_back(&existing);
    nested.sources.value.entries.push_back(&root);
    if (!empty) inputs.push_back({&root});
  }
  if (!empty) { inputs.push_back({&nested}); inputs.push_back({&roots[0]}); }
  if (early_abort) { roots[3].aborted = true; roots[3].reason = 37; roots[6].aborted = true; roots[6].reason = 67; }
  control.fail_stage = stage_failure ? fail_at : 0;
  control.fail_reserve = reserve_failure ? fail_at : 0;
  JSContext cx{pending};
  auto* result = AbortSignal::create_with_signals(&cx, {inputs});
  bool passed = true;
  if (stage_failure || reserve_failure || pending) {
    passed &= !result && cx.pending;
    for (auto& root : roots) passed &= root.dependents.value.entries == std::vector<Signal*>{&existing};
    if (stage_failure) passed &= control.stage_failed && !control.reserves;
    if (pending) passed &= !result_signal && !control.stage && !control.reserves;
  } else if (early_abort) {
    passed &= result && !cx.pending && result->aborted && result->reason == 37 && !control.stage && !control.reserves;
    for (auto& root : roots) passed &= root.dependents.value.entries == std::vector<Signal*>{&existing};
  } else {
    passed &= result && !cx.pending && result->dependent && result->sources.value.length() == (empty ? 0U : 9U);
    passed &= control.stage == (empty ? 0 : 9) && control.reserves == (empty ? 0 : 9);
    for (auto& root : roots) passed &= root.dependents.value.entries == (empty ? std::vector<Signal*>{&existing} : std::vector<Signal*>{&existing, result});
  }
  std::printf("{\"case\":\"%s\",\"position\":%d,\"passed\":%s,\"engineQualified\":false}\n",argv[1],fail_at,passed?"true":"false");
  return passed ? 0 : 1;
}
