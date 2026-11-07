// Exercises the emitted invoke_listeners with finite doubles and the real
// native retirement header. This is not SpiderMonkey or guest qualification.
#include "native_retirement.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>
#include <type_traits>

struct JSContext {};
struct Owner { unsigned id = 0; bool live = false; };
using Records = lsf::typescript::activation::NativeRetirement<Owner>;
using Lease = lsf::typescript::activation::NativeLease<Records>;
using FrameLease = lsf::typescript::activation::NativeFrameLease<Records>;
static_assert(!std::is_copy_constructible_v<FrameLease>);
static_assert(!std::is_move_constructible_v<FrameLease>);

struct State {
  Records records;
  Records::Record* pointers[32]{};
  bool live[32]{};
  bool buffers[32]{};
  unsigned next = 0, live_count = 0, limit = 2, last_admitted = 0;
  unsigned admits = 0, allocations = 0, frees = 0, acknowledgements = 0;
  unsigned outer_callbacks = 0, inner_callbacks = 0;
  bool ordering_error = false, reserve_failure = false, reject_ack = false;
  bool nested = false, nested_started = false, observed_nested = false;
  bool callback_failure = false;
  const char* error = nullptr;

  bool acknowledge(Owner& owner) {
    if (reject_ack) return false;
    if (!owner.live || !live[owner.id] || buffers[owner.id]) { ordering_error = true; return false; }
    live[owner.id] = false;
    pointers[owner.id] = nullptr;
    --live_count;
    ++acknowledgements;
    owner.live = false;
    return true;
  }
  bool checkpoint() { return records.checkpoint([this](Owner& owner) { return acknowledge(owner); }); }
  bool admit(Lease& lease) {
    ++admits;
    if (records.stopped() || !checkpoint() || live_count >= limit) { error = "admission"; return false; }
    const auto id = ++next;
    if (id >= 32 || !records.track({id, true}, pointers[id]) || !lease.bind(pointers[id])) return false;
    live[id] = true;
    ++live_count;
    last_admitted = id;
    return true;
  }
};
static State state;

namespace lsf::typescript::activation {
using NativeObjectFrameLease = FrameLease;
bool admit_native_object(JSContext*, Lease& lease) { return state.admit(lease); }
}

using ListenerRef = unsigned;
struct ListenerList {
  std::array<ListenerRef, 32> values{};
  size_t count = 0;
  size_t length() const { return count; }
  auto begin() { return values.begin(); }
  auto end() { return values.begin() + static_cast<std::ptrdiff_t>(count); }
};
struct Object { ListenerList list; bool inner = false; };
using HandleObject = Object*;

namespace JS {
template<class T> class RootedVector {
  std::array<T, 8> inline_{};
  std::unique_ptr<T[]> heap_;
  size_t length_ = 0;
  unsigned owner_ = 0;
public:
  explicit RootedVector(JSContext*) {}
  size_t capacity() const { return inline_.size(); }
  bool reserve(size_t length) {
    if (length <= capacity()) return true;
    if (state.reserve_failure) { state.error = "reserve"; return false; }
    owner_ = state.last_admitted;
    state.last_admitted = 0;
    if (!owner_ || !state.live[owner_] || !state.pointers[owner_]->physical) state.ordering_error = true;
    heap_.reset(new (std::nothrow) T[length]);
    if (!heap_) return false;
    if (owner_) state.buffers[owner_] = true;
    ++state.allocations;
    return true;
  }
  void infallibleAppend(T item) { (heap_ ? heap_.get() : inline_.data())[length_++] = item; }
  size_t length() const { return length_; }
  ~RootedVector() {
    if (heap_) {
      if (!owner_ || !state.pointers[owner_] || !state.pointers[owner_]->physical) state.ordering_error = true;
      heap_.reset();
      if (owner_) state.buffers[owner_] = false;
      ++state.frees;
    }
  }
};
}
enum class EventFlag { StopPropagation };
struct Event {
  enum class Phase { AT_TARGET };
  static void set_phase(Object*, Phase) {}
  static void set_target(Object*, Object*) {}
  static void set_related_target(Object*, Object*) {}
  static void set_current_target(Object*, Object*) {}
  static bool has_flag(Object*, EventFlag) { return false; }
};
#define MOZ_ASSERT(value) assert(value)
struct EventTarget {
  static bool is_instance(Object*) { return true; }
  static ListenerList* listeners(Object* target) { return &target->list; }
  static bool invoke_listeners(JSContext*, HandleObject, HandleObject);
  static bool inner_invoke(JSContext*, HandleObject, JS::RootedVector<ListenerRef>&, bool*);
};

// INSERT_EMITTED_INVOKE_LISTENERS

