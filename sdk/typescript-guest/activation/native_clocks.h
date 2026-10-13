// Exact scoped standard-clock reads; this port grants no clock authority.
#pragma once
#include "clocks.h"
#include "clock_values.h"
#include "extension-api.h"
#include "js/CallArgs.h"
#include "js/CompilationAndEvaluation.h"
#include "js/SourceText.h"
#include <cstdint>

namespace lsf::typescript::activation {
class Clocks final {
  ClockValues values_;

  static bool running(JSContext* cx) {
    auto* engine = api::Engine::get(cx);
    if (!engine || engine->state() != api::EngineState::Initialized) {
      JS_ReportErrorASCII(cx, "snapshot-time-clock-observation-unsupported");
      return false;
    }
    return true;
  }

public:
  bool wall(JSContext* cx, double& milliseconds) {
    if (!running(cx)) return false;
    const auto value = latent_clock_wall_now_unix_millis();
    // JS Date's millisecond range is finite and exactly representable here.
    if (!ClockValues::wall(value, milliseconds)) {
      JS_ReportErrorASCII(cx, "standard-runtime-clock-outside-Date-range");
      return false;
    }
    return true;
  }

  bool performance(JSContext* cx, double& elapsed, double& origin) {
    if (!running(cx)) return false;
    const auto now = latent_clock_monotonic_now_nanos();
    const auto first_wall = values_.sampled() ? 0 : latent_clock_wall_now_unix_millis();
    if (values_.performance(now, first_wall, elapsed, origin)) return true;
    JS_ReportErrorASCII(cx, "standard-runtime-clock-invalid-monotonic-or-Date-range");
    return false;
  }
};

bool install_clock_globals(JSContext*, JS::HandleObject);
} // namespace lsf::typescript::activation
