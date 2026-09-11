//! Client-side public diagnostic vocabulary. A peer is not a trusted producer.
use latent_core::ErrorDetail;
use serde_json::{json, Map, Value as JsonValue};

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

const CATALOG_REASONS: &[&str] = &[
    "deployment-generation-conflict",
    "deployment-scope-conflict",
    "deployment-not-found",
    "deployment-count-limit",
    "invalid-deployment-target",
    "catalog-root-already-owned",
    "catalog-path-durability-uncertain",
    "catalog-state-byte-limit",
    "snapshot-publication-busy",
    "route-index-limit",
    "route-not-found",
    "route-generation-not-retained",
    "route-generation-exhausted",
    "missing-tenant",
    "invalid-invocation-target",
    "invalid-deployment-page-size",
    "invalid-deployment-page-scope",
    "invalid-deployment-page-token",
    "expired-deployment-page-token",
    "deployment-page-byte-limit",
    "commit-durability-uncertain",
    "stale-route-generation",
];

pub(super) fn sanitize(details: &[ErrorDetail]) -> Vec<JsonValue> {
    details
        .iter()
        .take(16)
        .filter_map(|detail| {
            if detail.kind.len() > 128
                || detail.fields.len() > 32
                || detail
                    .fields
                    .iter()
                    .any(|(key, value)| key.len() > 128 || value.len() > 1024)
            {
                return None;
            }
            if detail.kind == "deployment-catalog" {
                let reason = detail.fields.get("reason")?;
                return CATALOG_REASONS
                    .contains(&reason.as_str())
                    .then(|| json!({"kind":"deployment-catalog", "fields":{"reason":reason}}));
            }
            if detail.kind == "deployment-mutation" {
                if detail.fields.get("committed")? != "true" {
                    return None;
                }
                let operation = detail.fields.get("operation")?;
                if !["apply", "delete"].contains(&operation.as_str()) {
                    return None;
                }
                let object = generation(detail.fields.get("object_generation")?)?;
                let catalog = generation(detail.fields.get("catalog_generation")?)?;
                return Some(json!({"kind":"deployment-mutation", "fields":{
                "operation":operation,"committed":"true","object_generation":object,
                "catalog_generation":catalog}}));
            }
            let schema = fields(&detail.kind)?;
            let mut output = Map::new();
            for (key, rule) in schema {
                let Some(value) = detail.fields.get(*key) else {
                    continue;
                };
                let accepted = match rule {
                    Value::Unsigned => value
                        .parse::<u64>()
                        .ok()
                        .filter(|n| n.to_string() == *value)
                        .map(|n| n.to_string()),
                    Value::Known(known) => known.contains(&value.as_str()).then(|| value.clone()),
                };
                if let Some(value) = accepted {
                    output.insert((*key).to_owned(), json!(value));
                }
            }
            (!output.is_empty()).then(|| json!({"kind":detail.kind, "fields":output}))
        })
        .collect()
}
fn generation(value: &str) -> Option<String> {
    value
        .parse::<u64>()
        .ok()
        .filter(|n| *n > 0 && n.to_string() == value)
        .map(|n| n.to_string())
}