static Object* active_target = nullptr;
bool EventTarget::inner_invoke(JSContext* cx, HandleObject event,
                               JS::RootedVector<ListenerRef>& listeners, bool* found) {
  *found = listeners.length() != 0;
  for (size_t i = 0; i < listeners.length(); ++i) {
    if (event->inner) {
      ++state.inner_callbacks;
      if (state.nested && state.live_count == 2 && state.buffers[1] && state.buffers[2])
        state.observed_nested = true;
    } else {
      ++state.outer_callbacks;
      if (state.nested && !state.nested_started) {
        state.nested_started = true;
        Object inner;
        inner.inner = true;
        if (!invoke_listeners(cx, active_target, &inner)) return false;
      }
      if (state.callback_failure) { state.error = "callback"; return false; }
    }
  }
  return true;
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const char* selected = argv[1];
  Object target, event;
  target.list.count = !std::strcmp(selected, "inline") ? 8 : 9;
  active_target = &target;
  JSContext cx;
  std::unique_ptr<Lease> existing;
  Records::Record* existing_record = nullptr;
  if (!std::strcmp(selected, "refusal")) {
    state.limit = 1;
    existing = std::make_unique<Lease>();
    if (!state.records.track({1, true}, existing_record) || !existing->bind(existing_record)) return 3;
    state.next = 1; state.live[1] = true; state.live_count = 1; state.pointers[1] = existing_record;
  }
  if (!std::strcmp(selected, "gc-object-not-retired")) {
    Lease gc_owned;
    if (!state.records.track({1, true}, existing_record) || !gc_owned.bind(existing_record)) return 3;
    state.next = 1; state.live[1] = true; state.live_count = 1; state.pointers[1] = existing_record;
  }
  if (!std::strcmp(selected, "repeated")) state.limit = 1;
  if (!std::strcmp(selected, "reserve-failure")) state.reserve_failure = true;
  if (!std::strcmp(selected, "nested") || !std::strcmp(selected, "nested-refusal")) state.nested = true;
  if (!std::strcmp(selected, "nested-refusal")) state.limit = 1;
  if (!std::strcmp(selected, "callback-failure")) state.callback_failure = true;
  const bool result = EventTarget::invoke_listeners(&cx, &target, &event);
  bool repeated_result = false;
  bool first_waited_for_checkpoint = false;
  if (!std::strcmp(selected, "repeated")) {
    first_waited_for_checkpoint = state.live_count == 1 && !state.acknowledgements &&
                                  state.pointers[1] && !state.pointers[1]->physical &&
                                  state.pointers[1]->collection_completed;
    repeated_result = EventTarget::invoke_listeners(&cx, &target, &event);
  }
  bool passed = false;
  if (!std::strcmp(selected, "inline"))
    passed = result && state.outer_callbacks == 8 && !state.admits && !state.allocations;
  else if (!std::strcmp(selected, "heap"))
    passed = result && state.outer_callbacks == 9 && state.admits == 1 && state.allocations == 1 &&
             state.frees == 1 && state.live_count == 1 && !state.acknowledgements &&
             !state.pointers[1]->physical && state.pointers[1]->collection_completed;
  else if (!std::strcmp(selected, "refusal"))
    passed = !result && state.error && !std::strcmp(state.error, "admission") && !state.outer_callbacks &&
             !state.allocations && !state.acknowledgements && state.live_count == 1 && existing_record->physical;
  else if (!std::strcmp(selected, "reserve-failure"))
    passed = !result && state.error && !std::strcmp(state.error, "reserve") && !state.outer_callbacks &&
             !state.allocations && state.live_count == 1 && !state.pointers[1]->physical &&
             state.pointers[1]->collection_completed && !state.acknowledgements;
  else if (!std::strcmp(selected, "nested"))
    passed = result && state.observed_nested && state.outer_callbacks == 9 && state.inner_callbacks == 9 &&
             state.admits == 2 && state.allocations == 2 && state.frees == 2 && state.live_count == 2 &&
             !state.acknowledgements && !state.pointers[1]->physical && !state.pointers[2]->physical;
  else if (!std::strcmp(selected, "nested-refusal"))
    passed = !result && state.error && !std::strcmp(state.error, "admission") && state.outer_callbacks == 1 &&
             !state.inner_callbacks && state.admits == 2 && state.allocations == 1 && state.frees == 1 &&
             state.live_count == 1 && !state.acknowledgements && !state.pointers[1]->physical;
  else if (!std::strcmp(selected, "repeated"))
    passed = result && first_waited_for_checkpoint && repeated_result && state.outer_callbacks == 18 &&
             state.admits == 2 && state.allocations == 2 && state.frees == 2 && state.acknowledgements == 1 &&
             !state.live[1] && state.live[2] && !state.pointers[2]->physical &&
             state.pointers[2]->collection_completed;
  else if (!std::strcmp(selected, "gc-object-not-retired")) {
    passed = result && state.live_count == 2 && !existing_record->physical &&
             !existing_record->collection_completed && !state.pointers[2]->physical &&
             state.pointers[2]->collection_completed && !state.acknowledgements;
    passed = passed && state.checkpoint() && state.acknowledgements == 1 && state.live[1] &&
             !state.live[2] && !existing_record->collection_completed;
    state.records.collectionCompleted();
  }
  else if (!std::strcmp(selected, "callback-failure"))
    passed = !result && state.error && !std::strcmp(state.error, "callback") && state.outer_callbacks == 1 &&
             state.allocations == 1 && state.frees == 1 && state.live_count == 1 && !state.acknowledgements;
  else if (!std::strcmp(selected, "ack-refusal")) {
    state.reject_ack = true;
    passed = result && state.live_count == 1 && !state.checkpoint() && state.records.stopped() &&
             state.records.hasRetained() && state.live[1] && !state.acknowledgements;
    Lease denied;
    passed = passed && !state.admit(denied) && state.next == 1;
    state.reject_ack = false;
  } else return 2;
  if (std::strcmp(selected, "refusal"))
    passed = passed && state.checkpoint() && !state.live_count && !state.records.hasRetained();
  else {
    passed = passed && state.checkpoint() && state.live_count == 1 && existing_record->physical;
    existing.reset();
    state.records.collectionCompleted();
    passed = passed && state.checkpoint() && !state.live_count && !state.records.hasRetained();
  }
  passed = passed && !state.ordering_error;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
