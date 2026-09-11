mod validation;

use std::time::{Duration, Instant};

use latent_core::ActivationId;
use latent_wire::invocation::proto;
use serde_json::{json, Value};

use super::super::{fixtures::Fixture, MeasurementNode, Result};

#[derive(Clone, Copy)]
pub(in super::super) enum Case {
    Success,
    Echo,
    FirstEcho,
    Domain,
    Malformed,
    Trap,
    Fuel,
    Memory,
    Deadline,
    Cancel,
    LogDenied,
    LogAccepted,
    Context,
    FreshStore,
}

impl Case {
    pub fn name(self) -> &'static str {
        match self {
            Self::Success | Self::Echo | Self::FirstEcho => "success",
            Self::Domain => "domain",
            Self::Malformed => "malformed",
            Self::Trap => "trap",
            Self::Fuel => "fuel",
            Self::Memory => "memory",
            Self::Deadline => "deadline",
            Self::Cancel => "cancel",
            Self::LogDenied => "log_denied",
            Self::LogAccepted => "log_accepted",
            Self::Context => "context",
            Self::FreshStore => "fresh_store",
        }
    }
    pub fn request<'a>(
        self,
        node: &'a MeasurementNode,
        id: &str,
    ) -> (&'a Fixture, proto::InvokeRequest) {
        let (fixture, function, payload) = match self {
            Self::Echo => (&node.fixtures.echo, "echo", json!(["phase0 warm echo"])),
            Self::FirstEcho => (
                &node.fixtures.echo,
                "echo",
                json!(["phase0 retained first echo"]),
            ),
            Self::Domain => (&node.fixtures.generic, "checked", json!([false])),
            Self::Malformed => (&node.fixtures.generic, "combine", json!(["not-an-s32", 1])),
            Self::Trap => (&node.fixtures.generic, "trap", json!([])),
            Self::Fuel | Self::Deadline | Self::Cancel => {
                (&node.fixtures.generic, "spin", json!([]))
            }
            Self::Memory => (&node.fixtures.generic, "grow", json!([])),
            Self::LogDenied | Self::LogAccepted => (
                &node.fixtures.capabilities,
                "log-probe",
                json!(["measurement \"line\"\n", []]),
            ),
            Self::Context => (&node.fixtures.capabilities, "snapshot", json!([])),
            Self::FreshStore => (&node.fixtures.generic, "bump", json!([])),
            Self::Success => (&node.fixtures.generic, "combine", json!([-4, 9])),
        };
        let mut request = fixture.request(function, id, &payload);
        let budget = request.budget.as_mut().expect("fixture budget");
        match self {
            Self::Echo | Self::FirstEcho => {
                budget.cpu_fuel = 10_000_000_000;
                budget.memory_bytes = 16 * 1024 * 1024;
            }
            Self::Fuel => budget.cpu_fuel = 50_000,
            Self::Memory => budget.memory_bytes = 4 * 1024 * 1024,
            Self::Deadline => {
                budget.cpu_fuel = 10_000_000_000;
                budget.wall_time_limit_millis = Some(10);
            }
            Self::Cancel => {
                budget.cpu_fuel = 10_000_000_000;
                budget.wall_time_limit_millis = Some(5000);
            }
            Self::LogDenied => budget.log_bytes = 0,
            Self::LogAccepted => budget.log_bytes = 4096,
            Self::Context => {
                request.metadata.insert("guest.visible".into(), id.into());
                request.metadata.insert(
                    "internal.private".into(),
                    "measurement-private-context".into(),
                );
            }
            _ => {}
        }
        (fixture, request)
    }
}

pub(in super::super) struct Observation {
    pub id: String,
    pub case: &'static str,
    pub outcome: &'static str,
    pub elapsed: u64,
    pub consumption: proto::BudgetConsumption,
    pub timing: Option<latent_wasmtime::Phase0InvocationTiming>,
}

impl Observation {
    pub fn value(&self) -> Value {
        let consumption = &self.consumption;
        json!({"activation_id":self.id,"case":self.case,"outcome":self.outcome,"rpc_latency_micros":self.elapsed.to_string(),
            "consumption":{"cpu_fuel":consumption.cpu_fuel.to_string(),"peak_memory_bytes":consumption.peak_memory_bytes.to_string(),
                "wall_time_micros":consumption.wall_time_micros.to_string(),"log_bytes":consumption.log_bytes.to_string()},
            "timing":self.timing.map(timing_value),"retained_consumption_matches":true})
    }
}

