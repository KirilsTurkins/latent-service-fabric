// Checked DOM/Web-IDL timeout conversion for the declared activation profile.
#pragma once
#include "extension-api.h"
#include "js/Conversions.h"
#include <cmath>
#include <cstdint>
#include <limits>

namespace lsf::typescript::activation {
inline bool timeout_nanoseconds(JSContext* cx, JS::HandleValue value, uint64_t* nanos) {
  double number = 0;
  if (!JS::ToNumber(cx, value, &number)) return false;
  if (!std::isfinite(number))
    return api::throw_error(cx, api::Errors::TypeError, "AbortSignal.timeout", "milliseconds",
                            "be finite and in the unsigned 64-bit range");
  const double integer = std::trunc(number);
  // The double representation of 2^64 is exact, while UINT64_MAX rounds up to
  // it. Compare against the exclusive endpoint before any integer conversion.
  if (integer < 0 || integer >= 18446744073709551616.0)
    return api::throw_error(cx, api::Errors::TypeError, "AbortSignal.timeout", "milliseconds",
                            "be in the unsigned 64-bit range");
  const auto millis = static_cast<uint64_t>(integer);
  if (millis > std::numeric_limits<uint64_t>::max()/1000000)
    return api::throw_error(cx, api::Errors::TypeError, "AbortSignal.timeout", "milliseconds",
                            "fit the selected activation timer's nanosecond representation");
  *nanos = millis*1000000;
  return true;
}
} // namespace lsf::typescript::activation
