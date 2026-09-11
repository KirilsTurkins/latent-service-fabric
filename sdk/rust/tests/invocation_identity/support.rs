//! A deterministic fixture server behind the public client trait, not a transport.

use std::future::poll_fn;
use std::sync::{Mutex, MutexGuard};
use std::task::{Context, Poll, Waker};

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BoxFuture, BudgetConsumption,
    ContractId, FunctionId, Metadata, PlatformErrorCode, ReleaseDigest, ResourceBudget, RevisionId,
    RouteGeneration, ServiceId, TenantId,
};
use latent_sdk::*;

pub const SERVER_ID: &str = "fixture-server-activation";

#[derive(Default)]
pub struct Fixture {
    state: Mutex<State>,
}

#[derive(Default)]
pub struct State {
    pub observed: Option<InvokeRequest>,
    pub root: Option<ActivationId>,
    pub status: Option<ActivationStatus>,
    pub invoke_count: usize,
    pub cancellation_requested: bool,
    pub fail_cancel: bool,
    response: Option<Result<InvocationOutcome, ClientTransportError>>,
    waiter: Option<Waker>,
}

impl Fixture {
    pub fn state(&self) -> MutexGuard<'_, State> {
        self.state.lock().expect("fixture state")
    }

    fn begin(&self, request: InvokeRequest) -> Result<(), ClientTransportError> {
        let mut state = self.state();
        state.invoke_count += 1;
        state.observed = Some(request.clone());
        if [
            &request.activation_id,
            &request.root_activation_id,
            &request.parent_activation_id,
        ]
        .into_iter()
        .flatten()
        .any(|id| id.0.is_empty())
            || (request.parent_activation_id.is_some() && request.root_activation_id.is_none())
        {
            return Err(transport_error("invalid invocation identity"));
        }
        let id = request
            .activation_id
            .unwrap_or_else(|| ActivationId(SERVER_ID.to_owned()));
        state.root = Some(request.root_activation_id.unwrap_or_else(|| id.clone()));
        state.status = Some(ActivationStatus {
            activation_id: id,
            phase: ActivationPhase::Running,
            terminal_state: None,
            terminal_outcome: None,
            final_consumption: None,
            last_updated_unix_millis: 1,
            terminal_at_unix_millis: None,
            metadata: Metadata::new(),
        });
        Ok(())
    }

    pub fn finish(&self, terminal: ActivationTerminalState, lose_response: bool) {
        let waiter = {
            let mut state = self.state();
            let status = state.status.as_mut().expect("started invocation");
            let consumption = BudgetConsumption {
                cpu_fuel: 7,
                ..BudgetConsumption::default()
            };
            let response = match terminal {
                ActivationTerminalState::Completed => {
                    status.phase = ActivationPhase::Committed;
                    status.terminal_outcome = Some(RetainedInvocationOutcome::Succeeded {
                        committed_state_version: None,
                        effect_ids: vec![],
                        metadata: Metadata::new(),
                    });
                    InvocationOutcome::Succeeded(InvokeResponse {
                        activation_id: status.activation_id.clone(),
                        revision_id: RevisionId("fixture-revision".to_owned()),
                        release_digest: ReleaseDigest("fixture-release".to_owned()),
                        route_generation: RouteGeneration(1),
                        payload: b"finished".to_vec(),
                        media_type: "text/plain".to_owned(),
                        committed_state_version: None,
                        effect_ids: vec![],
                        consumption: consumption.clone(),
                        metadata: Metadata::new(),
                    })
                }
                ActivationTerminalState::Cancelled => {
                    let error = PlatformError {
                        code: PlatformErrorCode::Cancelled,
                        message: "fixture cancellation acknowledged".to_owned(),
                        retryable: false,
                        details: vec![],
                    };
                    status.terminal_outcome =
                        Some(RetainedInvocationOutcome::PlatformFailure(error.clone()));
                    InvocationOutcome::PlatformFailure(PlatformInvocationFailure {
                        receipt: InvocationReceipt {
                            activation_id: status.activation_id.clone(),
                            revision_id: RevisionId("fixture-revision".to_owned()),
                            release_digest: ReleaseDigest("fixture-release".to_owned()),
                            route_generation: RouteGeneration(1),
                            consumption: consumption.clone(),
                        },
                        error,
                    })
                }
                _ => panic!("unsupported fixture terminal state"),
            };
            status.terminal_state = Some(terminal);
            status.final_consumption = Some(consumption);
            status.last_updated_unix_millis = 2;
            status.terminal_at_unix_millis = Some(2);
            state.response = Some(if lose_response {
                Err(transport_error("invocation response lost"))
            } else {
                Ok(response)
            });
            state.waiter.take()
        };
        if let Some(waiter) = waiter {
            waiter.wake();
        }
    }
}

impl LatentClient for Fixture {
    fn invoke(
        &self,
        request: InvokeRequest,
    ) -> BoxFuture<'_, Result<InvocationOutcome, ClientTransportError>> {
        Box::pin(async move {
            self.begin(request)?;
            poll_fn(|cx| {
                let mut state = self.state();
                if let Some(response) = state.response.take() {
                    Poll::Ready(response)
                } else {
                    state.waiter = Some(cx.waker().clone());
                    Poll::Pending
                }
            })
            .await
        })
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        _reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelResponse, ClientTransportError>> {
        Box::pin(async move {
            let mut state = self.state();
            if state.fail_cancel {
                return Err(transport_error("cancel transport unavailable"));
            }
            let Some(status) = state
                .status
                .as_ref()
                .filter(|s| &s.activation_id == activation_id)
            else {
                return Ok(CancelResponse::NotFound);
            };
            if let Some(terminal) = status.terminal_state {
                return Ok(CancelResponse::AlreadyTerminal(terminal));
            }
            state.cancellation_requested = true;
            Ok(CancelResponse::Accepted)
        })
    }

    fn get_activation<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<ActivationStatus, ClientTransportError>> {
        Box::pin(async move {
            self.state()
                .status
                .as_ref()
                .filter(|s| &s.activation_id == activation_id)
                .cloned()
                .ok_or_else(|| transport_error("activation not found"))
        })
    }
}

fn transport_error(message: &str) -> ClientTransportError {
    ClientTransportError {
        message: message.to_owned(),
        retryable: false,
    }
}

pub fn request() -> InvokeRequest {
    InvokeRequest {
        activation_id: Some(ActivationId("caller-activation".to_owned())),
        root_activation_id: None,
        parent_activation_id: None,
        target: InvocationTarget {
            tenant: TenantId("tenant".to_owned()),
            service: ServiceId("service".to_owned()),
            contract: ContractId("contract".to_owned()),
            function: FunctionId("function".to_owned()),
            route: None,
        },
        payload: vec![],
        media_type: "text/plain".to_owned(),
        options: InvokeOptions {
            deadline_unix_millis: None,
            priority: 0,
            idempotency_key: None,
            budget: ResourceBudget {
                cpu_fuel: 10,
                memory_bytes: 65_536,
                wall_time_limit_millis: None,
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: 0,
                effect_count: 0,
            },
            metadata: Metadata::new(),
        },
    }
}

pub fn poll<T>(future: &mut BoxFuture<'_, T>) -> Poll<T> {
    future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
}

pub fn ready<T>(mut future: BoxFuture<'_, T>) -> T {
    let Poll::Ready(value) = poll(&mut future) else {
        panic!("fixture operation unexpectedly pending");
    };
    value
}
