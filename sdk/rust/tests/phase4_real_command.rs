//! Explicit live command probe; caller provisions a separate signed node.
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
#[tokio::test]
#[ignore = "requires an explicitly provisioned separate signed node and current key version"]
async fn command_commits_through_real_client_and_retires() {
    let tenant = required("LSF_401_TENANT");
    let hex = required("LSF_401_EXPECTED_VERSION_HEX");
    assert!(hex.len() % 2 == 0 && !hex.is_empty());
    let version = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).expect("version hex"))
        .collect();
    let client = RpcClient::new(ClientConfig {
        endpoint: required("LSF_401_ENDPOINT").parse().expect("node endpoint"),
        tenant: TenantId(tenant.clone()),
        credential: required("LSF_401_TOKEN").into(),
        limits: ClientLimits::default(),
    })
    .expect("bounded client");
    let request = InvokeCommandRequest {
        profile: Some(transaction::current_profile()),
        invocation: Some(InvokeRequest {
            activation_id: Some("rust-sdk-direct-command".into()),
            target: Some(InvocationTarget {
                tenant: tenant.clone(),
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
        command: Some(CommandSelector {
            namespace: Some(NamespaceSelector {
                tenant,
                namespace: required("LSF_401_NAMESPACE"),
                incarnation: required("LSF_401_INCARNATION"),
            }),
            operation: "update".into(),
            entity: None,
            client_key: "rust-sdk-direct-command".into(),
            shared_recovery_scope: None,
        }),
        input_format: "lsf-wit-values-v1".into(),
        expected_versions: vec![ExpectedVersion {
            key: b"aggregate/count".to_vec(),
            absent: None,
            version: Some(version),
        }],
        retry_attempt: None,
    };
    let outcome = client.invoke_command(request, CallOptions::default()).await;
    let retired = client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await;
    assert!(retired.is_ok());
    let command = outcome
        .expect("original command invocation")
        .value
        .command
        .expect("durable command result");
    assert_eq!(command.outcome, CommandOutcome::COMMITTED);
    assert!(command.metadata_durable && command.application_state_committed);
    let commit = command.commit.expect("original commit receipt");
    assert_eq!(commit.effect_ids.len(), 1);
    println!(
        "RESULT {} {} {}",
        command.command_id, command.attempt_id, commit.effect_ids[0]
    );
}
