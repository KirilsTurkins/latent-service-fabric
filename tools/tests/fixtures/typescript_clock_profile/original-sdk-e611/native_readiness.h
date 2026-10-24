// Original Component Model P3 readiness. No callback runs from a host import.
#pragma once
#include "jobs.h"
#include "jsapi.h"
#include "native_ownership.h"
#include "native_cancel.h"

namespace lsf::typescript::activation {
class ReadinessSet;

// The owning timer/import record reserves native/result storage before this
// member exists. Its address and result buffer stay stable until actual return
// and subtask-drop; requesting cancellation never releases that storage.
class Subtask final {
  friend class ReadinessSet;
  jobs_subtask_t handle_ = 0;
  jobs_subtask_state_t state_ = JOBS_SUBTASK_RETURNED;
  bool live_ = false;
  bool joined_ = false;
  bool cancel_requested_ = false;
  ReadinessSet* owner_set_ = nullptr;
  Subtask* next_in_set_ = nullptr;

  static bool returned(jobs_subtask_state_t state) {
    return state == JOBS_SUBTASK_RETURNED || state == JOBS_SUBTASK_STARTED_CANCELLED ||
           state == JOBS_SUBTASK_RETURNED_CANCELLED;
  }
  static bool known(jobs_subtask_state_t state) {
    return state == JOBS_SUBTASK_STARTING || state == JOBS_SUBTASK_STARTED ||
           returned(state);
  }
  static bool invalid(JSContext* cx) {
    if (!JS_IsExceptionPending(cx))
      JS_ReportErrorASCII(cx, "activation-runtime-subtask-state-invalid");
    return false;
  }

public:
  Subtask() = default;
  Subtask(const Subtask&) = delete;
  Subtask& operator=(const Subtask&) = delete;

  bool started(JSContext* cx, jobs_subtask_status_t status) {
    if (live_) return invalid(cx);
    state_ = JOBS_SUBTASK_STATE(status);
    handle_ = JOBS_SUBTASK_HANDLE(status);
    if (!known(state_) || (!returned(state_) && !handle_)) return invalid(cx);
    live_ = true;
    joined_ = false;
    cancel_requested_ = false;
    return true;
  }
  bool join(JSContext* cx, jobs_waitable_set_t set) {
    if (!live_ || joined_) return invalid(cx);
    if (returned(state_)) return true;
    jobs_waitable_join(handle_, set);
    joined_ = true;
    return true;
  }
  bool observed(JSContext* cx, const jobs_event_t& event) {
    if (!live_ || !joined_ || !handle_ || event.event != JOBS_EVENT_SUBTASK ||
        event.waitable != handle_)
      return invalid(cx);
    auto next = JOBS_SUBTASK_STATE(event.code);
    if (!known(next) || returned(state_) ||
        (state_ == JOBS_SUBTASK_STARTED && next == JOBS_SUBTASK_STARTING))
      return invalid(cx);
    // Started/starting acknowledgements do not make the outcome buffer ready.
    state_ = next;
    return true;
  }
  bool cancel(JSContext* cx) {
    if (!live_) return true;
    if (returned(state_)) return true;
    if (cancel_requested_) return true;
    cancel_requested_ = true;
    auto status = lsf_async_subtask_cancel(handle_);
    // The original asynchronous intrinsic returns BLOCKED while actual stop
    // remains pending. Keep the existing handle/state/set registration and
    // every result/capture owner until its eventual terminal event arrives.
    if (status == SubtaskCancellationBlocked) return true;
    auto next = JOBS_SUBTASK_STATE(status);
    // Original v0.62 cancellation returns a state code, not another packed
    // start status. The existing nonzero handle remains the physical owner.
    if (!known(next) ||
        (state_ == JOBS_SUBTASK_STARTED && next == JOBS_SUBTASK_STARTING))
      return invalid(cx);
    state_ = next;
    return true;
  }
  bool drop(JSContext* cx);
  bool resultReady() const { return live_ && state_ == JOBS_SUBTASK_RETURNED; }
  bool cancelledReady() const {
    return live_ && (state_ == JOBS_SUBTASK_STARTED_CANCELLED ||
                    state_ == JOBS_SUBTASK_RETURNED_CANCELLED);
  }
  bool pending() const { return live_ && !returned(state_); }
  bool physical() const { return live_; }
  bool matches(const jobs_event_t& event) const {
    return live_ && joined_ && handle_ && event.event == JOBS_EVENT_SUBTASK && event.waitable == handle_;
  }
};

// One lazy activation-local set. Its host/native reservation precedes the
// actual canonical set allocation; no sleeping worker or polling spin exists.
// Callers must retire every joined subtask before drop so their stable result
// buffers remain live through the actual subtask acknowledgements.
class ReadinessSet final {
  PromiseAccounting& accounting_;
  NativeOwner native_{};
  jobs_waitable_set_t set_ = 0;
  bool physical_ = false;
  Subtask* joined_ = nullptr;

