// Activation-local timer readiness for the selected native Promise engine.
// No host import invokes application code. Every next-result buffer is stable
// through its original P3 subtask return, unjoin and drop acknowledgements.
#pragma once
#include "broker_accounting.h"
#include "native_readiness.h"
#include "js/ValueArray.h"
#include <algorithm>
#include <climits>
#include <memory>
#include <new>

namespace lsf::typescript::activation {

class Timers final {
  struct Record {
    NativeOwner native;
    latent_runtime_activation_token_t timer{};
    bool timer_live = false;
    bool repeat = false;
    bool closing = false;
    bool in_callback = false;
    int32_t id = 0;
    JS::PersistentRootedObject callback;
    JS::PersistentRootedVector<JS::Value> arguments;
    JobOwners callback_owners{};
    Subtask next;
    latent_runtime_activation_result_u64_error_t outcome{};
    std::unique_ptr<Record> following;
    Record(JSContext* cx, const NativeOwner& owner, JS::HandleObject function)
        : native(owner), callback(cx, function), arguments(cx) {}
  };

  BrokerAccounting& jobs_;
  PromiseAccounting& native_;
  ReadinessSet readiness_;
  std::unique_ptr<Record> records_;
  Record* tail_ = nullptr;
  NativeOwner retired_native_{};
  int32_t next_id_ = 1;
  bool exhausted_ids_ = false;
  bool stopped_ = false;

  static bool fail(JSContext* cx, const char* operation,
                   latent_runtime_activation_error_t error) {
    if (!JS_IsExceptionPending(cx))
      JS_ReportErrorASCII(cx, "activation-runtime-timer-%s-denied:%u", operation,
                          static_cast<unsigned>(error));
    return false;
  }

