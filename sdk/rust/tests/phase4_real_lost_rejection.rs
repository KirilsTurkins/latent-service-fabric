//! Explicit lost-rejection and fresh-client recovery on a provisioned node.
#![cfg(feature = "transport")]
use latent_core::TenantId;
use latent_sdk::{
    management::{
        CallOptions, InvocationTarget, InvokeRequest, OutcomeKnowledge, PublicationRef,
        ResourceBudget,
    },
    network::{ClientConfig, ClientLimits, RpcClient},
    transaction::{
        self, CommandOutcome, CommandSelector, ExpectedVersion, InvokeCommandRequest,
        LookupCommandRequest, NamespaceSelector, TransactionClient,
    },
};
use std::{env, time::Duration};
use tokio::time::Instant;
fn required(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("missing live fixture field {name}"))
}
fn unhex(value: &str) -> Vec<u8> {
    assert!(!value.is_empty() && value.len() % 2 == 0);
    (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).expect("hex"))
        .collect()
}
fn selector() -> CommandSelector {
    CommandSelector {
        namespace: Some(NamespaceSelector {
            tenant: required("LSF_401_TENANT"),
            namespace: required("LSF_401_NAMESPACE"),
            incarnation: required("LSF_401_INCARNATION"),
        }),
        operation: "update".into(),
        entity: None,
        client_key: "rust-sdk-lost-rejection".into(),
        shared_recovery_scope: None,
    }
}
fn client() -> RpcClient {
    RpcClient::new(ClientConfig {
        endpoint: required("LSF_401_ENDPOINT").parse().expect("endpoint"),
        tenant: TenantId(required("LSF_401_TENANT")),
        credential: required("LSF_401_TOKEN").into(),
        limits: ClientLimits::default(),
    })
    .expect("bounded client")
}
async fn retire(client: &RpcClient) {
    assert!(client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .is_ok());
    let usage = client.usage();
    assert_eq!(
        (
            usage.active_calls,
            usage.reserved_message_bytes,
            usage.sockets,
            usage.executor_tasks
        ),
        (0, 0, 0, 0)
    );
}
#[tokio::test]
#[ignore = "requires a separate node and response-blocking fault fixture"]
async fn lost_rejection_response_reports_unknown() {
    let tenant = required("LSF_401_TENANT");
    let key = "rust-sdk-lost-rejection";
    let request = InvokeCommandRequest {
        profile: Some(transaction::current_profile()),
        invocation: Some(InvokeRequest {
            activation_id: Some(key.into()),
            target: Some(InvocationTarget {
                tenant,
                service: "examples/transaction-java-aggregate".into(),
                contract: "examples:transactional-aggregate/api@1.0.0".into(),
                function: "update".into(),
                route: Some("transaction-java-aggregate".into()),
            }),
            payload: br#"[{"delta":1,"reject":true}]"#.to_vec(),
            media_type: "application/vnd.latent.wit-values.v1+json".into(),
            budget: Some(ResourceBudget {
                cpu_fuel: 1_000_000_000,
                memory_bytes: 67_108_864,
                state_read_bytes: 4_194_304,
                state_write_bytes: 2_097_152,
                effect_count: 1,
                wall_time_limit_millis: Some(120_000),
                ..Default::default()
            }),
            ..Default::default()
        }),
        command: Some(selector()),
        input_format: "lsf-wit-values-v1".into(),
        expected_versions: vec![ExpectedVersion {
            key: b"aggregate/count".to_vec(),
            absent: None,
            version: Some(unhex(&required("LSF_401_EXPECTED_VERSION_HEX"))),
        }],
        retry_attempt: None,
    };
    let client = client();
    let failure = client
        .invoke_command(request, CallOptions::default())
        .await
        .expect_err("response must be withheld");
    assert!(failure.transport.dispatched);
    assert_eq!(failure.transport.outcome, OutcomeKnowledge::UNKNOWN);
    assert_eq!(
        failure
            .identity
            .command
            .as_ref()
            .expect("original selector")
            .client_key,
        key
    );
    assert!(failure.observed.is_none());
    retire(&client).await;
    println!("LOST_REJECTION_UNKNOWN");
}
#[tokio::test]
#[ignore = "requires the original rejection and a later state change"]
async fn recover_original_rejection_after_lost_response() {
    let tenant = required("LSF_401_TENANT");
    let client = client();
    let request = LookupCommandRequest {
        profile: Some(transaction::current_profile()),
        command: Some(selector()),
        attempt_id: None,
        authorization_publication: Some(PublicationRef {
            tenant,
            id: required("LSF_401_PUBLICATION"),
        }),
    };
    let command = client
        .lookup_command(request, CallOptions::default())
        .await
        .expect("lookup")
        .value
        .command
        .expect("original command");
    assert_eq!(command.outcome, CommandOutcome::REJECTED);
    assert!(
        command.metadata_durable
            && !command.application_state_committed
            && command.commit.is_none()
    );
    assert_eq!(command.command_id, required("LSF_401_ORIGINAL_ID"));
    assert_eq!(command.attempt_id, required("LSF_401_ORIGINAL_ATTEMPT"));
    assert_eq!(
        command.fingerprint_sha256,
        unhex(&required("LSF_401_ORIGINAL_FINGERPRINT"))
    );
    let rejection = command.business_rejection.expect("business rejection");
    assert_eq!(
        rejection.code.as_bytes(),
        unhex(&required("LSF_401_REJECTION_CODE"))
    );
    assert_eq!(
        rejection.payload,
        unhex(&required("LSF_401_REJECTION_PAYLOAD"))
    );
    retire(&client).await;
    println!("LOST_REJECTION_RECOVERED");
}