  friend class Subtask;
  void acknowledgedDrop(Subtask& subtask) {
    auto* link = &joined_;
    while (*link && *link != &subtask) link = &(*link)->next_in_set_;
    if (*link) *link = subtask.next_in_set_;
    subtask.owner_set_ = nullptr;
    subtask.next_in_set_ = nullptr;
  }

public:
  explicit ReadinessSet(PromiseAccounting& accounting) : accounting_(accounting) {}
  ReadinessSet(const ReadinessSet&) = delete;
  ReadinessSet& operator=(const ReadinessSet&) = delete;
  bool initialize(JSContext* cx) {
    if (physical_) return true;
    if (native_.live) {
      JS_ReportErrorASCII(cx, "activation-runtime-readiness-partial-admission");
      return false;
    }
    if (!accounting_.beforeAllocate(cx, native_)) return false;
    if (!native_.live) {
      JS_ReportErrorASCII(cx, "activation-runtime-readiness-during-snapshot-denied");
      return false;
    }
    // The intrinsic may trap; live native ownership is already retained in
    // this activation record until physical Store cleanup in that outcome.
    set_ = jobs_waitable_set_new();
    physical_ = true;
    return true;
  }
  bool join(JSContext* cx, Subtask& subtask) {
    if (!subtask.pending()) return subtask.physical();
    if (subtask.owner_set_ || !initialize(cx) || !subtask.join(cx, set_)) return false;
    // Intrusive registration allocates no container. The stable subtask/result
    // record cannot leave this set until its real drop operation returns.
    subtask.owner_set_ = this;
    subtask.next_in_set_ = joined_;
    joined_ = &subtask;
    return true;
  }
  bool next(JSContext* cx, bool idle, jobs_event_t& event) {
    if (!physical_ || !joined_) {
      JS_ReportErrorASCII(cx, "activation-runtime-readiness-set-uninitialized");
      return false;
    }
    // An idle pump may suspend. While eligible ECMAScript work exists, this
    // operation only polls; asynchronous imports retain their own subtasks.
    if (idle) jobs_waitable_set_wait(set_, &event);
    else jobs_waitable_set_poll(set_, &event);
    return true;
  }
  bool dispatch(JSContext* cx, bool idle) {
    jobs_event_t event{};
    if (!next(cx, idle, event)) return false;
    if (event.event == JOBS_EVENT_NONE && !idle) return true;
    if (event.event != JOBS_EVENT_SUBTASK) {
      JS_ReportErrorASCII(cx, "activation-runtime-readiness-event-invalid");
      return false;
    }
    // Every producer registers its stable record in this one set. Dispatch
    // only advances the matching subtask; application code runs on a later
    // ordinary event-loop turn, never inside a host import or this traversal.
    for (auto* subtask = joined_; subtask; subtask = subtask->next_in_set_) {
      if (subtask->matches(event)) return subtask->observed(cx, event);
    }
    JS_ReportErrorASCII(cx, "activation-runtime-readiness-unknown-subtask");
    return false;
  }
  bool retire(JSContext* cx) {
    if (joined_) {
      JS_ReportErrorASCII(cx, "activation-runtime-readiness-subtasks-still-owned");
      return false;
    }
    if (physical_) {
      jobs_waitable_set_drop(set_);
      physical_ = false; // only after the actual canonical intrinsic returned
    }
    return accounting_.acknowledgeRetirement(cx, native_) && !native_.live;
  }
  bool physical() const { return physical_ || native_.live; }
  bool hasJoined() const { return joined_ != nullptr; }
};

inline bool Subtask::drop(JSContext* cx) {
  if (!live_) return true;
  if (!returned(state_)) return invalid(cx);
  // Remove the actual waitable from dispatch first. Neither unjoin nor a
  // cancellation request refunds its native/result storage or host subtask.
  if (joined_) {
    jobs_waitable_join(handle_, 0);
    joined_ = false;
  }
  // Immediate STATUS_RETURNED can carry no handle. Original v0.62 code uses
  // NonZeroU32 and drops only an actual created subtask.
  if (handle_) jobs_subtask_drop(handle_);
  live_ = false; // only after the actual drop intrinsic returned
  if (owner_set_) owner_set_->acknowledgedDrop(*this);
  return true;
}

} // namespace lsf::typescript::activation
