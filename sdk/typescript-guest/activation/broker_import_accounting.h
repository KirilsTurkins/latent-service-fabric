#pragma once
#include "native_import_lifecycle.h"
#include "broker_accounting.h"
#include "promise_accounting.h"

namespace lsf::typescript::activation {

class BrokerImportAccounting final : public ImportAccounting {
  BrokerAccounting& jobs_;
  BrokerPromiseAccounting& native_;

  static bool resultRetired(JSContext* cx, NativeOwner& owner) {
    if (!owner.live) return true;
    latent_runtime_activation_token_t token{owner.token.generation, owner.token.id};
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_settle(&token, &error)) {
      if (!JS_IsExceptionPending(cx))
        JS_ReportErrorASCII(cx, "activation-runtime-import-result-retirement-denied:%u",
                            static_cast<unsigned>(error));
      return false;
    }
    owner.live = false;
    return true;
  }
public:
  BrokerImportAccounting(BrokerAccounting& jobs, BrokerPromiseAccounting& native)
      : jobs_(jobs), native_(native) {}
  bool admit(JSContext* cx, JobOwners& work, NativeOwner& native, NativeOwner& result) override {
    if (!jobs_.admit(cx, work) || !native_.beforeAllocate(cx, native) || !native.live)
      return false;
    latent_runtime_activation_token_t parent{work.task.generation, work.task.id};
    latent_runtime_activation_token_t token{};
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT,
                                           &parent, &token, &error)) {
      if (!JS_IsExceptionPending(cx))
        JS_ReportErrorASCII(cx, "activation-runtime-import-result-admission-denied:%u",
                            static_cast<unsigned>(error));
      return false;
    }
    result.token = {token.generation, token.id};
    result.live = true;
    return true;
  }
  bool rollback(JSContext* cx, JobOwners& work, NativeOwner& native, NativeOwner& result) override {
    return resultRetired(cx, result) && native_.acknowledgeRetirement(cx, native) &&
           jobs_.retireAcceptedImport(cx, work);
  }
  bool park(JSContext* cx, JobOwners& work) override { return jobs_.parkAccepted(cx, work); }
  bool resume(JSContext* cx, JobOwners& work) override {
    // Typed lifting executes inside the genuine admitted Promise reaction's
    // frame. Its Task/Queued owners account that execution; the parked import
    // task owns only the original in-flight lowering until its ACK below.
    Token continuation{};
    if (!jobs_.currentContinuation(continuation) || !work.task_live || work.queued_live)
      return false;
    return true;
  }
  bool complete(JSContext* cx, JobOwners& work) override {
    // Cancellation does not enter application code or replace the current
    // continuation. Actual lift completion is the separately resumed frame.
    return jobs_.retireAcceptedImport(cx, work);
  }
  bool physicallyRetired(JSContext* cx, NativeOwner& native, NativeOwner& result) override {
    return resultRetired(cx, result) && native_.acknowledgeRetirement(cx, native);
  }
};

} // namespace lsf::typescript::activation
