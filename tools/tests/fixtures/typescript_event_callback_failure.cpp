// Execute the complete emitted inner_invoke body, including both JS::Call
// results. These are finite JS/event doubles, not an engine qualification.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

struct JSContext { int pending = 0; };
struct JSObject {
  bool callable = true, fatal = false, throws = false, success_pending = false;
  bool getter_failure = false, getter_pending = false;
};
struct Value { JSObject* object = nullptr; JSObject& toObject() const { return *object; } };
struct RootedValue : Value {
  explicit RootedValue(JSContext*) {}
  RootedValue(JSContext*, Value value) : Value(value) {}
};
struct RootedObject {
  JSObject* object;
  RootedObject(JSContext*, JSObject* value) : object(value) {}
  operator JSObject*() const { return object; }
};
struct RootedString {
  const char* value;
  RootedString(JSContext*, const char* selected) : value(selected) {}
};
struct Event;
struct Argument { void setObject(Event&) {} };
template<size_t N> using RootedValueArrayBase = std::array<Argument, N>;
template<size_t N> struct RootedValueArray : RootedValueArrayBase<N> {
  explicit RootedValueArray(JSContext*) {}
};
static int calls = 0, reports = 0, pending_entries = 0, wrong_receivers = 0;
static int steal_mode = 0, report_mode = 0, report_side_effects = 0;
static JSObject* expected_target = nullptr;
static JSObject* receiver_object(JSObject* object) { return object; }
static JSObject* receiver_object(Value value) { return value.object; }
static bool JS_IsExceptionPending(JSContext* cx) { return cx->pending != 0; }
static void JS_ClearPendingException(JSContext* cx) { cx->pending = 0; }
static bool JS_GetProperty(JSContext* cx, JSObject* object, const char*, RootedValue* value) {
  if (object->getter_failure || object->getter_pending) cx->pending = 7;
  value->object = object;
  return !object->getter_failure;
}
namespace JS {
struct ExceptionStack { explicit ExceptionStack(JSContext*) {} };
inline bool StealPendingExceptionStack(JSContext* cx, ExceptionStack*) {
  JS_ClearPendingException(cx);
  if (steal_mode >= 2) cx->pending = 11;
  return steal_mode == 0 || steal_mode == 3;
}
struct ErrorReportBuilder {
  enum SniffingBehavior { WithSideEffects, NoSideEffects };
  explicit ErrorReportBuilder(JSContext*) {}
  bool init(JSContext* cx, const ExceptionStack&, SniffingBehavior behavior) {
    if (cx->pending) ++pending_entries;
    if (behavior != NoSideEffects) ++report_side_effects;
    if (report_mode >= 2) cx->pending = 12;
    return report_mode == 0 || report_mode == 3;
  }
};
inline void PrintError(FILE*, const ErrorReportBuilder&, bool) { ++reports; }
template<class T> using HandleVector = const std::vector<T>&;
static bool IsCallable(JSObject* object) { return object->callable; }
template<class Receiver, class Args>
bool Call(JSContext* cx, const Receiver& receiver, Value function, const Args&, RootedValue*) {
  if (receiver_object(receiver) != (function.object->callable ? expected_target : function.object))
    ++wrong_receivers;
  ++calls;
  if (cx->pending) ++pending_entries;
  if (function.object->fatal) return false;
  if (function.object->throws || function.object->success_pending) cx->pending = 8;
  return !function.object->throws;
}
}
namespace core { static const char* encode(JSContext*, RootedString value) { return value.value; } }
namespace api {
struct Engine {
  JSObject global_object;
  JSContext* cx = nullptr;
  static Engine* get(JSContext* cx) { static Engine engine; engine.cx = cx; return &engine; }
  JSObject* global() { return &global_object; }
  void dump_pending_exception(const char*) {
    JS::ExceptionStack exception(cx);
    if (!JS::StealPendingExceptionStack(cx, &exception)) return;
    JS::ErrorReportBuilder report(cx);
    if (!report.init(cx, exception, JS::ErrorReportBuilder::WithSideEffects)) return;
    JS::PrintError(stderr, report, false);
  }
};
}
struct Listener {
  bool removed = false, once = true, passive = true, capture = false;
  std::string type = "abort";
  Value callback;
};
using ListenerRef = std::shared_ptr<Listener>;
struct List {
  std::vector<ListenerRef> values;
  template<class Predicate> void eraseIf(Predicate predicate) {
    values.erase(std::remove_if(values.begin(), values.end(), predicate), values.end());
  }
};
struct Target : JSObject { List list; };
enum class EventFlag { InPassiveListener, StopImmediatePropagation };
struct Event {
  using EventFlag = ::EventFlag;
  Target* target;
  bool passive = false, stopped = false;
  static const char* type(Event*) { return "abort"; }
  static Target* current_target(Event* event) { return event->target; }
  static bool has_flag(Event* event, EventFlag flag) {
    return flag == EventFlag::InPassiveListener ? event->passive : event->stopped;
  }
  static void set_flag(Event* event, EventFlag flag, bool value) {
    if (flag == EventFlag::InPassiveListener) event->passive = value;
    else event->stopped = value;
  }
};
using HandleObject = Event*;
#define MOZ_ASSERT(value) assert(value)
struct EventTarget {
  static bool is_instance(Target* target) { return target != nullptr; }
  static List* listeners(Target* target) { return &target->list; }
  static bool inner_invoke(JSContext*, HandleObject, JS::HandleVector<ListenerRef>, bool*);
};