#[tokio::test]
#[ignore = "requires an original durable rejection on a separate node"]
async fn changed_input_conflicts_with_original_rejection() {
    let tenant = required("LSF_401_TENANT");
    let key = "rust-sdk-lost-rejection";
    let request = InvokeCommandRequest {
        profile: Some(transaction::current_profile()),
        invocation: Some(InvokeRequest {
            activation_id: Some(key.into()),
            target: Some(InvocationTarget {
                tenant,
                service: "examples/transaction-java-aggregate".into(),
                contract: "examples:transactional-aggregate/api@1.0.0".into(),
                function: "update".into(),
                route: Some("transaction-java-aggregate".into()),
            }),
            payload: br#"[{"delta":2,"reject":true}]"#.to_vec(),
            media_type: "application/vnd.latent.wit-values.v1+json".into(),
            budget: Some(ResourceBudget {
                cpu_fuel: 1_000_000_000,
                memory_bytes: 67_108_864,
                state_read_bytes: 4_194_304,
                state_write_bytes: 2_097_152,
                effect_count: 1,
                wall_time_limit_millis: Some(120_000),
                ..Default::default()
            }),
            ..Default::default()
        }),
        command: Some(selector()),
        input_format: "lsf-wit-values-v1".into(),
        expected_versions: vec![ExpectedVersion {
            key: b"aggregate/count".to_vec(),
            absent: None,
            version: Some(unhex(&required("LSF_401_EXPECTED_VERSION_HEX"))),
        }],
        retry_attempt: None,
    };
    let client = client();
    let failure = client
        .invoke_command(request, CallOptions::default())
        .await
        .expect_err("changed input under the retained key must conflict");
    assert!(failure.transport.dispatched);
    assert_eq!(failure.transport.grpc_status, Some(6));
    assert_eq!(failure.transport.outcome, OutcomeKnowledge::UNKNOWN);
    assert_eq!(
        failure
            .identity
            .command
            .as_ref()
            .expect("selector")
            .client_key,
        key
    );
    assert!(failure.observed.is_none());
    retire(&client).await;
    println!("CHANGED_INPUT_CONFLICT");
}
