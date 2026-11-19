#include "reaction_records.h"
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;
unsigned rooted_callables = 0;
bool call_succeeds = true;
bool fail_next_capture = false;

struct Native final : PromiseAccounting {
  unsigned next = 1, live = 0, settled = 0, fail_after_register = 0;
  bool snapshot = false, bad = false;
  unsigned long long tokens = 0;
  bool beforeAllocate(JSContext* cx, NativeOwner& owner) override {
    if (snapshot) return true;
    owner.token = {1, next++}; owner.live = true; ++live;
    tokens |= 1ULL << owner.token.id;
    if (owner.token.id == fail_after_register) { cx->exception = true; return false; }
    return true;
  }
  bool acknowledgeRetirement(JSContext*, NativeOwner& owner) override {
    if (!owner.live) return true;
    const auto bit = 1ULL << owner.token.id;
    if (!live || !(tokens & bit)) { bad = true; return false; }
    tokens &= ~bit; --live; ++settled; owner.live = false; return true;
  }
};
struct Jobs final : Accounting {
  unsigned tasks = 0, queued = 0;
  bool admit(JSContext*, JobOwners& owner) override {
    owner.task_live = owner.queued_live = true; ++tasks; ++queued; return true;
  }
  bool rollback(JSContext*, JobOwners& owner) override {
    if (owner.task_live) { if (!tasks) return false; --tasks; owner.task_live = false; }
    if (owner.queued_live) { if (!queued) return false; --queued; owner.queued_live = false; }
    return true;
  }
  bool started(JSContext*, JobOwners&) override { return false; }
  bool completed(JSContext*, JobOwners&) override { return false; }
  bool cancelled(JSContext*, JobOwners&) override { return false; }
};

static bool release(PromiseRecords& records, JSContext& cx, JSObject& object) {
  JSTracer dead{&object}; records.sweep(&dead);
  return records.collectionCompleted() == 1 && records.checkpoint(&cx);
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JSContext cx;
  Native native;
  Jobs jobs;
  bool passed = false;
  if (!std::strcmp(argv[1], "probe-before-created")) {
    PromiseRecords records(native);
    void* record = nullptr;
    if (!records.beforeAllocate(&cx, &record) || !records.checkpoint(&cx)) return 3;
    // Do not dereference record here: the old tracker has already freed it.
    std::printf("{\"case\":\"%s\",\"live\":%u,\"settled\":%u,"
                "\"pending\":%s,\"engineQualified\":false}\n",
                argv[1], native.live, native.settled,
                records.hasPendingPromises() ? "true" : "false");
    return 0;
  } else if (!std::strcmp(argv[1], "creation-reentry")) {
    PromiseRecords records(native);
    JSObject promise, first, second;
    void *p = nullptr, *a = nullptr, *b = nullptr;
    passed = records.beforeAllocate(&cx, &p) && records.hasPendingPromises() &&
      records.checkpoint(&cx) && native.live == 1 && native.settled == 0;
    PromiseRecords::created(&cx, &promise, p);
    passed = passed && records.beforeAllocate(&cx, &a) && records.checkpoint(&cx) && native.live == 2;
    PromiseRecords::capturedCreated(&cx, &first, a);
    passed = passed && records.beforeAllocate(&cx, &b) && records.checkpoint(&cx) && native.live == 3;
    PromiseRecords::capturedCreated(&cx, &second, b);
    records.settled(&cx, &promise);
    passed = passed && release(records, cx, promise) && native.live == 2 &&
      release(records, cx, first) && native.live == 1 &&
      release(records, cx, second) && native.live == 0 && native.settled == 3 && !native.bad;
  } else if (!std::strcmp(argv[1], "gc-during-creation")) {
    PromiseRecords records(native);
    JSObject function;
    void* record = nullptr;
    passed = records.beforeAllocate(&cx, &record);
    JSTracer gc{}; records.sweep(&gc);
    passed = passed && records.collectionCompleted() == 0 && records.checkpoint(&cx) &&
      native.live == 1 && native.settled == 0 && records.hasPendingPromises();
    PromiseRecords::capturedCreated(&cx, &function, record);
    passed = passed && release(records, cx, function) && native.live == 0 && !native.bad;
  } else if (!std::strcmp(argv[1], "partial-pair-allocation")) {
    PromiseRecords records(native);
    JSObject first;
    void *a = nullptr, *b = nullptr;
    passed = records.beforeAllocate(&cx, &a);
    PromiseRecords::capturedCreated(&cx, &first, a);
    passed = passed && records.beforeAllocate(&cx, &b) && records.checkpoint(&cx) &&
      native.live == 2 && native.settled == 0 && (native.tokens & 2ULL) && (native.tokens & 4ULL);
    PromiseRecords::allocationFailed(b);
    passed = passed && records.checkpoint(&cx) && native.live == 1 && native.settled == 1 &&
      (native.tokens & 2ULL) && !(native.tokens & 4ULL);
    passed = passed && release(records, cx, first) && native.live == 0 && native.settled == 2 && !native.bad;
  } else if (!std::strcmp(argv[1], "partial-pair-admission")) {
    PromiseRecords records(native);
    JSObject first;
    void *a = nullptr, *b = nullptr;
    passed = records.beforeAllocate(&cx, &a);
    PromiseRecords::capturedCreated(&cx, &first, a);
    native.fail_after_register = 2;
    passed = passed && !records.beforeAllocate(&cx, &b) && !b && cx.exception && native.live == 2;
    JS_ClearPendingException(&cx);
    passed = passed && records.checkpoint(&cx) && native.live == 1 && native.settled == 1 &&
      (native.tokens & 2ULL) && !(native.tokens & 4ULL);
    passed = passed && release(records, cx, first) && native.live == 0 && native.settled == 2 && !native.bad;
  } else if (!std::strcmp(argv[1], "reaction-creation-reentry")) {
    ReactionRecords records(native, jobs);
    void* record = nullptr;
    passed = records.beforeAllocate(&cx, &record) && records.hasPendingReactions() &&
      records.checkpoint(&cx) && native.live == 1 && jobs.tasks == 1 && jobs.queued == 1;
    ReactionRecords::allocationFailed(record);
    passed = passed && records.checkpoint(&cx) && !records.hasPendingReactions() &&
      native.live == 0 && native.settled == 1 && jobs.tasks == 0 && jobs.queued == 0 && !native.bad;
  } else if (!std::strcmp(argv[1], "snapshot-creation-fence")) {
    PromiseRecords records(native);
    native.snapshot = true;
    JSObject function;
    void* record = nullptr;
    passed = records.beforeAllocate(&cx, &record) && !records.snapshotCapturesEmpty(&cx, 0) && cx.exception;
    JS_ClearPendingException(&cx);
    PromiseRecords::capturedCreated(&cx, &function, record);
    passed = passed && !records.snapshotCapturesEmpty(&cx, 0) && cx.exception;
    JS_ClearPendingException(&cx);
    passed = passed && release(records, cx, function) && records.snapshotCapturesEmpty(&cx, 0) &&
      native.live == 0 && native.settled == 0 && !native.bad;
  } else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              argv[1], passed ? "true" : "false");
  return passed ? 0 : 1;
}
