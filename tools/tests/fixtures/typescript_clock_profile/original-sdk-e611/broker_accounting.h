// The generated jobs.h is produced from the current, unchanged activation WIT
// by the pinned wit-bindgen0.62 tool. There is no fallback/local owner ledger.
#pragma once
#include "native_job_queue.h"
#include "jobs.h"

namespace lsf::typescript::activation {

class BrokerAccounting final : public Accounting {
  using EffectsAllowed = bool (*)(JSContext*);
  EffectsAllowed effects_allowed_;
  EffectsAllowed compiler_snapshot_allowed_;
  Token continuation_{};
  bool executing_ = false;
  bool executing_snapshot_ = false;
  Token root_{};
  bool root_live_ = false;
  bool root_closed_ = false;

  static latent_runtime_activation_token_t native(const Token& token) {
    return {token.generation, token.id};
  }

  static bool failure(JSContext* cx, const char* operation,
                      latent_runtime_activation_error_t error) {
    // Retiring a native frame must preserve its original JS exception. A
    // failed acknowledgement still returns false and retains its live token.
    if (!JS_IsExceptionPending(cx)) {
      JS_ReportErrorASCII(cx, "activation-runtime-%s-denied:%u", operation,
                          static_cast<unsigned>(error));
    }
    return false;
  }

  bool settle(JSContext* cx, Token token, bool& live) {
    if (!live) return true;
    auto owner = native(token);
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_settle(&owner, &error))
      return failure(cx, "settle", error);
    live = false;
    return true;
  }

  bool release(JSContext* cx, JobOwners& owners) {
    if (owners.compiler_snapshot) {
      if (owners.task_live || owners.queued_live || !compiler_snapshot_allowed_ ||
          !compiler_snapshot_allowed_(cx) || (effects_allowed_ && effects_allowed_(cx)))
        return failure(cx, "snapshot-owner-transition", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
      owners.compiler_snapshot = false;
      return true; // no activation token exists and no host import is invoked
    }
    // A child queue record is acknowledged before its parent task. If either
    // operation fails, acknowledged flags preserve the exact remaining owner
    // for cancellation; no retry invents a new token or refunds twice.
    if (!settle(cx, owners.queued, owners.queued_live)) return false;
    return settle(cx, owners.task, owners.task_live);
  }

public:
  explicit BrokerAccounting(EffectsAllowed effects_allowed,
                            EffectsAllowed compiler_snapshot_allowed = nullptr)
      : effects_allowed_(effects_allowed), compiler_snapshot_allowed_(compiler_snapshot_allowed) {}

  bool currentContinuation(Token& output) const {
    if (!executing_ && !root_live_) return false;
    output = executing_ ? continuation_ : root_;
    return true;
  }

  bool beginRoot(JSContext* cx) {
    if (root_live_ || root_closed_ || !effects_allowed_ || !effects_allowed_(cx))
      return failure(cx, "root-entry", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    latent_runtime_activation_token_t root{};
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK,
                                           nullptr, &root, &error))
      return failure(cx, "root-register", error);
    root_ = {root.generation, root.id};
    root_live_ = true;
    return true;
  }

  bool parkRoot(JSContext* cx) {
    if (!root_live_) return failure(cx, "root-park", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    auto root = native(root_);
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_park(&root, &error))
      return failure(cx, "root-park", error);
    return true;
  }

