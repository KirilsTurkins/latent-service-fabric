#pragma once
#include "broker_accounting.h"
#include "promise_records.h"

namespace lsf::typescript::activation {

class BrokerPromiseAccounting final : public PromiseAccounting {
public:
  enum class Phase { CompilerSnapshot, Activation, Unavailable };
private:
  using PhaseAccessor = Phase (*)(JSContext*);
  PhaseAccessor phase_;
  BrokerAccounting& jobs_;

  static bool failure(JSContext* cx, const char* operation,
                      latent_runtime_activation_error_t error) {
    if (!JS_IsExceptionPending(cx))
      JS_ReportErrorASCII(cx, "activation-runtime-promise-%s-denied:%u", operation,
                          static_cast<unsigned>(error));
    return false;
  }

public:
  BrokerPromiseAccounting(PhaseAccessor phase, BrokerAccounting& jobs)
      : phase_(phase), jobs_(jobs) {}

  bool beforeAllocate(JSContext* cx, NativeOwner& owner) override {
    if (!phase_ || phase_(cx) == Phase::Unavailable) {
      JS_ReportErrorASCII(cx, "activation-runtime-promise-phase-unavailable");
      return false;
    }
    // Snapshot evaluation observes intrinsic state but imports no authority.
    // Its process/heap remains subject to the original bounded compiler recipe.
    if (phase_(cx) == Phase::CompilerSnapshot) return true;
    Token inherited{};
    const bool has_parent = jobs_.currentContinuation(inherited);
    latent_runtime_activation_token_t parent{inherited.generation, inherited.id};
    latent_runtime_activation_token_t token{};
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE,
                                           has_parent ? &parent : nullptr, &token, &error))
      return failure(cx, "native-register", error);
    owner.token = {token.generation, token.id};
    owner.live = true;
    return true;
  }

  bool acknowledgeRetirement(JSContext* cx, NativeOwner& owner) override {
    if (!owner.live) return true;
    latent_runtime_activation_token_t token{owner.token.generation, owner.token.id};
    latent_runtime_activation_error_t error{};
    if (!latent_runtime_activation_settle(&token, &error))
      return failure(cx, "native-settle", error);
    owner.live = false;
    return true;
  }
};

} // namespace lsf::typescript::activation