pub(in super::super) async fn execute(
    node: &MeasurementNode,
    case: Case,
    id: &str,
) -> Result<Observation> {
    let (fixture, request) = case.request(node, id);
    let started = Instant::now();
    let response = if matches!(case, Case::Cancel) {
        cancel_running(node, &fixture.tenant, request, id).await?
    } else {
        node.invoke(&fixture.tenant, request).await?
    };
    finish(
        node,
        case,
        id,
        &fixture.tenant,
        response,
        u64::try_from(started.elapsed().as_micros())?,
    )
    .await
}

pub(in super::super) async fn finish(
    node: &MeasurementNode,
    case: Case,
    id: &str,
    tenant: &str,
    response: proto::InvokeResponse,
    elapsed: u64,
) -> Result<Observation> {
    let expected_release = match case {
        Case::Echo | Case::FirstEcho => &node.fixtures.echo.release_digest,
        Case::LogDenied | Case::LogAccepted | Case::Context => {
            &node.fixtures.capabilities.release_digest
        }
        _ => &node.fixtures.generic.release_digest,
    };
    if response.activation_id != id
        || &response.release_digest != expected_release
        || response.revision_id.is_empty()
        || response.release_digest.is_empty()
        || response.route_generation == 0
    {
        return Err("invocation receipt lost resolved identity".into());
    }
    let outcome = validation::response(case, id, &response)?;
    let status = node.status(tenant, id).await?;
    if status.activation_id != id
        || status.terminal_state.is_none()
        || status.final_consumption != response.consumption
    {
        return Err("retained terminal accounting mismatch".into());
    }
    let consumption = response.consumption.ok_or("missing terminal consumption")?;
    let timing = node
        .node
        .backend
        .take_invocation_timing(&ActivationId(id.to_owned()));
    if timing.is_none() && !matches!(case, Case::Cancel | Case::Deadline | Case::Malformed) {
        return Err("missing completed backend timing".into());
    }
    Ok(Observation {
        id: id.to_owned(),
        case: case.name(),
        outcome,
        elapsed,
        consumption,
        timing,
    })
}

async fn cancel_running(
    node: &MeasurementNode,
    tenant: &str,
    request: proto::InvokeRequest,
    id: &str,
) -> Result<proto::InvokeResponse> {
    let invocation = node.invoke(tenant, request);
    let control = async {
        wait_running(node, tenant, id).await?;
        let cancellation = node.cancel(tenant, id, "measurement cancellation").await?;
        if cancellation.disposition != proto::CancelDisposition::Accepted as i32 {
            return Err("running cancellation was not accepted".into());
        }
        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
    };
    // The server may return the cancelled Invoke before the Cancel RPC response.
    // Join both receipts rather than incorrectly treating that ordering as failure.
    let (response, cancellation) = tokio::join!(invocation, control);
    cancellation?;
    response
}

pub(in super::super) async fn wait_running(
    node: &MeasurementNode,
    tenant: &str,
    id: &str,
) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(2);
    for _ in 0..200 {
        match node.status(tenant, id).await {
            Ok(status) => {
                if let Some(terminal) = status.terminal_state.as_deref() {
                    let code = match &status.terminal_outcome {
                        Some(proto::activation_status::TerminalOutcome::PlatformFailure(error)) => {
                            error.code.as_str()
                        }
                        Some(proto::activation_status::TerminalOutcome::DeclaredError(_)) => {
                            "declared-error"
                        }
                        Some(proto::activation_status::TerminalOutcome::Succeeded(_)) => "success",
                        None => "missing-outcome",
                    };
                    return Err(format!(
                        "expected running activation already terminal: id={} terminal={} code={}",
                        diagnostic_token(id, 96),
                        diagnostic_token(terminal, 32),
                        diagnostic_token(code, 48),
                    )
                    .into());
                }
                if status.phase == "running" {
                    return Ok(());
                }
            }
            Err(error)
                if error
                    .downcast_ref::<tonic::Status>()
                    .is_some_and(|status| status.code() == tonic::Code::NotFound) => {}
            Err(error) => return Err(error),
        }
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    Err("running activation observation bound".into())
}

fn diagnostic_token(value: &str, maximum: usize) -> String {
    value
        .chars()
        .take(maximum)
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '_'
            }
        })
        .collect()
}

fn timing_value(t: latent_wasmtime::Phase0InvocationTiming) -> Value {
    json!({"backend_setup_micros":t.backend_setup_micros.to_string(),"guest_call_micros":t.guest_call_micros.to_string(),
        "host_call_micros":t.host_call_micros.to_string(),"host_call_count":t.host_call_count.to_string(),
        "component_post_return_micros":t.component_post_return_micros.to_string(),
        "activation_resource_reclamation_micros":t.activation_resource_reclamation_micros.to_string(),
        "outcome_classification_micros":t.outcome_classification_micros.to_string(),"reusable_proof_micros":t.reusable_proof_micros.to_string(),
        "backend_total_micros":t.backend_total_micros.to_string()})
}
