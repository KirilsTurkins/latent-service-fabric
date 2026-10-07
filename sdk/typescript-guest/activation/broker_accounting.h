// The generated jobs.h is produced from the current, unchanged activation WIT
// by the pinned wit-bindgen0.62 tool. There is no fallback/local owner ledger.
#pragma once
#include "native_job_queue.h"
#include "jobs.h"

namespace lsf::typescript::activation {

class BrokerAccounting final : public Accounting {
  using EffectsAllowed = bool (*)(JSContext*);
  EffectsAllowed effects_allowed_;
  Token continuation_{};
  bool executing_ = false;

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
    // A child queue record is acknowledged before its parent task. If either
    // operation fails, acknowledged flags preserve the exact remaining owner
    // for cancellation; no retry invents a new token or refunds twice.
    if (!settle(cx, owners.queued, owners.queued_live)) return false;
    return settle(cx, owners.task, owners.task_live);
  }

public:
  explicit BrokerAccounting(EffectsAllowed effects_allowed)
      : effects_allowed_(effects_allowed) {}

  bool currentContinuation(Token& output) const {
    if (!executing_) return false;
    output = continuation_;
    return true;
  }

  bool admit(JSContext* cx, JobOwners& owners) override {
    if (!effects_allowed_ || !effects_allowed_(cx)) {
      JS_ReportErrorASCII(cx, "activation-runtime-job-during-snapshot-denied");
      return false;
    }
    latent_runtime_activation_error_t error{};
    latent_runtime_activation_token_t task{}, queued{};
    auto parent = native(continuation_);
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK,
          executing_ ? &parent : nullptr, &task, &error))
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

  bool rollback(JSContext* cx, JobOwners& owners) override {
    return release(cx, owners);
  }

  bool started(JSContext* cx, JobOwners& owners) override {
    if (executing_ || !owners.task_live || !owners.queued_live)
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
    // The native JS::Call frame has returned, including the exceptional path.
    // Subsequent admissions therefore cannot inherit this completed task.
    executing_ = false;
    continuation_ = {};
    return release(cx, owners);
  }

  bool cancelled(JSContext* cx, JobOwners& owners) override {
    if (executing_)
      return failure(cx, "running-job-cancel", LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE);
    return release(cx, owners);
  }
};

} // namespace lsf::typescript::activation
