//! Public diagnostics use fixed producer vocabularies, never arbitrary atoms.

use super::{public_platform_message, ErrorDetail, InvocationLimits, PlatformError};

// Admission controller/quota/timing/policy diagnostics. These are schema
// spellings, never tenant identities, queue names, credentials or guest data.
const SCOPES: &[&str] = &[
    "request",
    "node",
    "tenant",
    "revision",
    "trust-class",
    "queue-class",
];
const DIMENSIONS: &[&str] = &[
    "cpu-fuel",
    "memory-bytes",
    "wall-time-micros",
    "child-calls",
    "outbound-requests",
    "state-read-bytes",
    "state-write-bytes",
    "blob-read-bytes",
    "blob-write-bytes",
    "log-bytes",
    "effect-count",
    "concurrency",
    "queue",
    "principal",
    "identifier",
    "revision",
    "priority",
    "payload-bytes",
    "backend",
    "state-model",
    "call-depth",
    "architecture",
    "region",
    "zone",
    "threading",
    "required-features",
    "cell-class",
    "overload",
    "load",
    "cpu-pressure",
    "memory-pressure",
    "metadata",
    "deadline",
    "budget",
    "trust-class",
    "activation-id",
    "quota",
    "configuration",
];
const ADMISSION_REASONS: &[&str] = &[
    "capacity-exhausted",
    "tenant-not-authorized",
    "principal-not-authorized",
    "invalid-identifier",
    "revision-not-available",
    "priority-not-authorized",
    "payload-too-large",
    "unsupported-execution-requirement",
    "placement-not-compatible",
    "no-compatible-cell",
    "cell-class-not-authorized",
    "node-not-accepting",
    "load-sample-not-current",
    "node-overloaded",
    "invalid-load-sample",
    "load-source-unavailable",
    "out-of-order-load-sample",
    "trust-class-not-authorized",
    "metadata-limit",
    "unsupported-budget-dimension",
    "no-executable-capacity",
    "deadline-exceeded",
    "deadline-out-of-range",
    "invalid-budget",
    "activation-id-unavailable",
    "reservation-not-live",
    "reservation-already-started",
    "quota-state-unavailable",
    "queue-estimate-overflow",
    "missing-effective-deadline",
    "queue-deadline-infeasible",
    "invalid-node-identity",
    "invalid-node-budget",
    "invalid-overload-threshold",
    "invalid-deadline-policy",
    "invalid-cell-classes",
    "invalid-cell-class",
    "unknown-cell-class",
    "invalid-queue-class",
    "overlapping-priority-ranges",
    "unmapped-priority",
    "invalid-trust-class",
    "invalid-tenant-policy",
];
const SCHEDULER_REASONS: &[&str] = &[
    "pool-topology",
    "cell-class",
    "pool-changes-closed",
    "cancelled",
    "deadline-exceeded",
    "handoff-closed",
    "foreign-admission",
    "cancellation-identity",
    "shutdown",
    "duplicate-activation",
    "queue-full",
    "sequence-exhausted",
    "activation-not-found",
    "configuration",
    "local-node-unavailable",
    "all-cells-quarantined",
    "pool-lease-mismatch",
];
const OPERATIONS: &[&str] = &["try-acquire", "cancel-waiting", "quarantine"];
const RESOURCES: &[&str] = &[
    "memory",
    "cpu",
    "cpu-fuel",
    "memory-bytes",
    "wall-time-micros",
    "log-bytes",
];

#[derive(Clone, Copy)]
enum Value {
    Unsigned,
    Known(&'static [&'static str]),
}

pub(super) fn public_platform_error(
    error: PlatformError,
    limits: &InvocationLimits,
) -> PlatformError {
    PlatformError {
        code: error.code,
        message: truncate_utf8(
            public_platform_message(error.code),
            limits.max_platform_error_message_bytes,
        ),
        retryable: error.retryable,
        details: error
            .details
            .into_iter()
            .take(limits.max_platform_error_details)
            .filter_map(|detail| public_detail(detail, limits))
            .collect(),
    }
}

fn fields(kind: &str) -> Option<&'static [(&'static str, Value)]> {
    use Value::{Known, Unsigned};
    Some(match kind {
        "cell-pool.all-quarantined" => &[("quarantined", Unsigned)],
        "cell-pool.unsupported-operation" => &[("operation", Known(OPERATIONS))],
        "cell-pool.sequence-exhausted" => &[("scope", Known(&["phase0"]))],
        "cell-pool.deadline-exceeded" => &[("deadline_unix_millis", Unsigned)],
        "resource.limit" => &[
            ("resource", Known(RESOURCES)),
            ("requested", Unsigned),
            ("limit", Unsigned),
        ],
        "admission.limit" => &[
            ("scope", Known(SCOPES)),
            ("dimension", Known(DIMENSIONS)),
            ("reason", Known(ADMISSION_REASONS)),
        ],
        "scheduler.limit" => &[("reason", Known(SCHEDULER_REASONS))],
        "activation.resource-exhausted" => &[
            ("dimension", Known(DIMENSIONS)),
            ("limit", Unsigned),
            ("consumed", Unsigned),
            ("requested", Unsigned),
        ],
        "activation.deadline-exceeded" | "budget.deadline-out-of-range" => &[
            ("deadline_unix_millis", Unsigned),
            ("admitted_at_unix_millis", Unsigned),
        ],
        "budget.unsupported-request-dimension" | "budget.unsupported-consumption-dimension" => {
            &[("dimension", Known(DIMENSIONS)), ("value", Unsigned)]
        }
        "budget.accounting-overflow" | "budget.invalid-accounting-operation" => {
            &[("dimension", Known(DIMENSIONS))]
        }
        "route.unavailable" => &[("route_generation", Unsigned)],
        "retry" => &[("retry_after_millis", Unsigned)],
        // State versions, cancellation reasons and engine diagnostics are
        // opaque data. Their existence does not authorize public disclosure.
        _ => return None,
    })
}

fn public_detail(mut detail: ErrorDetail, limits: &InvocationLimits) -> Option<ErrorDetail> {
    let allowed = fields(&detail.kind)?;
    let mut public = latent_core::Metadata::new();
    for (key, kind) in allowed.iter().take(limits.max_platform_error_fields) {
        let Some(value) = detail.fields.remove(*key) else {
            continue;
        };
        if value.len() > limits.max_string_bytes {
            continue;
        }
        let valid = match kind {
            Value::Known(values) => values.contains(&value.as_str()),
            Value::Unsigned => {
                !value.is_empty()
                    && value.len() <= 20
                    && value.bytes().all(|byte| byte.is_ascii_digit())
                    && value.parse::<u64>().is_ok()
            }
        };
        if valid {
            public.insert((*key).to_owned(), value);
        }
    }
    if public.is_empty() {
        return None;
    }
    Some(ErrorDetail {
        kind: detail.kind,
        fields: public,
    })
}

fn truncate_utf8(value: &str, maximum: usize) -> String {
    let mut end = maximum.min(value.len());
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}
