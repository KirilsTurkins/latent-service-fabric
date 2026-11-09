//! Explicit lost-response and fresh-client recovery on a provisioned node.
#![cfg(feature = "transport")]
use latent_core::TenantId;
use latent_sdk::{
    management::{CallOptions, InvocationTarget, InvokeRequest, ResourceBudget},
    network::{ClientConfig, ClientLimits, RpcClient},
    transaction::{
        self, CommandOutcome, CommandSelector, ExpectedVersion, InvokeCommandRequest,
        NamespaceSelector, TransactionClient,
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
        client_key: "rust-sdk-stale-edit".into(),
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
#[ignore = "requires a real node with a commit newer than the original edit view"]
async fn stale_edit_does_not_refresh_expected_version() {
    let tenant = required("LSF_401_TENANT");
    let original_version = unhex(&required("LSF_401_EXPECTED_VERSION_HEX"));
    let key = "rust-sdk-stale-edit";
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
            payload: br#"[{"delta":1,"reject":false}]"#.to_vec(),
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
            version: Some(original_version.clone()),
        }],
        retry_attempt: None,
    };
    let client = client();
    let response = client
        .invoke_command(request, CallOptions::default())
        .await
        .expect("stale edit response");
    assert_eq!(
        response.metadata.identity.expected_versions[0]
            .version
            .as_ref(),
        Some(&original_version)
    );
    let command = response.value.command.expect("durable stale outcome");
    assert_eq!(command.outcome, CommandOutcome::ABORTED);
    assert!(command.metadata_durable && !command.application_state_committed);
    assert!(command.commit.is_none() && command.proven_abort.is_some());
    retire(&client).await;
    println!("STALE_EDIT_ABORTED");
}
