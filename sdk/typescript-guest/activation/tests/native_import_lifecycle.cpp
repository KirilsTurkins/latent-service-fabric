// The actual SDK lifecycle/readiness source with explicitly fake canonical
// imports and broker. This reference is not a signed Component Model witness.
#include "../native_import_lifecycle.h"
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;
namespace {
unsigned joined = 0, drops = 0, waits = 0, polls = 0, sets = 0;
uint32_t event_handle = 7;
jobs_subtask_state_t event_state = JOBS_SUBTASK_RETURNED;
bool defer_cancel = false, ack_refused = false, error = false;
struct Broker final : PromiseAccounting, ImportAccounting {
  unsigned reservations = 0, native_live = 0, result_live = 0, tasks = 0;
  bool deny_result = false;
  bool beforeAllocate(JSContext*, NativeOwner& out) override {
    out = {{1, ++reservations}, true}; ++native_live; return true;
  }
  bool acknowledgeRetirement(JSContext*, NativeOwner& owner) override {
    if (ack_refused) return false;
    if (owner.live) { owner.live = false; --native_live; }
    return true;
  }
  bool admit(JSContext*, JobOwners& work, NativeOwner& native, NativeOwner& result) override {
    work.task_live = work.queued_live = true; ++tasks;
    native = {{1, ++reservations}, true}; ++native_live;
    if (deny_result) return false;
    result = {{1, ++reservations}, true}; ++result_live;
    return true;
  }
  bool rollback(JSContext* cx, JobOwners& work, NativeOwner& native, NativeOwner& result) override {
    if (ack_refused) return false;
    if (result.live) { result.live = false; --result_live; }
    if (!acknowledgeRetirement(cx, native)) return false;
    return complete(cx, work);
  }
  bool park(JSContext*, JobOwners& work) override {
    if (!work.task_live || !work.queued_live) return false;
    work.queued_live = false; return true;
  }
  bool resume(JSContext*, JobOwners& work) override { return work.task_live && !work.queued_live; }
  bool complete(JSContext*, JobOwners& work) override {
    if (work.task_live) { work.task_live = work.queued_live = false; --tasks; }
    return true;
  }
  bool physicallyRetired(JSContext* cx, NativeOwner& native, NativeOwner& result) override {
    if (ack_refused) return false;
    if (result.live) { result.live = false; --result_live; }
    return acknowledgeRetirement(cx, native);
  }
};
bool check(bool value) { return value; }
}