  bool begin_next(JSContext* cx, Record& record) {
    if (!record.timer_live || record.closing || record.next.physical())
      return fail(cx, "next-state", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    // The record's precharged native storage includes this result buffer.
    record.outcome = {};
    if (!record.next.started(cx,
          latent_runtime_activation_timer_next(record.timer, &record.outcome)))
      return false;
    return readiness_.join(cx, record.next);
  }

  bool stop(JSContext* cx, Record& record) {
    record.closing = true; // eligibility closes before either host operation
    if (record.timer_live) {
      latent_runtime_activation_error_t error{};
      if (!latent_runtime_activation_timer_stop(&record.timer, &error))
        return fail(cx, "stop", error);
      record.timer_live = false; // only after the actual timer-stop returned
    }
    // A cancellation request is not retirement. Keep the entire rooted record
    // and its result buffer until a terminal state and actual subtask drop.
    return record.next.cancel(cx);
  }

  bool collect(JSContext* cx) {
    auto* link = &records_;
    while (*link) {
      auto* record = link->get();
      if (!record->closing || record->in_callback ||
          record->callback_owners.task_live || record->callback_owners.queued_live) {
        link = &record->following;
        continue;
      }
      if (record->next.pending()) {
        link = &record->following;
        continue;
      }
      if (!record->next.drop(cx)) return false;
      if (record->timer_live) return false;
      NativeOwner retired = record->native;
      const bool was_tail = tail_ == record;
      auto physical = std::move(*link);
      *link = std::move(physical->following);
      physical.reset(); // rooted captures and actual C++ metadata retired first
      if (was_tail) tail_ = nullptr;
      if (!native_.acknowledgeRetirement(cx, retired) || retired.live) {
        retired_native_ = retired;
        stopped_ = true;
        return false;
      }
    }
    // An erased tail is reconstructed without another allocation. Earlier
    // records may remain while a later cleared timer physically retires.
    if (!tail_ && records_) {
      tail_ = records_.get();
      while (tail_->following) tail_ = tail_->following.get();
    }
    return true;
  }

  bool invoke(JSContext* cx, Record& record) {
    if (record.closing || !record.timer_live ||
        !record.next.resultReady() || record.outcome.is_err)
      return fail(cx, "callback-state", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    // Keep the still-live Timer as the explicit parent after root close. Both
    // executable owners are accepted before allocating a native callback frame.
    Token parent{record.timer.generation, record.timer.id};
    if (!jobs_.admitUnder(cx, parent, record.callback_owners)) return false;
    if (!record.next.drop(cx)) return false;
    if (!jobs_.started(cx, record.callback_owners)) return false;
    record.in_callback = true;
    bool called;
    {
      JS::RootedValue result(cx);
      called = JS::Call(cx, JS::NullHandleValue, record.callback,
                        JS::HandleValueArray(record.arguments), &result);
    }
    record.in_callback = false; // actual JS::Call frame has returned
    if (!jobs_.completed(cx, record.callback_owners) ||
        record.callback_owners.task_live || record.callback_owners.queued_live)
      return false;
    // Microtasks generated by this callback run at the next real engine
    // checkpoint. A repeat registers at most one non-overlapping next wait;
    // the original host coalesces missed ticks without a catch-up queue.
    if (!called || !record.repeat || record.closing) {
      if (!stop(cx, record)) return false;
      if (!collect(cx)) return false;
      return called;
    }
    return begin_next(cx, record);
  }

public:
  Timers(BrokerAccounting& jobs, PromiseAccounting& native)
      : jobs_(jobs), native_(native), readiness_(native) {}

  bool start(JSContext* cx, JS::HandleObject callback,
             const JS::HandleValueArray& arguments, int32_t delay_ms,
             bool repeat, int32_t* id) {
    *id = 0;
    if (stopped_ || retired_native_.live || exhausted_ids_)
      return fail(cx, "admission-closed", LATENT_RUNTIME_ACTIVATION_ERROR_RESOURCE_EXHAUSTED);
    NativeOwner accepted;
    if (!native_.beforeAllocate(cx, accepted)) {
      if (accepted.live) { retired_native_ = accepted; stopped_ = true; }
      return false;
    }
    if (!accepted.live)
      return fail(cx, "during-snapshot", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    auto physical = std::unique_ptr<Record>(
        new (std::nothrow) Record(cx, accepted, callback));
    if (!physical) {
      if (!native_.acknowledgeRetirement(cx, accepted) || accepted.live) {
        retired_native_ = accepted; stopped_ = true;
      }
      JS_ReportOutOfMemory(cx);
      return false;
    }
    Record* record = physical.get();
    if (tail_) tail_->following = std::move(physical);
    else records_ = std::move(physical);
    tail_ = record;
    record->repeat = repeat;
    record->id = next_id_;
    if (next_id_ == INT32_MAX) exhausted_ids_ = true;
    else ++next_id_;

    Token inherited{};
    const bool has_parent = jobs_.currentContinuation(inherited);
    latent_runtime_activation_token_t parent{inherited.generation, inherited.id};
    latent_runtime_activation_error_t error{};
    const auto millis = static_cast<uint64_t>(std::max(delay_ms, 0));
    const uint64_t first = millis * 1000000;
    // The named activation profile uses finite fixed-rate/coalescing intervals.
    // Zero-delay intervals use a one-millisecond period, never a zero host tick.
    uint64_t period = std::max<uint64_t>(millis, 1) * 1000000;
    if (!latent_runtime_activation_timer_start(first, repeat ? &period : nullptr,
          has_parent ? &parent : nullptr, &record->timer, &error)) {
      record->closing = true;
      (void)collect(cx);
      return fail(cx, "start", error);
    }
    record->timer_live = true;
    if (!record->arguments.initCapacity(arguments.length())) {
      JS_ReportOutOfMemory(cx);
      (void)stop(cx, *record); (void)collect(cx);
      return false;
    }
    for (size_t index = 0; index < arguments.length(); ++index)
      record->arguments.infallibleAppend(arguments[index]);
    if (!begin_next(cx, *record)) {
      stopped_ = true;
      (void)stop(cx, *record);
      return false;
    }
    *id = record->id;
    return true;
  }

  bool clear(JSContext* cx, int32_t id) {
    for (auto* record = records_.get(); record; record = record->following.get()) {
      if (record->id == id) {
        if (!stop(cx, *record)) { stopped_ = true; return false; }
        return collect(cx);
      }
    }
    return true; // stale/unknown IDs are the standard no-op
  }

  bool hasPending() const {
    return records_ || retired_native_.live || readiness_.physical();
  }

  // One macrotask per native event-loop turn. Caller runs the genuine Promise
  // queue checkpoint before invoking this pump again. idle only permits a
  // canonical wait when no eligible ECMAScript continuation is executing.
  bool turn(JSContext* cx, bool idle) {
    if (stopped_) return fail(cx, "pump-stopped", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    if (!collect(cx)) return false;
    for (auto* record = records_.get(); record; record = record->following.get()) {
      if (record->closing) continue;
      if (record->next.cancelledReady())
        return fail(cx, "unexpected-cancellation", LATENT_RUNTIME_ACTIVATION_ERROR_CANCELLED);
      if (record->next.resultReady()) {
        if (record->outcome.is_err)
          return fail(cx, "next", record->outcome.val.err);
        const bool result = invoke(cx, *record);
        if (!result) stopped_ = true;
        return result;
      }
    }
    if (!records_) return readiness_.retire(cx);
    jobs_event_t event{};
    if (!readiness_.next(cx, idle, event)) return false;
    if (event.event == JOBS_EVENT_NONE && !idle) return true;
    if (event.event != JOBS_EVENT_SUBTASK)
      return fail(cx, "unexpected-readiness", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    for (auto* record = records_.get(); record; record = record->following.get()) {
      if (record->next.matches(event)) return record->next.observed(cx, event);
    }
    return fail(cx, "unknown-readiness", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
  }

  bool cancel(JSContext* cx) {
    stopped_ = true;
    for (auto* record = records_.get(); record; record = record->following.get()) {
      if (record->in_callback) return false;
      if (!stop(cx, *record) || !jobs_.cancelled(cx, record->callback_owners))
        return false;
    }
    if (!collect(cx)) return false;
    if (records_) return false; // actual pending subtasks still own their storage
    if (retired_native_.live &&
        (!native_.acknowledgeRetirement(cx, retired_native_) || retired_native_.live))
      return false;
    return readiness_.retire(cx);
  }
};

} // namespace lsf::typescript::activation
