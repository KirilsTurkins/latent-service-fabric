pub(super) fn valid_metric_dimension(name: &str, value: &str) -> bool {
    match name {
        "stage" => matches!(
            value,
            "receipt"
                | "resolution"
                | "admission"
                | "queueing"
                | "materialization"
                | "execution"
                | "cancellation"
                | "failure"
                | "completion"
                | "cleanup"
        ),
        "outcome" => matches!(
            value,
            "guest_success" | "guest_domain_error" | "platform_failure"
        ),
        "resource" => matches!(
            value,
            "cpu_fuel"
                | "memory_bytes"
                | "wall_time_micros"
                | "child_calls"
                | "outbound_requests"
                | "state_read_bytes"
                | "state_write_bytes"
                | "blob_read_bytes"
                | "blob_write_bytes"
                | "log_bytes"
                | "effect_count"
        ),
        "cell_class" => matches!(
            value,
            "tiny" | "small" | "standard" | "large" | "extra-large"
        ),
        "result" => matches!(
            value,
            "accepted"
                | "already_terminal"
                | "not_found"
                | "ok"
                | "failed"
                | "acquired"
                | "rejected"
                | "returned"
                | "declared_error"
                | "trapped"
                | "cancelled"
                | "deadline_exceeded"
                | "fuel_exhausted"
                | "memory_exhausted"
                | "platform_error"
        ),
        "reason" => matches!(
            value,
            "queue_full" | "queue_closed" | "invalid_record" | "sink_failure" | "sink_timeout"
        ),
        "kind" => matches!(
            value,
            "cancelled" | "deadline_exceeded" | "fuel_exhausted" | "memory_exhausted"
        ),
        "operation" => matches!(value, "prepare" | "release"),
        "disposition" => matches!(
            value,
            "reusable"
                | "quarantine"
                | "no_cell"
                | "released"
                | "quarantined"
                | "reclaimed_before_execution"
                | "abandoned"
                | "failed"
        ),
        "severity" => matches!(
            value,
            "trace" | "debug" | "info" | "warn" | "error" | "fatal"
        ),
        "error_code" => latent_core::PlatformErrorCode::from_wire_code(value).is_some(),
        _ => false,
    }
}