  bool settleRoot(JSContext* cx) {
    if (!root_live_) return failure(cx, "root-settlement", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    if (!root_closed_) {
      latent_runtime_activation_error_t error{};
      if (!latent_runtime_activation_close(&error)) return failure(cx, "root-close", error);
      root_closed_ = true;
    }
    // Root JS_Call has returned; continuation frames own independent admitted
    // tasks. The root Promise/result objects remain charged through actual GC.
    return settle(cx, root_, root_live_);
  }

  bool rootSettled() const { return root_closed_ && !root_live_; }

  bool admit(JSContext* cx, JobOwners& owners) override {
    Token inherited{};
    const bool has_parent = currentContinuation(inherited);
    return admitWithParent(cx, owners, has_parent ? &inherited : nullptr);
  }

  // An accepted timer remains an actual broker owner after root settlement.
  // Its callback inherits that exact token, without reopening root admission
  // or inventing authority, a deadline, or another budget ledger.
  bool admitUnder(JSContext* cx, Token parent, JobOwners& owners) {
    if (!effects_allowed_ || !effects_allowed_(cx))
      return failure(cx, "callback-phase", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    if (!parent.generation || !parent.id)
      return failure(cx, "callback-parent", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
    return admitWithParent(cx, owners, &parent);
  }

  bool parkAccepted(JSContext* cx, JobOwners& owners) {
    if (!owners.task_live || !owners.queued_live || owners.compiler_snapshot)
      return failure(cx, "import-park", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    auto task = native(owners.task);
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_park(&task, &error)) return failure(cx, "import-park", error);
    return settle(cx, owners.queued, owners.queued_live);
  }

  bool retireAcceptedImport(JSContext* cx, JobOwners& owners) {
    // This import's lowering frame has already returned; retiring it does not
    // enter or replace the independent reaction frame that performs lifting.
    if (owners.compiler_snapshot)
      return failure(cx, "import-retirement", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    return release(cx, owners);
  }

private:
  bool admitWithParent(JSContext* cx, JobOwners& owners, const Token* inherited) {
    if (owners.task_live || owners.queued_live || owners.compiler_snapshot)
      return failure(cx, "job-readmission", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    if (!effects_allowed_ || !effects_allowed_(cx)) {
      if (compiler_snapshot_allowed_ && compiler_snapshot_allowed_(cx) && !inherited) {
        // The original bounded Wizer process/linear heap owns pure compilation.
        // Snapshot jobs create no runtime owner, identity, or external effect.
        owners.compiler_snapshot = true;
        return true;
      }
      JS_ReportErrorASCII(cx, "activation-runtime-job-during-snapshot-denied");
      return false;
    }
    latent_runtime_activation_error_t error{};
    latent_runtime_activation_token_t task{}, queued{};
    auto parent = inherited ? native(*inherited) : latent_runtime_activation_token_t{};
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK,
          inherited ? &parent : nullptr, &task, &error))
      return failure(cx, "task-register", error);
    owners.task = {task.generation, task.id};
    owners.task_live = true;
    if (!latent_runtime_activation_park(&task, &error))
      return failure(cx, "task-park", error);
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_QUEUED_WORK,
                                           &task, &queued, &error))
      return failure(cx, "queue-register", error);
    owners.queued = {queued.generation, queued.id};
    owners.queued_live = true;
    return true;
  }

public:
  bool rollback(JSContext* cx, JobOwners& owners) override {
    return release(cx, owners);
  }

  bool started(JSContext* cx, JobOwners& owners) override {
    if (owners.compiler_snapshot) {
      if (executing_ || executing_snapshot_ || !compiler_snapshot_allowed_ ||
          !compiler_snapshot_allowed_(cx) || (effects_allowed_ && effects_allowed_(cx)))
        return failure(cx, "snapshot-frame-entry", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
      executing_snapshot_ = true;
      return true;
    }
    if (executing_ || executing_snapshot_ || !owners.task_live || !owners.queued_live)
      return failure(cx, "job-entry", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    auto task = native(owners.task);
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_wake(&task, &error))
      return failure(cx, "task-wake", error);
    if (!settle(cx, owners.queued, owners.queued_live)) return false;
    continuation_ = owners.task;
    executing_ = true;
    return true;
  }

  bool completed(JSContext* cx, JobOwners& owners) override {
    if (owners.compiler_snapshot) {
      executing_snapshot_ = false; // original native JS::Call frame returned
      return release(cx, owners);
    }
    // The native JS::Call frame has returned, including the exceptional path.
    // Subsequent admissions therefore cannot inherit this completed task.
    executing_ = false;
    continuation_ = {};
    return release(cx, owners);
  }

  bool cancelled(JSContext* cx, JobOwners& owners) override {
    if (executing_ || executing_snapshot_)
      return failure(cx, "running-job-cancel", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    return release(cx, owners);
  }
};

} // namespace lsf::typescript::activation
