// Executes the emitted AbortSignal::any with finite doubles and the real
// retirement header. This does not qualify SpiderMonkey or a signed guest.
#include "native_retirement.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>

struct JSContext {};
struct JSObject { bool signal = true; };
struct Owner { unsigned id = 0; bool live = false; };
using Records = lsf::typescript::activation::NativeRetirement<Owner>;
using Lease = lsf::typescript::activation::NativeLease<Records>;
using FrameLease = lsf::typescript::activation::NativeFrameLease<Records>;

struct State {
  Records records;
  Records::Record* pointers[64]{};
  bool live[64]{};
  unsigned buffers[64]{};
  unsigned next = 0, last_admitted = 0, live_count = 0, limit = 2;
  unsigned admissions = 0, allocations = 0, frees = 0, acknowledgements = 0;
  unsigned calls = 0, close_calls = 0, return_reentries = 0, created = 0;
  unsigned max_buffers = 0, allocation_failure = 0;
  bool ordering_error = false, nested_seen = false, nested_started = false, close_saw_owner = false;
  bool return_reentry = false, return_threw = false;
  bool uncatchable = false;
  const char* error = nullptr;

  bool acknowledge(Owner& owner) {
    if (!owner.live || !live[owner.id] || buffers[owner.id]) {
      ordering_error = true;
      return false;
    }
    live[owner.id] = false;
    pointers[owner.id] = nullptr;
    --live_count;
    ++acknowledgements;
    owner.live = false;
    return true;
  }
  bool checkpoint() { return records.checkpoint([this](Owner& owner) { return acknowledge(owner); }); }
  bool admit(Lease& lease) {
    ++admissions;
    if (records.stopped() || !checkpoint() || live_count >= limit) {
      error = uncatchable ? nullptr : "admission";
      return false;
    }
    const auto id = ++next;
    if (id >= 64 || !records.track({id, true}, pointers[id]) || !lease.bind(pointers[id])) {
      error = "record";
      return false;
    }
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

struct Input { size_t count; size_t invalid_at; bool nested; unsigned depth; };
static bool invoke(JSContext* cx, Input& input);

namespace JS {
struct Value {
  JSObject* object = nullptr;
  Input* input = nullptr;
  bool isObject() const { return object != nullptr; }
  JSObject& toObject() const { return *object; }
};
struct RootedValue : Value {
  explicit RootedValue(JSContext*) {}
};
class RootedValueVector {
  std::array<Value, 8> inline_{};
  std::unique_ptr<Value[]> heap_;
  size_t length_ = 0, capacity_ = 8;
  unsigned owner_ = 0;
public:
  explicit RootedValueVector(JSContext*) {}
  size_t length() const { return length_; }
  size_t capacity() const { return capacity_; }
  bool append(const Value& value) {
    if (length_ == capacity_) {
      if (!owner_) { owner_ = state.last_admitted; state.last_admitted = 0; }
      if (!owner_ || !state.live[owner_] || !state.pointers[owner_]->physical) state.ordering_error = true;
      if (state.allocation_failure && state.allocations + 1 == state.allocation_failure) return false;
      auto grown = std::unique_ptr<Value[]>(new (std::nothrow) Value[capacity_ * 2]);
      if (!grown) return false;
      ++state.allocations;
      if (owner_) {
        ++state.buffers[owner_];
        if (state.buffers[owner_] > state.max_buffers) state.max_buffers = state.buffers[owner_];
      }
      const auto* old = heap_ ? heap_.get() : inline_.data();
      for (size_t i = 0; i < length_; ++i) grown[i] = old[i];
      if (heap_) {
        heap_.reset();
        if (owner_) --state.buffers[owner_];
        ++state.frees;
      }
      heap_ = std::move(grown);
      capacity_ *= 2;
    }
    (heap_ ? heap_.get() : inline_.data())[length_++] = value;
    return true;
  }
  ~RootedValueVector() {
    if (heap_) {
      if (!owner_ || !state.pointers[owner_] || !state.pointers[owner_]->physical) state.ordering_error = true;
      heap_.reset();
      if (owner_) --state.buffers[owner_];
      ++state.frees;
    }
  }
};
struct HandleValueArray { explicit HandleValueArray(const RootedValueVector&) {} };
class ForOfIterator {
  JSContext* cx_;
  Input* input_ = nullptr;
  size_t index_ = 0;
public:
  explicit ForOfIterator(JSContext* cx) : cx_(cx) {}
  bool init(Value value) { input_ = value.input; return input_ != nullptr; }
  bool next(RootedValue* value, bool* done) {
    ++state.calls;
    if (input_->nested && index_ == 9 && !state.nested_started) {
      state.nested_started = true;
      Input inner{9, static_cast<size_t>(-1), false, input_->depth + 1};
      if (!invoke(cx_, inner)) return false;
    }
    if (input_->depth == 1 && index_ == 9 && state.live_count == 2 &&
        state.buffers[1] == 1 && state.buffers[2] == 1) state.nested_seen = true;
    *done = index_ == input_->count;
    if (*done) return true;
    static JSObject signal;
    value->object = index_ == input_->invalid_at ? nullptr : &signal;
    ++index_;
    return true;
  }
  // Models pinned ForOfIterator::closeThrow: save a pending exception across
  // the user return callback; an uncatchable interrupt has no callback.
  void closeThrow() {
    if (!state.error) return;
    const char* original = state.error;
    ++state.close_calls;
    if (state.live[1] && state.buffers[1] && state.pointers[1] && state.pointers[1]->physical)
      state.close_saw_owner = true;
    if (state.return_reentry && input_->depth == 1) {
      ++state.return_reentries;
      Input inline_input{2, static_cast<size_t>(-1), false, input_->depth + 1};
      if (!invoke(cx_, inline_input)) state.ordering_error = true;
      state.error = "iterator-return-threw";
      state.return_threw = true;
    }
    state.error = original;
  }
};
struct Result { void setObject(JSObject&) {} };
struct CallArgs {
  Value input;
  Result result;
  bool requireAtLeast(JSContext*, const char*, unsigned) { return true; }
  Value get(unsigned) const { return input; }
  Result& rval() { return result; }
};
CallArgs CallArgsFromVp(unsigned, Value* value) { return {*value, {}}; }
}
using CallArgs = JS::CallArgs;
struct RootedObject {
  JSObject* object;
  RootedObject(JSContext*, JSObject* value) : object(value) {}
  explicit operator bool() const { return object != nullptr; }
  JSObject& operator*() const { return *object; }
};
namespace api {
enum class Errors { TypeError };
void throw_error(JSContext*, Errors, const char*, const char*, const char*) { state.error = "invalid"; }
}
void JS_ReportOutOfMemory(JSContext*) { state.error = "oom"; }
struct AbortSignal {
  static bool is_instance(JSObject* object) { return object->signal; }
  static JSObject* create_with_signals(JSContext*, JS::HandleValueArray) {
    ++state.created;
    if (state.live_count == 2 && state.buffers[1] == 1 && state.buffers[2] == 1) state.nested_seen = true;
    static JSObject result;
    return &result;
  }
  static bool any(JSContext*, unsigned, JS::Value*);
};

// INSERT_EMITTED_ABORT_ANY

static bool invoke(JSContext* cx, Input& input) {
  JS::Value argument;
  argument.input = &input;
  return AbortSignal::any(cx, 1, &argument);
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const char* name = argv[1];
  Input input{9, static_cast<size_t>(-1), false, 0};
  if (!std::strcmp(name, "inline")) input.count = 8;
  if (!std::strcmp(name, "growth")) input.count = 33;
  if (!std::strcmp(name, "invalid")) { input.count = 4; input.invalid_at = 2; }
  if (!std::strcmp(name, "invalid-grown")) { input.count = 10; input.invalid_at = 9; }
  if (!std::strcmp(name, "refusal") || !std::strcmp(name, "uncatchable")) state.limit = 0;
  if (!std::strcmp(name, "uncatchable")) state.uncatchable = true;
  if (!std::strcmp(name, "nested") || !std::strcmp(name, "nested-refusal") ||
      !std::strcmp(name, "return-reentry")) { input.count = 10; input.nested = true; }
  if (!std::strcmp(name, "nested-refusal") || !std::strcmp(name, "return-reentry")) state.limit = 1;
  if (!std::strcmp(name, "return-reentry")) state.return_reentry = true;
  if (!std::strcmp(name, "allocation-failure-first")) state.allocation_failure = 1;
  if (!std::strcmp(name, "allocation-failure")) state.allocation_failure = 2;
  if (!std::strcmp(name, "allocation-failure")) input.count = 17;
  Records::Record* gc_record = nullptr;
  if (!std::strcmp(name, "gc-object")) {
    Lease gc_owned;
    if (!state.records.track({1, true}, gc_record) || !gc_owned.bind(gc_record)) return 3;
    state.next = 1; state.live[1] = true; state.live_count = 1; state.pointers[1] = gc_record;
  }
  if (!std::strcmp(name, "repeated")) state.limit = 1;
  JSContext cx;
  const bool result = invoke(&cx, input);
  bool waited = false, second = false;
  if (!std::strcmp(name, "repeated")) {
    waited = state.live_count == 1 && !state.acknowledgements && !state.pointers[1]->physical &&
             state.pointers[1]->collection_completed;
    second = invoke(&cx, input);
  }
  bool passed = false;
  if (!std::strcmp(name, "inline"))
    passed = result && state.created == 1 && !state.admissions && !state.allocations && !state.close_calls;
  else if (!std::strcmp(name, "heap"))
    passed = result && state.created == 1 && state.admissions == 1 && state.allocations == 1 &&
             state.frees == 1 && state.live_count == 1 && !state.acknowledgements &&
             !state.pointers[1]->physical && state.pointers[1]->collection_completed;
  else if (!std::strcmp(name, "growth"))
    passed = result && state.admissions == 1 && state.allocations == 3 && state.frees == 3 &&
             state.max_buffers == 2 && state.live_count == 1 && !state.pointers[1]->physical;
  else if (!std::strcmp(name, "refusal"))
    passed = !result && state.error && !std::strcmp(state.error, "admission") && state.calls == 9 &&
             state.close_calls == 1 && !state.created && !state.allocations;
  else if (!std::strcmp(name, "uncatchable"))
    passed = !result && !state.error && state.calls == 9 && !state.close_calls && !state.created && !state.allocations;
  else if (!std::strcmp(name, "invalid"))
    passed = !result && state.error && !std::strcmp(state.error, "invalid") && state.close_calls == 1 &&
             !state.admissions && !state.created;
  else if (!std::strcmp(name, "invalid-grown"))
    passed = !result && state.error && !std::strcmp(state.error, "invalid") && state.close_calls == 1 &&
             state.close_saw_owner && state.admissions == 1 && state.allocations == 1 && state.frees == 1 &&
             state.live_count == 1 && !state.pointers[1]->physical && state.pointers[1]->collection_completed;
  else if (!std::strcmp(name, "nested"))
    passed = result && state.nested_seen && state.created == 2 && state.admissions == 2 &&
             state.allocations == 2 && state.frees == 2 && state.live_count == 2 &&
             !state.pointers[1]->physical && !state.pointers[2]->physical;
  else if (!std::strcmp(name, "nested-refusal") || !std::strcmp(name, "return-reentry"))
    passed = !result && state.error && !std::strcmp(state.error, "admission") && state.close_calls == 1 &&
             state.close_saw_owner && state.admissions == 2 && state.allocations == 1 && state.frees == 1 && state.live_count == 1 &&
             !state.pointers[1]->physical &&
             (std::strcmp(name, "return-reentry") || (state.return_reentries == 1 && state.return_threw && state.created == 1));
  else if (!std::strcmp(name, "allocation-failure-first"))
    passed = !result && state.error && !std::strcmp(state.error, "oom") && state.admissions == 1 &&
             !state.allocations && !state.frees && !state.close_calls && !state.created && state.live_count == 1 &&
             !state.pointers[1]->physical && state.pointers[1]->collection_completed;
  else if (!std::strcmp(name, "allocation-failure"))
    passed = !result && state.error && !std::strcmp(state.error, "oom") && state.admissions == 1 &&
             state.allocations == 1 && state.frees == 1 && !state.close_calls && !state.created &&
             state.live_count == 1 && !state.pointers[1]->physical && state.pointers[1]->collection_completed;
  else if (!std::strcmp(name, "repeated"))
    passed = result && waited && second && state.admissions == 2 && state.allocations == 2 && state.frees == 2 &&
             state.acknowledgements == 1 && !state.live[1] && state.live[2] && !state.pointers[2]->physical;
  else if (!std::strcmp(name, "gc-object")) {
    passed = result && state.live_count == 2 && !gc_record->physical && !gc_record->collection_completed &&
             !state.pointers[2]->physical && state.pointers[2]->collection_completed && !state.acknowledgements;
    passed = passed && state.checkpoint() && state.acknowledgements == 1 && state.live[1] && !state.live[2] &&
             !gc_record->collection_completed;
    state.records.collectionCompleted();
  } else return 2;
  passed = passed && state.checkpoint() && !state.live_count && !state.records.hasRetained() && !state.ordering_error;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              name, passed ? "true" : "false");
  return passed ? 0 : 1;
}
