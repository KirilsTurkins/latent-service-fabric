// Executes the emitted dispatch stop and cleanup blocks with finite listener
// doubles. This does not qualify SpiderMonkey GC or a signed component.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

struct Listener {
  bool once = false, removed = false, stop = false;
};
struct List {
  std::vector<std::shared_ptr<Listener>> values;
  template<class P> void eraseIf(P predicate) {
    values.erase(std::remove_if(values.begin(), values.end(), predicate), values.end());
  }
};
struct Target { List list; };
enum class EventFlag { StopImmediatePropagation };
struct Event {
  Target* target;
  bool stopped = false;
  static bool has_flag(Event* event, EventFlag) { return event->stopped; }
  static Target* current_target(Event* event) { return event->target; }
};
#define MOZ_ASSERT(condition) do { if (!(condition)) std::abort(); } while (false)
struct EventTarget {
  static bool is_instance(Target* target) { return target != nullptr; }
  static List* listeners(Target* target) { return &target->list; }
  static bool invoke(Target* target, unsigned& calls) {
    Event storage{target};
    Event* event = &storage;
    auto list = target->list.values; // original dispatch clones listener references
    bool listeners_removed = false;
    for (const auto& listener : list) {
      if (listener->removed) continue;
      if (listener->once) { listener->removed = true; listeners_removed = true; }
      ++calls;
      if (listener->stop) event->stopped = true;
      // INSERT_EMITTED_STOP_BLOCK
    }
    // INSERT_EMITTED_CLEANUP_BLOCK
    return true;
  }
};

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const char* selected = argv[1];
  Target target;
  auto first = std::make_shared<Listener>();
  first->once = std::strcmp(selected, "ordinary-stop-keeps-listeners") != 0;
  first->stop = std::strcmp(selected, "once-without-stop-cleans-up") != 0;
  std::weak_ptr<Listener> tracked = first;
  target.list.values.push_back(first);
  first.reset();
  auto later = std::make_shared<Listener>();
  target.list.values.push_back(later);
  unsigned calls = 0;
  const bool returned = EventTarget::invoke(&target, calls);
  bool passed;
  if (!std::strcmp(selected, "once-immediate-stop-retires-listener"))
    passed = returned && calls == 1 && tracked.expired() && target.list.values.size() == 1 &&
             target.list.values[0] == later;
  else if (!std::strcmp(selected, "once-without-stop-cleans-up"))
    passed = returned && calls == 2 && tracked.expired() && target.list.values.size() == 1 &&
             target.list.values[0] == later;
  else if (!std::strcmp(selected, "ordinary-stop-keeps-listeners"))
    passed = returned && calls == 1 && !tracked.expired() && target.list.values.size() == 2;
  else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
