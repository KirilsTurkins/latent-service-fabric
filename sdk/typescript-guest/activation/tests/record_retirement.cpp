// Actual maintained record classes with serialized JS lifetime doubles.
// No engine, collector, canonical guest or native broker qualification.
#include "../reaction_records.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace lsf::typescript::activation;
unsigned rooted_callables = 0;
bool call_succeeds = true;
static void* watched = nullptr;
static bool destroyed = false;
static bool watch_next = false;
static unsigned allocations = 0;

void* operator new(std::size_t size) {
  void* value = std::malloc(size);
  if (!value) std::abort();
  ++allocations;
  if (watch_next) { watched = value; destroyed = false; watch_next = false; }
  return value;
}
void operator delete(void* value) noexcept {
  if (value == watched) destroyed = true;
  std::free(value);
}
void operator delete(void* value, std::size_t) noexcept { ::operator delete(value); }

struct Jobs final : Accounting {
  unsigned tasks = 0, queued = 0, completed_count = 0, cancelled_count = 0;
  bool refuse = false, refused = false, physical_violation = false;
  bool admit(JSContext*, JobOwners& owners) override {
    owners.task = {1, 7}; owners.queued = {1, 8};
    owners.task_live = owners.queued_live = true;
    ++tasks; ++queued; return true;
  }
  bool release(JobOwners& owners) {
    if (!destroyed || rooted_callables) physical_violation = true;
    if (owners.queued_live) { --queued; owners.queued_live = false; }
    if (refuse) { refused = true; return false; }
    if (owners.task_live) { --tasks; owners.task_live = false; }
    return true;
  }
  bool rollback(JSContext*, JobOwners& owners) override { return release(owners); }
  bool started(JSContext*, JobOwners& owners) override {
    if (!owners.queued_live) return false;
    --queued; owners.queued_live = false; return true;
  }
  bool completed(JSContext*, JobOwners& owners) override {
    bool result = release(owners); if (result) ++completed_count; return result;
  }
  bool cancelled(JSContext*, JobOwners& owners) override {
    bool result = release(owners); if (result) ++cancelled_count; return result;
  }
};
struct Native final : PromiseAccounting {
  unsigned live = 0, acknowledged = 0;
  bool refuse = false, physical_violation = false;
  bool beforeAllocate(JSContext*, NativeOwner& owner) override {
    owner.token = {2, 9}; owner.live = true; ++live; return true;
  }
  bool acknowledgeRetirement(JSContext*, NativeOwner& owner) override {
    if (!destroyed) physical_violation = true;
    if (refuse) return false;
    if (!owner.live) return false;
    owner.live = false; --live; ++acknowledged; return true;
  }
};
static unsigned callbacks = 0;
static bool callback_executed = false;
static void retired(void*, bool executed) { ++callbacks; callback_executed = executed; }

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JSContext cx;
  Native native;
  Jobs jobs;
  bool passed = false;
  const char* selected = argv[1];
  if (!std::strcmp(selected, "promise-ack-after-delete") ||
      !std::strcmp(selected, "promise-refused-ack-retains-owner")) {
    PromiseRecords records(native);
    void* record = nullptr;
    watch_next = true;
    if (!records.beforeAllocate(&cx, &record) || record != watched) return 3;
    PromiseRecords::allocationFailed(record);
    native.refuse = std::strstr(selected, "refused") != nullptr;
    const auto before = allocations;
    const bool first = records.checkpoint(&cx);
    passed = destroyed && !native.physical_violation;
    if (native.refuse) {
      void* rejected = nullptr;
      passed = passed && !first && native.live == 1 && records.hasRetainedRetirement() &&
               !records.beforeAllocate(&cx, &rejected) && !rejected;
      native.refuse = false;
    } else passed = passed && first;
    passed = passed && records.checkpoint(&cx) && records.checkpoint(&cx) &&
             !records.hasRetainedRetirement() && native.live == 0 &&
             native.acknowledged == 1 && allocations == before;
  } else if (!std::strcmp(selected, "reaction-ack-after-delete") ||
             !std::strcmp(selected, "reaction-partial-ack-retains-owner")) {
    ReactionRecords records(native, jobs);
    void* record = nullptr;
    watch_next = true;
    if (!records.beforeAllocate(&cx, &record) || record != watched) return 3;
    ReactionRecords::allocationFailed(record);
    native.refuse = std::strstr(selected, "partial") != nullptr;
    const auto before = allocations;
    const bool first = records.checkpoint(&cx);
    passed = destroyed && !native.physical_violation && !jobs.physical_violation;
    if (native.refuse) {
      void* rejected = nullptr;
      passed = passed && !first && native.live == 1 && jobs.tasks == 0 && jobs.queued == 0 &&
               records.hasPendingReactions() && !records.beforeAllocate(&cx, &rejected) && !rejected;
      native.refuse = false;
    } else passed = passed && first;
    passed = passed && records.checkpoint(&cx) && records.checkpoint(&cx) &&
             !records.hasPendingReactions() && native.live == 0 && native.acknowledged == 1 &&
             jobs.tasks == 0 && jobs.queued == 0 && allocations == before;
  } else {
    if (std::strcmp(selected, "job-ack-after-delete") &&
        std::strcmp(selected, "job-error-ack-after-delete") &&
        std::strcmp(selected, "job-cancel-ack-after-delete") &&
        std::strcmp(selected, "job-partial-ack-retains-owner") &&
        std::strcmp(selected, "job-cancel-partial-ack-retains-owner")) return 2;
    JobQueue queue(jobs);
    JobOwners owner;
    if (!jobs.admit(&cx, owner)) return 3;
    const bool cancel = std::strstr(selected, "cancel") != nullptr;
    const bool partial = std::strstr(selected, "partial") != nullptr;
    call_succeeds = std::strstr(selected, "error") == nullptr;
    jobs.refuse = partial;
    watch_next = true;
    JSObject callable;
    if (!queue.enqueueAdmitted(&cx, &callable, owner, retired, nullptr)) return 3;
    const auto before = allocations;
    bool first = true;
    if (cancel) first = queue.cancelQueued(&cx);
    else queue.runJobs(&cx);
    passed = destroyed && rooted_callables == 0 && !jobs.physical_violation;
    if (partial) {
      passed = passed && !queue.empty() && jobs.tasks == 1 && jobs.queued == 0 &&
               callbacks == 0 && !queue.cancelQueued(&cx) && jobs.tasks == 1;
      jobs.refuse = false;
    } else passed = passed && first;
    passed = passed && queue.cancelQueued(&cx) && queue.empty() && jobs.tasks == 0 &&
             jobs.queued == 0 && callbacks == 1 && callback_executed == !cancel &&
             (cancel ? jobs.cancelled_count : jobs.completed_count) == 1 && allocations == before;
  }
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", selected, passed ? "true" : "false");
  return passed ? 0 : 1;
}
