//! Explicit disposable-fixture observation at the original public redaction boundary.
//! No original error strings, payload, provider names or ownership handles escape.
use latent_core::{ActivationBudget, BudgetDimension, PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::time::Instant;

pub(crate) const PREFIX: &str = "LSF_LOCAL_SERVICE_REFUSAL_V1 ";
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum Stage {
    Setup,
    BrokerDispatch,
    ChildStart,
    ChildCompletion,
}

pub(crate) struct Observer {
    enabled: bool,
    seen: bool,
}
impl Observer {
    pub(crate) const fn new(enabled: bool) -> Self {
        Self {
            enabled,
            seen: false,
        }
    }
    pub(crate) const fn pending(&self) -> bool {
        self.enabled && !self.seen
    }
    pub(crate) fn capture<'a>(
        &mut self,
        activation: &'a str,
        stage: Stage,
        error: &PlatformError,
        budget: &ActivationBudget,
        now: Instant,
    ) -> Option<Record<'a>> {
        if !self.enabled || self.seen {
            return None;
        }
        self.seen = true;
        // Only original dev scenario root identities, never guest/provider strings.
        if activation.len() != 36
            || !activation.starts_with("dev-")
            || !activation.as_bytes()[4..].iter().all(u8::is_ascii_hexdigit)
            || activation.as_bytes()[4..]
                .iter()
                .any(u8::is_ascii_uppercase)
        {
            return None;
        }
        let remaining = budget.remaining_at(now);
        let descendants = budget.descendant_snapshot().ok().map(|value| Descendants {
            depth: value.depth,
            live_children: value.live_children,
            live_descendants: value.live_descendants,
            reserved_memory_bytes: value.reserved_memory_bytes,
            live_observed_child_memory_bytes: value.live_observed_child_memory_bytes,
            closed: value.closed,
        });
        Some(Record {
            schema_version: "latent.dev.local-service-refusal.v1",
            activation_id: activation,
            sampling: "before-public-redaction-after-adapter-return",
            stage,
            code: error.code.wire_code(),
            reason: reason(error),
            typed_budget: typed_budget(error),
            remaining: Remaining {
                cpu_fuel: remaining.cpu_fuel,
                memory_bytes: remaining.memory_bytes,
                child_calls: remaining.child_calls,
                wall_time_limit_millis: remaining.wall_time_limit_millis,
            },
            descendants,
        })
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Record<'a> {
    schema_version: &'static str,
    activation_id: &'a str,
    sampling: &'static str,
    stage: Stage,
    code: &'static str,
    reason: &'static str,
    typed_budget: Option<TypedBudget>,
    remaining: Remaining,
    descendants: Option<Descendants>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Remaining {
    cpu_fuel: u64,
    memory_bytes: u64,
    child_calls: u32,
    wall_time_limit_millis: Option<u64>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Descendants {
    depth: u8,
    live_children: usize,
    live_descendants: usize,
    reserved_memory_bytes: u64,
    live_observed_child_memory_bytes: u64,
    closed: bool,
}
#[derive(Serialize, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct TypedBudget {
    dimension: &'static str,
    limit: u64,
    consumed: u64,
    requested: u64,
}
fn reason(error: &PlatformError) -> &'static str {
    if typed_budget(error).is_some() {
        "typed-budget"
    } else if error.code == PlatformErrorCode::ResourceExhausted
        && !error.retryable
        && error.details.is_empty()
        && error.message == "descendant-capacity"
    {
        "descendant-capacity"
    } else {
        "unclassified"
    }
}
fn decimal(value: &str) -> Option<u64> {
    if value.is_empty()
        || value.len() > 20
        || !value.bytes().all(|c| c.is_ascii_digit())
        || (value.len() != 1 && value.starts_with('0'))
    {
        return None;
    }
    value.parse().ok()
}
fn typed_budget(error: &PlatformError) -> Option<TypedBudget> {
    if error.code != PlatformErrorCode::ResourceExhausted || error.retryable {
        return None;
    }
    let [detail] = error.details.as_slice() else {
        return None;
    };
    if detail.kind != "activation.resource-exhausted" || detail.fields.len() != 4 {
        return None;
    }
    let raw = detail.fields.get("dimension")?;
    let dimension = BudgetDimension::PHASE1_ENFORCED
        .into_iter()
        .chain(BudgetDimension::LATER_PHASE)
        .find(|d| d.wire_name() == raw)?
        .wire_name();
    Some(TypedBudget {
        dimension,
        limit: decimal(detail.fields.get("limit")?)?,
        consumed: decimal(detail.fields.get("consumed")?)?,
        requested: decimal(detail.fields.get("requested")?)?,
    })
}
pub(crate) fn emit(record: &Record<'_>) {
    // Every field is fixed or bounded; failed diagnostics never change the WIT error.
    if let Ok(line) = serde_json::to_string(record) {
        if line.len() <= 2048 {
            use std::io::Write;
            let _ = writeln!(std::io::stderr().lock(), "{PREFIX}{line}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{BudgetError, EffectiveActivationBudget, ResourceBudget};
    fn budget() -> ActivationBudget {
        let limits = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 1024,
            wall_time_limit_millis: None,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        ActivationBudget::new(
            EffectiveActivationBudget::admit_now(&limits, &limits, &limits, None).unwrap(),
        )
    }
    #[test]
    fn disabled_and_first_per_activation_do_not_share_global_admission() {
        let error = BudgetError::Exhausted {
            dimension: BudgetDimension::MemoryBytes,
            limit: 1024,
            consumed: 900,
            requested: 200,
        }
        .to_platform_error();
        let budget = budget();
        let now = Instant::now();
        let a = "dev-00000000000000000000000000000001";
        let b = "dev-00000000000000000000000000000002";
        assert!(Observer::new(false)
            .capture(a, Stage::Setup, &error, &budget, now)
            .is_none());
        let mut first = Observer::new(true);
        let original = error.clone();
        let row = serde_json::to_value(
            first
                .capture(a, Stage::ChildStart, &error, &budget, now)
                .unwrap(),
        )
        .unwrap();
        assert_eq!(row["activationId"], a);
        assert_eq!(row["typedBudget"]["dimension"], "memory-bytes");
        assert!(first
            .capture(a, Stage::BrokerDispatch, &error, &budget, now)
            .is_none());
        assert!(Observer::new(true)
            .capture(b, Stage::Setup, &error, &budget, now)
            .is_some());
        assert_eq!(error, original);
    }
    #[test]
    fn typed_budget_refuses_coercion_unknown_details_and_private_error_text() {
        let original = BudgetError::Exhausted {
            dimension: BudgetDimension::CpuFuel,
            limit: u64::MAX,
            consumed: 1,
            requested: 2,
        }
        .to_platform_error();
        assert_eq!(typed_budget(&original).unwrap().limit, u64::MAX);
        for (key, value) in [
            ("limit", "01"),
            ("limit", "-1"),
            ("limit", "18446744073709551616"),
            ("limit", "?"),
            ("dimension", "private-secret"),
        ] {
            let mut changed = original.clone();
            changed.details[0].fields.insert(key.into(), value.into());
            assert!(typed_budget(&changed).is_none());
        }
        let mut changed = original.clone();
        changed.details[0]
            .fields
            .insert("extra".into(), "secret".into());
        assert!(typed_budget(&changed).is_none());
        let mut changed = original;
        changed.code = PlatformErrorCode::Internal;
        assert!(typed_budget(&changed).is_none());
        changed.message = "private-secret".into();
        let serialized = serde_json::to_string(
            &Observer::new(true)
                .capture(
                    "dev-00000000000000000000000000000001",
                    Stage::ChildStart,
                    &changed,
                    &budget(),
                    Instant::now(),
                )
                .unwrap(),
        )
        .unwrap();
        assert!(!serialized.contains("private-secret"));
        assert!(serialized.len() <= 2048);
    }
}
