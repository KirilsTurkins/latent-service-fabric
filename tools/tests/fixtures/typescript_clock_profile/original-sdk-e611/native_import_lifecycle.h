// Physical ownership of an asynchronous canonical import. The embedding
// supplies rooted JS values and the unchanged typed lowering/result layout.
#pragma once
#include "native_readiness.h"
#include <cstddef>

namespace lsf::typescript::activation {

class ImportAccounting {
public:
  virtual ~ImportAccounting() = default;
  // One original-ledger reservation, before buffers, JS roots or dispatch.
  virtual bool admit(JSContext*, JobOwners&, NativeOwner&, NativeOwner&) = 0;
  virtual bool rollback(JSContext*, JobOwners&, NativeOwner&, NativeOwner&) = 0;
  virtual bool park(JSContext*, JobOwners&) = 0;
  virtual bool resume(JSContext*, JobOwners&) = 0;
  virtual bool complete(JSContext*, JobOwners&) = 0;
  // Called only after the record and all its rooted/lowered buffers are gone.
  virtual bool physicallyRetired(JSContext*, NativeOwner&, NativeOwner&) = 0;
};

class ImportLifecycle final {
public:
  struct Retirement { NativeOwner native{}; NativeOwner result{}; };
  enum class Phase { Empty, Reserved, Lowering, Pending, Returned, Cancelled, Lifting,
                     Retiring, Retired };
private:
  ImportAccounting& accounting_;
  ReadinessSet& readiness_;
  JobOwners work_{};
  NativeOwner native_{};
  NativeOwner result_{};
  Subtask subtask_;
  Phase phase_ = Phase::Empty;
  bool cancelled_ = false;
  bool rollback_pending_ = false;

  static bool invalid(JSContext* cx) {
    if (!JS_IsExceptionPending(cx))
      JS_ReportErrorASCII(cx, "activation-runtime-import-lifecycle-invalid");
    return false;
  }
public:
  ImportLifecycle(ImportAccounting& accounting, ReadinessSet& readiness)
      : accounting_(accounting), readiness_(readiness) {}
  ImportLifecycle(const ImportLifecycle&) = delete;
  ImportLifecycle& operator=(const ImportLifecycle&) = delete;

  bool reserve(JSContext* cx) {
    if (phase_ != Phase::Empty) return invalid(cx);
    // Admit records partial tokens even on failure; rollback must acknowledge
    // those exact owners before this record can disappear or admission reopen.
    if (!accounting_.admit(cx, work_, native_, result_)) {
      phase_ = Phase::Retiring;
      rollback_pending_ = true;
      if (!accounting_.rollback(cx, work_, native_, result_)) return false;
      rollback_pending_ = false;
      phase_ = Phase::Retired;
      return false;
    }
    phase_ = Phase::Reserved;
    return true;
  }
  bool beginLowering(JSContext* cx) {
    if (phase_ != Phase::Reserved || cancelled_) return invalid(cx);
    phase_ = Phase::Lowering;
    return true;
  }
  bool started(JSContext* cx, jobs_subtask_status_t status) {
    if (phase_ != Phase::Lowering || cancelled_ || !subtask_.started(cx, status))
      return invalid(cx);
    if (!accounting_.park(cx, work_)) return false;
    if (subtask_.pending()) {
      if (!readiness_.join(cx, subtask_)) return false;
      phase_ = Phase::Pending;
    } else {
      phase_ = subtask_.resultReady() ? Phase::Returned : Phase::Cancelled;
    }
    return true;
  }
  bool observe(JSContext* cx) {
    if (phase_ != Phase::Pending) return invalid(cx);
    if (subtask_.pending()) return true;
    // Cancellation remains cancellation even if a late physical result wins.
    phase_ = cancelled_ || subtask_.cancelledReady() ? Phase::Cancelled : Phase::Returned;
    return true;
  }
  bool beginLifting(JSContext* cx) {
    if (phase_ == Phase::Pending && !observe(cx)) return false;
    if (phase_ != Phase::Returned || cancelled_ || !subtask_.resultReady())
      return invalid(cx);
    // The typed result remains reserved/rooted through this exact JS lift.
    if (!accounting_.resume(cx, work_)) return false;
    phase_ = Phase::Lifting;
    return true;
  }
  bool liftCompleted(JSContext* cx) {
    if (phase_ != Phase::Lifting) return invalid(cx);
    // Typed lifting and original borrow/resource reconstruction have returned.
    // Keep the real canonical handle until this point, matching v0.62's own
    // result-lift-before-InProgress-destructor/drop sequence.
    if (!subtask_.drop(cx) || !accounting_.complete(cx, work_)) return false;
    phase_ = Phase::Retiring;
    return true;
  }
  bool cancel(JSContext* cx) {
    if (phase_ == Phase::Retired || phase_ == Phase::Retiring) return true;
    if (phase_ == Phase::Empty || phase_ == Phase::Lifting) return invalid(cx);
    cancelled_ = true;
    if (subtask_.physical()) {
      if (!subtask_.cancel(cx)) return false;
      if (subtask_.pending()) { phase_ = Phase::Pending; return true; }
      if (!subtask_.drop(cx)) return false;
    }
    // No lifting occurs after cancellation. Buffers and captures still live
    // until the embedding's destruction acknowledgement below.
    if (!accounting_.complete(cx, work_)) return false;
    phase_ = Phase::Retiring;
    return true;
  }
  bool physicalRetirementAcknowledged(JSContext* cx) {
    if (phase_ != Phase::Retiring || subtask_.physical()) return invalid(cx);
    if (rollback_pending_) {
      if (!accounting_.rollback(cx, work_, native_, result_)) return false;
      rollback_pending_ = false;
    }
    if (!accounting_.physicallyRetired(cx, native_, result_) || native_.live || result_.live)
      return false;
    phase_ = Phase::Retired;
    return true;
  }
  bool releaseAfterPhysicalDestruction(JSContext* cx, Retirement& retirement) {
    if ((phase_ != Phase::Retiring && phase_ != Phase::Retired) || subtask_.physical() || rollback_pending_ ||
        work_.task_live || work_.queued_live) return invalid(cx);
    retirement = {native_, result_};
    native_ = {}; result_ = {};
    phase_ = Phase::Retired;
    return true;
  }
  Phase phase() const { return phase_; }
  bool hasPhysicalSubtask() const { return subtask_.physical(); }
  bool resultMayBeRead() const { return phase_ == Phase::Lifting && !cancelled_; }
};

} // namespace lsf::typescript::activation
