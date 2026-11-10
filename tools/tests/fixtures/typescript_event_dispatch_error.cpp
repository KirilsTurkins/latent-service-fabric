// Runs the emitted dispatch completion block with event/listener doubles.
// It does not qualify SpiderMonkey exceptions or an actual signed component.
#include <cstdio>
#include <cstring>

struct JSContext {};
static bool pending = false;
static bool JS_IsExceptionPending(JSContext*) { return pending; }
struct Target {};
enum class EventFlag { Dispatch, StopPropagation, StopImmediatePropagation, Canceled };
struct Event {
  enum class Phase { ACTIVE, NONE };
  Phase phase = Phase::ACTIVE;
  bool dispatch = true, stop = true, immediate = true, canceled = false;
  Target* current = nullptr;
  Target* related = nullptr;
  static void set_phase(Event* e, Phase value) { e->phase = value; }
  static void set_current_target(Event* e, Target* value) { e->current = value; }
  static void set_related_target(Event* e, Target* value) { e->related = value; }
  static void set_flag(Event* e, EventFlag flag, bool value) {
    if (flag == EventFlag::Dispatch) e->dispatch = value;
    else if (flag == EventFlag::StopPropagation) e->stop = value;
    else if (flag == EventFlag::StopImmediatePropagation) e->immediate = value;
  }
  static bool has_flag(Event* e, EventFlag flag) { return flag == EventFlag::Canceled && e->canceled; }
};
struct Result {
  bool set = false, value = false;
  void setBoolean(bool result) { set = true;value = result; }
};
static bool invoke_result = true;
static bool invoke_listeners(JSContext*, Target*, Event*) { return invoke_result; }

static bool finish_dispatch(Event* event, Result& rval) {
  JSContext* cx = nullptr;
  Target* target = event->current;
  // INSERT_EMITTED_DISPATCH_COMPLETION
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  Target target;
  Event event;
  event.current = event.related = &target;
  Result result;
  const char* selected = argv[1];
  invoke_result = std::strcmp(selected, "lookup-error-resets-dispatch") != 0;
  event.canceled = std::strcmp(selected, "success-preserves-canceled-result") == 0;
  pending = std::strcmp(selected, "success-pending-resets-dispatch") == 0;
  const bool returned = finish_dispatch(&event, result);
  const bool cleared = event.phase == Event::Phase::NONE && !event.dispatch && !event.stop &&
                       !event.immediate && event.current == nullptr && event.related == nullptr;
  bool passed;
  if (!std::strcmp(selected, "lookup-error-resets-dispatch") || pending)
    passed = !returned && !result.set && cleared;
  else if (!std::strcmp(selected, "success-resets-dispatch"))
    passed = returned && result.set && result.value && cleared;
  else if (!std::strcmp(selected, "success-preserves-canceled-result"))
    passed = returned && result.set && !result.value && cleared;
  else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