bool JS_IsExceptionPending(JSContext*) { return error; }
void JS_ReportErrorASCII(JSContext*, const char*, ...) { error = true; }
extern "C" {
jobs_waitable_set_t jobs_waitable_set_new() { ++sets; return 1; }
void jobs_waitable_join(uint32_t, jobs_waitable_set_t set) { if (set) ++joined; else --joined; }
void jobs_waitable_set_drop(jobs_waitable_set_t) { if (joined) error = true; --sets; }
void jobs_waitable_set_wait(jobs_waitable_set_t, jobs_event_t* event) {
  ++waits; *event = {JOBS_EVENT_SUBTASK, event_handle, static_cast<uint32_t>(event_state)};
}
void jobs_waitable_set_poll(jobs_waitable_set_t, jobs_event_t* event) { ++polls; *event = {}; }
jobs_subtask_status_t jobs_subtask_cancel(jobs_subtask_t) {
  return defer_cancel ? JOBS_SUBTASK_STARTED : JOBS_SUBTASK_STARTED_CANCELLED;
}
void jobs_subtask_drop(jobs_subtask_t) { ++drops; }
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JSContext cx;
  Broker broker;
  ReadinessSet readiness(broker);
  ImportLifecycle import(broker, readiness);
  bool ok = true;
  const char* name = argv[1];
  if (!std::strcmp(name, "partial-admission-exact-rollback")) {
    broker.deny_result = true;
    ok = !import.reserve(&cx) && broker.tasks == 0 && broker.native_live == 0 &&
         import.phase() == ImportLifecycle::Phase::Retired;
  } else if (!std::strcmp(name, "failed-rollback-retains-owners")) {
    broker.deny_result = ack_refused = true;
    ok = !import.reserve(&cx) && broker.tasks == 1 && broker.native_live == 1 &&
         import.phase() == ImportLifecycle::Phase::Retiring;
  } else {
    ok = import.reserve(&cx) && import.beginLowering(&cx);
    if (!std::strcmp(name, "destruction-before-owner-acknowledgement")) {
      ok = ok && import.started(&cx, JOBS_SUBTASK_RETURNED) && import.beginLifting(&cx) &&
           import.liftCompleted(&cx);
      ImportLifecycle::Retirement retired;
      ok = ok && import.releaseAfterPhysicalDestruction(&cx, retired) &&
           broker.result_live == 1 && retired.result.live && retired.native.live;
      // Embedding destroys its actual record/captures/buffer between transfer
      // and this ACK. The reference tests exact owner transfer, not JS GC.
      ok = ok && broker.physicallyRetired(&cx, retired.native, retired.result) &&
           !retired.native.live && !retired.result.live && broker.native_live == 0;
    } else if (!std::strcmp(name, "immediate-result-keeps-lift-storage")) {
      ok = ok && import.started(&cx, JOBS_SUBTASK_RETURNED) && import.beginLifting(&cx) &&
           import.resultMayBeRead() && broker.result_live == 1 && broker.native_live == 1 &&
           import.liftCompleted(&cx) && broker.tasks == 0 && broker.result_live == 1 &&
           import.physicalRetirementAcknowledged(&cx);
    } else {
      ok = ok && import.started(&cx, (7u << 4) | JOBS_SUBTASK_STARTED) && joined == 1 &&
           broker.tasks == 1 && !import.resultMayBeRead();
      if (!std::strcmp(name, "eligible-work-polls-without-blocking")) {
        ok = ok && readiness.dispatch(&cx, false) && polls == 1 && waits == 0 &&
             import.phase() == ImportLifecycle::Phase::Pending;
      } else if (!std::strcmp(name, "unknown-readiness-keeps-storage")) {
        event_handle = 99;
        ok = ok && !readiness.dispatch(&cx, true) && broker.result_live == 1 &&
             import.hasPhysicalSubtask() && drops == 0;
      } else if (!std::strcmp(name, "late-return-after-cancel-never-lifts")) {
        defer_cancel = true;
        ok = ok && import.cancel(&cx) && import.hasPhysicalSubtask() && broker.result_live == 1 &&
             readiness.dispatch(&cx, true) && import.observe(&cx) &&
             !import.beginLifting(&cx) && broker.result_live == 1 && import.cancel(&cx) &&
             drops == 1 && import.physicalRetirementAcknowledged(&cx);
      } else if (!std::strcmp(name, "terminal-cancel-before-result-drop")) {
        ok = ok && import.cancel(&cx) && drops == 1 && joined == 0 && broker.result_live == 1 &&
             import.physicalRetirementAcknowledged(&cx);
      } else if (!std::strcmp(name, "failed-physical-ack-retains-result")) {
        ok = ok && readiness.dispatch(&cx, true) && import.observe(&cx) && import.beginLifting(&cx) &&
             import.liftCompleted(&cx);
        ack_refused = true;
        ok = ok && !import.physicalRetirementAcknowledged(&cx) && broker.native_live == 2 &&
             broker.result_live == 1 && import.phase() == ImportLifecycle::Phase::Retiring;
      } else if (!std::strcmp(name, "shared-timer-import-dispatch")) {
        Subtask timer;
        ok = ok && timer.started(&cx, (8u << 4) | JOBS_SUBTASK_STARTED) && readiness.join(&cx, timer) &&
             joined == 2 && sets == 1 && readiness.dispatch(&cx, true) && import.observe(&cx) &&
             timer.pending() && import.beginLifting(&cx) && import.liftCompleted(&cx) &&
             import.physicalRetirementAcknowledged(&cx) && joined == 1;
        event_handle = 8;
        ok = ok && readiness.dispatch(&cx, true) && timer.resultReady() && timer.drop(&cx) &&
             joined == 0 && readiness.retire(&cx) && broker.native_live == 0;
      } else if (!std::strcmp(name, "pending-buffer-not-readable")) {
        ok = ok && !import.beginLifting(&cx) && import.hasPhysicalSubtask() &&
             broker.tasks == 1 && broker.result_live == 1 && drops == 0;
      } else ok = false;
    }
  }
  std::printf("{\"case\":\"%s\",\"status\":%d,\"subtaskDrops\":%u,\"joined\":%u,"
              "\"resultOwners\":%u,\"nativeOwners\":%u,\"tasks\":%u,\"idleWaits\":%u}\n",
              name, ok ? 0 : 1, drops, joined, broker.result_live, broker.native_live, broker.tasks, waits);
  return check(ok) ? 0 : 1;
}
