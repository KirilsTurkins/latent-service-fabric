// Checked per-Store values only; all reads remain with the typed host caller.
#pragma once
#include <cstdint>

namespace lsf::typescript::activation {
class ClockValues final {
  bool sampled_ = false;
  uint64_t monotonic_origin_ = 0;
  uint64_t last_monotonic_ = 0;
  uint64_t wall_origin_millis_ = 0;
public:
  static constexpr uint64_t maximum_date_millis = 8640000000000000ULL;
  bool sampled() const { return sampled_; }
  static bool wall(uint64_t actual, double& milliseconds) {
    if (actual > maximum_date_millis) return false;
    milliseconds = static_cast<double>(actual);
    return true;
  }
  bool performance(uint64_t actual_nanos, uint64_t first_wall_millis,
                   double& elapsed, double& epoch) {
    if (sampled_ && actual_nanos < last_monotonic_) return false;
    if (!sampled_) {
      if (first_wall_millis > maximum_date_millis) return false;
      monotonic_origin_ = actual_nanos;
      wall_origin_millis_ = first_wall_millis;
      sampled_ = true;
    }
    last_monotonic_ = actual_nanos;
    elapsed = static_cast<double>(actual_nanos - monotonic_origin_) / 1000000.0;
    epoch = static_cast<double>(wall_origin_millis_);
    return true;
  }
};
} // namespace lsf::typescript::activation
