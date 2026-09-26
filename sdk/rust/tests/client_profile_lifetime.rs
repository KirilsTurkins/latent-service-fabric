use latent_sdk::management::*;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};

#[derive(Default)]
struct State {
    writes: usize,
    waiters: usize,
    cancels: usize,
    pages: usize,
    receipt: Option<CapabilityPolicyOperation>,
    policy: Option<Policy>,
}

#[derive(Default)]
struct FixtureClient(Arc<Mutex<State>>);

struct LocalOwner(Arc<Mutex<State>>);

impl Drop for LocalOwner {
    fn drop(&mut self) {
        self.0.lock().unwrap().waiters -= 1;
    }
}

fn response<Response>(value: Response, identity: RequestIdentity) -> ClientResponse<Response> {
    ClientResponse {
        value,
        metadata: ResponseMetadata {
            identity,
            outcome: OutcomeKnowledge::OBSERVED,
            ..Default::default()
        },
    }
}

fn ready<Response: Send + 'static>(value: Response) -> ClientFuture<'static, Response> {
    Box::pin(async move { Ok(response(value, RequestIdentity::default())) })
}

impl ClientProfile for FixtureClient {
    fn invoke(
        &self,
        request: InvokeRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, InvokeResponse> {
        ready(InvokeResponse {
            activation_id: request.activation_id.unwrap(),
            success: Some(Success {
                payload: request.payload,
                ..Default::default()
            }),
            ..Default::default()
        })
    }

    fn cancel(
        &self,
        _request: CancelRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, CancelResponse> {
        self.0.lock().unwrap().cancels += 1;
        ready(CancelResponse {
            disposition: CancelDisposition::ACCEPTED,
            ..Default::default()
        })
    }

    fn get_activation(
        &self,
        request: GetActivationRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, ActivationStatus> {
        ready(ActivationStatus {
            activation_id: request.activation_id,
            phase: "running".into(),
            ..Default::default()
        })
    }

    fn get_policy(
        &self,
        _request: GetPolicyRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, GetPolicyResponse> {
        ready(GetPolicyResponse {
            policy: self.0.lock().unwrap().policy.clone(),
        })
    }

    fn list_policies(
        &self,
        _request: ListPoliciesRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, ListPoliciesResponse> {
        self.0.lock().unwrap().pages += 1;
        ready(ListPoliciesResponse {
            page: Some(PageResponse {
                next_page_token: Some("opaque-next-page".into()),
            }),
            ..Default::default()
        })
    }

    fn list_capabilities(
        &self,
        request: ListCapabilitiesRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, ListCapabilitiesResponse> {
        ready(ListCapabilitiesResponse {
            revision: Some(CapabilityInspectionRevision {
                deployment_id: request.deployment_id,
                ..Default::default()
            }),
            ..Default::default()
        })
    }

    fn apply_policy(
        &self,
        request: ApplyPolicyRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, ApplyPolicyResponse> {
        Box::pin(async move {
            let identity = RequestIdentity {
                operation_id: Some(request.operation_id.clone()),
                ..Default::default()
            };
            if options.timeout_millis == Some(0) {
                return Err(ClientFailure {
                    category: FailureCategory::DEADLINE,
                    identity,
                    outcome: OutcomeKnowledge::NOT_DISPATCHED,
                    ..Default::default()
                });
            }
            assert_eq!(request.expected_generation, Some(0));
            assert!(!request.operation_id.is_empty());
            {
                let mut state = self.0.lock().unwrap();
                if let Some(receipt) = &state.receipt {
                    assert_eq!(receipt.operation_id, request.operation_id);
                    return Ok(response(
                        ApplyPolicyResponse {
                            receipt: Some(receipt.clone()),
                            ..Default::default()
                        },
                        identity,
                    ));
                }
                let policy = request.policy.unwrap();
                state.receipt = Some(CapabilityPolicyOperation {
                    operation_id: request.operation_id,
                    tenant: "tenant-a".into(),
                    id: policy.id.clone(),
                    generation: u64::MAX,
                    record_kind: policy.record_kind,
                    ..Default::default()
                });
                state.policy = Some(policy);
                state.writes += 1;
                state.waiters += 1;
            }
            let local_owner = LocalOwner(self.0.clone());
            let result = std::future::pending().await;
            drop(local_owner);
            result
        })
    }

    fn get_policy_operation(
        &self,
        request: GetPolicyOperationRequest,
        _options: CallOptions,
    ) -> ClientFuture<'_, GetPolicyOperationResponse> {
        let receipt = self
            .0
            .lock()
            .unwrap()
            .receipt
            .clone()
            .filter(|receipt| receipt.operation_id == request.operation_id);
        Box::pin(async move {
            let outcome = if receipt.is_some() {
                OutcomeKnowledge::OBSERVED
            } else {
                OutcomeKnowledge::UNKNOWN
            };
            Ok(ClientResponse {
                value: GetPolicyOperationResponse { receipt },
                metadata: ResponseMetadata {
                    identity: RequestIdentity {
                        operation_id: Some(request.operation_id),
                        ..Default::default()
                    },
                    outcome,
                    ..Default::default()
                },
            })
        })
    }
}

fn completed<Response>(mut future: ClientFuture<'_, Response>) -> ClientResponse<Response> {
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(Ok(value)) => value,
        _ => panic!("fixture must complete in one bounded poll"),
    }
}

#[test]
fn dropped_waiter_preserves_receipt_and_all_eight_operations() {
    let client = FixtureClient::default();
    let profile: &dyn ClientProfile = &client;
    let request = ApplyPolicyRequest {
        operation_id: "operation-a".into(),
        expected_generation: Some(0),
        policy: Some(Policy {
            id: "policy-a".into(),
            record_kind: CapabilityPolicyRecordKind::POLICY,
            ..Default::default()
        }),
    };
    let mut pending = profile.apply_policy(request.clone(), CallOptions::default());
    assert_eq!(client.0.lock().unwrap().writes, 0);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(client.0.lock().unwrap().writes, 1);
    assert_eq!(client.0.lock().unwrap().waiters, 1);
    drop(pending);
    assert_eq!(client.0.lock().unwrap().waiters, 0);
    assert_eq!(client.0.lock().unwrap().cancels, 0);
    let recovered = completed(profile.get_policy_operation(
        GetPolicyOperationRequest {
            operation_id: "operation-a".into(),
        },
        CallOptions::default(),
    ));
    assert_eq!(recovered.value.receipt.unwrap().generation, u64::MAX);
    assert!(recovered.metadata.audit_ack.is_none());
    let unknown = completed(profile.get_policy_operation(
        GetPolicyOperationRequest {
            operation_id: "not-retained".into(),
        },
        CallOptions::default(),
    ));
    assert!(unknown.value.receipt.is_none());
    assert_eq!(unknown.metadata.outcome, OutcomeKnowledge::UNKNOWN);
    completed(profile.apply_policy(request.clone(), CallOptions::default()));
    assert_eq!(client.0.lock().unwrap().writes, 1);
    let mut expired = profile.apply_policy(
        request,
        CallOptions {
            timeout_millis: Some(0),
        },
    );
    let Poll::Ready(Err(failure)) = expired
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    else {
        panic!("zero timeout must fail locally")
    };
    assert!(!failure.dispatched);
    assert_eq!(
        failure.identity.operation_id.as_deref(),
        Some("operation-a")
    );
    assert_eq!(failure.outcome, OutcomeKnowledge::NOT_DISPATCHED);
    verify_read_operations(&client);
}

fn verify_read_operations(client: &FixtureClient) {
    let profile: &dyn ClientProfile = client;
    let invoked = completed(profile.invoke(
        InvokeRequest {
            activation_id: Some("activation-a".into()),
            payload: vec![1, 2],
            ..Default::default()
        },
        CallOptions::default(),
    ));
    assert_eq!(invoked.value.success.unwrap().payload, vec![1, 2]);
    assert_eq!(
        completed(profile.cancel(
            CancelRequest {
                activation_id: "activation-a".into(),
                ..Default::default()
            },
            CallOptions::default()
        ))
        .value
        .disposition,
        CancelDisposition::ACCEPTED
    );
    assert_eq!(
        completed(profile.get_activation(
            GetActivationRequest {
                activation_id: "activation-a".into()
            },
            CallOptions::default()
        ))
        .value
        .phase,
        "running"
    );
    assert_eq!(
        completed(profile.get_policy(
            GetPolicyRequest {
                id: "policy-a".into(),
                record_kind: CapabilityPolicyRecordKind::POLICY
            },
            CallOptions::default()
        ))
        .value
        .policy
        .unwrap()
        .id,
        "policy-a"
    );
    assert!(completed(profile.list_policies(
        ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind::POLICY,
            page: Some(PageRequest {
                page_size: 1,
                ..Default::default()
            })
        },
        CallOptions::default()
    ))
    .value
    .page
    .unwrap()
    .next_page_token
    .is_some());
    assert_eq!(client.0.lock().unwrap().pages, 1);
    assert_eq!(
        completed(profile.list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: "deployment-a".into(),
                ..Default::default()
            },
            CallOptions::default()
        ))
        .value
        .revision
        .unwrap()
        .deployment_id,
        "deployment-a"
    );
}