// INSERT_EMITTED_INNER_INVOKE

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const auto is = [&](const char* name) { return std::strcmp(argv[1], name) == 0; };
  JSContext cx;
  JSObject first, second;
  first.callable = !is("object-fatal") && !is("getter-failure") && !is("getter-pending");
  first.fatal = is("function-fatal") || is("object-fatal");
  steal_mode = is("steal-fatal") ? 1 : is("steal-error") ? 2 : is("steal-success-pending") ? 3 : 0;
  report_mode = is("report-fatal") ? 1 : is("report-error") ? 2 : is("report-success-pending") ? 3 : 0;
  first.throws = is("catchable-continues") || is("report-no-script") || steal_mode || report_mode;
  first.success_pending = is("success-pending-reported");
  first.getter_failure = is("getter-failure");
  first.getter_pending = is("getter-pending");
  if (is("entry-pending")) cx.pending = 9;
  Target target;
  expected_target = &target;
  for (auto* callback : {&first, &second}) {
    auto listener = std::make_shared<Listener>();
    listener->callback.object = callback;
    target.list.values.push_back(std::move(listener));
  }
  std::weak_ptr<Listener> first_record = target.list.values[0];
  Event event{&target};
  bool found = false, result;
  {
    const auto clone = target.list.values;
    result = EventTarget::inner_invoke(&cx, &event, clone, &found);
  }
  bool passed = !event.passive && !pending_entries;
  if (steal_mode || report_mode) {
    const int mode = steal_mode ? steal_mode : report_mode;
    passed &= !result && cx.pending == (mode >= 2 ? (steal_mode ? 11 : 12) : 0) &&
      calls == 1 && reports == 0 && !report_side_effects && target.list.values.size() == 1 && first_record.expired();
  }
  else if (first.fatal) passed &= !result && !cx.pending && calls == 1 && reports == 0 &&
      target.list.values.size() == 1 && first_record.expired();
  else if (first.getter_failure || first.getter_pending) passed &= !result && cx.pending == 7 &&
      calls == 0 && reports == 0 && target.list.values.size() == 1 && first_record.expired();
  else if (is("entry-pending")) passed &= !result && cx.pending == 9 && !found && calls == 0 &&
      reports == 0 && target.list.values.size() == 2 && !first_record.expired();
  else if (is("success") || is("function-receiver") || first.throws || first.success_pending) {
    passed &= result && !cx.pending && found && calls == 2 &&
      reports == ((first.throws || first.success_pending) ? 1 : 0) && target.list.values.empty();
    if (is("function-receiver")) passed &= !wrong_receivers;
    if (is("report-no-script")) passed &= !report_side_effects;
  }
  else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              argv[1], passed ? "true" : "false");
  return passed ? 0 : 1;
}
