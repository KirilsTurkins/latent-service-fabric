/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

uint64_t exports_tests_metrics_api_run(uint32_t which, probe_string_t *text,
                                      uint64_t handle) {
    (void)handle;
    probe_tuple2_string_string_t attribute = {LSF_LITERAL("region"), LSF_LITERAL("east")};
    latent_telemetry_custom_metric_t metric = {
        .name = *text,
        .kind = which < 3 ? (uint8_t)which : LATENT_TELEMETRY_CUSTOM_METRIC_KIND_HISTOGRAM,
        .value = 2.0,
        .unit = LSF_LITERAL("1"),
        .attributes = {&attribute, 1},
    };
    bool accepted = false;
    latent_telemetry_custom_telemetry_error_t error = {0};
    bool ok = latent_telemetry_custom_emit_metric(&metric, &accepted, &error);
    probe_string_free(text);
    if (ok) return accepted ? 1 : 0;
    switch (error.tag) {
    case LATENT_TELEMETRY_CUSTOM_TELEMETRY_ERROR_INVALID_NAME: return 10;
    case LATENT_TELEMETRY_CUSTOM_TELEMETRY_ERROR_BUDGET_EXHAUSTED: return 11;
    case LATENT_TELEMETRY_CUSTOM_TELEMETRY_ERROR_UNAVAILABLE: return 12;
    default: __builtin_trap();
    }
}
