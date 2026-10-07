// LSF's opt-in queue implements the pinned Firefox147 JS::JobQueue interface.
// The original Promise intrinsics enqueue here; no Promise.then replacement is
// involved. Accounting implementations must use the admitted activation broker.
#pragma once

#include "js/CallAndConstruct.h"
#include "js/Promise.h"
#include "js/Realm.h"
#include "js/RootingAPI.h"
#include "jsapi.h"

#include <cstdint>
#include <memory>
#include <new>

namespace lsf::typescript::activation {

struct Token {
  uint64_t generation;
  uint64_t id;
};

struct JobOwners {
  Token task{};
  Token queued{};
  bool task_live = false;
  bool queued_live = false;
};

// These are mandatory native entry/exit hooks, not a second budget ledger.
// admit reserves both records before queue allocation. The mutable live flags
// change only after individual broker acknowledgements, including partial
// admission and cancellation. started releases only the queue record; the
// task and its captures stay live through JS::Call. These methods preserve any
// pending ECMAScript exception when reporting an independent broker failure.
class Accounting {
public:
  virtual ~Accounting() = default;
  virtual bool admit(JSContext* cx, JobOwners& owners) = 0;
  virtual bool rollback(JSContext* cx, JobOwners& owners) = 0;
  virtual bool started(JSContext* cx, JobOwners& owners) = 0;
  virtual bool completed(JSContext* cx, JobOwners& owners) = 0;
  virtual bool cancelled(JSContext* cx, JobOwners& owners) = 0;
};

class JobQueue final : public JS::JobQueue {
public:
  // A reaction transfers the task/queue reservations made before its intrinsic
  // allocation. Other native jobs still use the original admission path.
  using Transfer = bool (*)(JSContext*, JS::HandleObject, JobOwners&, bool&);

private:
  enum class Phase { Queued, Executing, Retired };
  struct Job {
    JS::PersistentRootedObject callable;
    JobOwners owners;
    Phase phase = Phase::Queued;
    std::unique_ptr<Job> next;
    Job(JSContext* cx, JS::HandleObject function, const JobOwners& accepted)
        : callable(cx, function), owners(accepted) {}
  };

  Accounting& accounting_;
  Transfer transfer_;
  std::unique_ptr<Job> head_;
  Job* tail_ = nullptr;
  std::unique_ptr<Job> current_;
  // Allocation failure must not allocate another container to retain a failed
  // rollback. At most this single admission can fail before the queue closes.
  JobOwners rollback_{};
  bool rollback_pending_ = false;
  bool running_ = false;
  bool stopped_ = false;

  static bool live(const JobOwners& owners) {
    return owners.task_live || owners.queued_live;
  }

  void retainFailedAdmission(JSContext* cx, JobOwners& owners) {
    if (!accounting_.rollback(cx, owners) || live(owners)) {
      rollback_ = owners;
      rollback_pending_ = true;
      stopped_ = true;
    }
  }

public:
  explicit JobQueue(Accounting& accounting, Transfer transfer = nullptr)
      : accounting_(accounting), transfer_(transfer) {}

  bool getHostDefinedData(JSContext*, JS::MutableHandleObject data) const override {
    data.set(nullptr);
    return true;
  }
  bool getHostDefinedGlobal(JSContext*, JS::MutableHandleObject data) const override {
    // This finite single-global embedding has no incumbent browser global.
    // Match the pinned internal queue rather than changing thenable realms.
    data.set(nullptr);
    return true;
  }

  bool enqueuePromiseJob(JSContext* cx, JS::HandleObject,
                         JS::HandleObject job, JS::HandleObject,
                         JS::HandleObject) override {
    JobOwners accepted{};
    if (stopped_) {
      JS_ReportErrorASCII(cx, "activation-runtime-job-admission-closed");
      return false;
    }
    bool transferred = false;
    if (transfer_ && !transfer_(cx, job, accepted, transferred)) return false;
    if (!transferred && !accounting_.admit(cx, accepted)) {
      if (live(accepted)) retainFailedAdmission(cx, accepted);
      return false;
    }
    auto record = std::unique_ptr<Job>(new (std::nothrow) Job(cx, job, accepted));
    if (!record) {
      retainFailedAdmission(cx, accepted);
      JS_ReportOutOfMemory(cx);
      return false;
    }
    auto* last = record.get();
    if (tail_) tail_->next = std::move(record);
    else head_ = std::move(record);
    tail_ = last;
    JS::JobQueueMayNotBeEmpty(cx);
    return true;
  }

  void runJobs(JSContext* cx) override {
    // Native callback reentrancy cannot introduce an extra microtask checkpoint
    // in the middle of an executing ECMAScript job.
    if (running_ || stopped_) return;
    running_ = true;
    while (head_ && !stopped_) {
      current_ = std::move(head_);
      head_ = std::move(current_->next);
      if (!head_) tail_ = nullptr;
      if (!accounting_.started(cx, current_->owners)) {
        stopped_ = true;
        break;
      }
      current_->phase = Phase::Executing;
      bool called;
      {
        JSAutoRealm realm(cx, current_->callable);
        JS::RootedValue result(cx);
        called = JS::Call(cx, JS::UndefinedHandleValue, current_->callable,
                          JS::HandleValueArray::empty(), &result);
      }
      // Call returning false does not mean that its task vanished. The native
      // frame is now retired; settlement happens after that boundary in either
      // outcome, without changing the original exception or root stop cause.
      current_->phase = Phase::Retired;
      if (!accounting_.completed(cx, current_->owners) || live(current_->owners)) {
        stopped_ = true;
        break;
      }
      current_.reset();
      if (!called) {
        stopped_ = true;
        break;
      }
    }
    running_ = false;
  }

  bool empty() const override {
    return !head_ && !current_ && !rollback_pending_;
  }
  bool isDrainingStopped() const override { return stopped_; }

  bool cancelQueued(JSContext* cx) {
    // The caller closes admission first. A callback cannot be cancelled while
    // its native frame executes, and a cancel request alone refunds no owner.
    if (running_) return false;
    stopped_ = true;
    if (rollback_pending_) {
      if (!accounting_.rollback(cx, rollback_) || live(rollback_)) return false;
      rollback_pending_ = false;
    }
    if (current_) {
      // The running frame must have returned before a cancellation or a failed
      // settlement is retried. Mutable acknowledged flags prevent double
      // refunds when a previous transition retired only one of its owners.
      if (current_->phase == Phase::Executing) return false;
      const bool settled = current_->phase == Phase::Retired
          ? accounting_.completed(cx, current_->owners)
          : accounting_.cancelled(cx, current_->owners);
      if (!settled || live(current_->owners)) return false;
      current_.reset();
    }
    while (head_) {
      if (!accounting_.cancelled(cx, head_->owners) || live(head_->owners)) return false;
      auto next = std::move(head_->next);
      head_ = std::move(next);
    }
    tail_ = nullptr;
    return true;
  }

protected:
  js::UniquePtr<SavedJobQueue> saveJobQueue(JSContext* cx) override {
    // Debugger interruptions are outside this finite activation profile; never
    // fabricate a saved queue or silently reorder accepted continuation work.
    JS_ReportErrorASCII(cx, "activation-runtime-debugger-job-queue-unsupported");
    return nullptr;
  }
};

} // namespace lsf::typescript::activation
