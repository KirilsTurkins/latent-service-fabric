//! Explicit rejection and recovery probes for a separately provisioned node.
#![cfg(feature = "transport")]
use latent_core::TenantId;
use latent_sdk::{
    management::{CallOptions, InvocationTarget, InvokeRequest, PublicationRef, ResourceBudget},
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
fn decode(value: &str) -> Vec<u8> {
    assert!(value.len() % 2 == 0);
    (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).expect("hex field"))
        .collect()
}
fn encode(value: &[u8]) -> String {
    value.iter().map(|b| format!("{b:02x}")).collect()
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
        client_key: "rust-sdk-rejected-command".into(),
        shared_recovery_scope: None,
    }
}
fn client() -> RpcClient {
    RpcClient::new(ClientConfig {
        endpoint: required("LSF_401_ENDPOINT").parse().expect("node endpoint"),
        tenant: TenantId(required("LSF_401_TENANT")),
        credential: required("LSF_401_TOKEN").into(),
        limits: ClientLimits::default(),
    })
    .expect("bounded client")
}
#[tokio::test]
#[ignore = "requires a separate signed node and current key version"]
async fn rejection_is_durable_without_business_writes() {
    let client = client();
    let tenant = required("LSF_401_TENANT");
    let request = InvokeCommandRequest {
        profile: Some(transaction::current_profile()),
        command: Some(selector()),
        input_format: "lsf-wit-values-v1".into(),
        retry_attempt: None,
        expected_versions: vec![ExpectedVersion {
            key: b"aggregate/count".to_vec(),
            absent: None,
            version: Some(decode(&required("LSF_401_EXPECTED_VERSION_HEX"))),
        }],
        invocation: Some(InvokeRequest {
            activation_id: Some("rust-sdk-rejected-command".into()),
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
    };
    let result = client.invoke_command(request, CallOptions::default()).await;
    assert!(client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .is_ok());
    let result = result.expect("original rejection response").value;
    let command = result.command.expect("durable rejection command");
    let rejection = result
        .invocation
        .expect("original invocation")
        .declared_error
        .expect("business rejection");
    assert_eq!(command.outcome, CommandOutcome::REJECTED);
    assert!(
        command.metadata_durable
            && !command.application_state_committed
            && command.commit.is_none()
    );
    assert!(!rejection.code.is_empty() && !rejection.payload.is_empty());
    println!(
        "REJECTION {} {} {} {} {}",
        command.command_id,
        command.attempt_id,
        encode(&command.fingerprint_sha256),
        encode(rejection.code.as_bytes()),
        encode(&rejection.payload)
    );
}
#[tokio::test]
#[ignore = "requires the original rejection and a later committed state change"]
async fn rejection_recovers_after_state_change() {
    let client = client();
    let request = LookupCommandRequest {
        profile: Some(transaction::current_profile()),
        command: Some(selector()),
        attempt_id: None,
        authorization_publication: Some(PublicationRef {
            tenant: required("LSF_401_TENANT"),
            id: required("LSF_401_PUBLICATION"),
        }),
    };
    let result = client.lookup_command(request, CallOptions::default()).await;
    assert!(client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .is_ok());
    let command = result
        .expect("original rejection lookup")
        .value
        .command
        .expect("rejection record");
    assert_eq!(command.command_id, required("LSF_401_REJECTION_ID"));
    assert_eq!(command.attempt_id, required("LSF_401_REJECTION_ATTEMPT"));
    assert_eq!(
        command.fingerprint_sha256,
        decode(&required("LSF_401_REJECTION_FINGERPRINT"))
    );
    assert_eq!(command.outcome, CommandOutcome::REJECTED);
    assert!(
        command.metadata_durable
            && !command.application_state_committed
            && command.commit.is_none()
    );
    let rejection = command
        .business_rejection
        .expect("original retained rejection");
    assert_eq!(
        rejection.code.as_bytes(),
        decode(&required("LSF_401_REJECTION_CODE"))
    );
    assert_eq!(
        rejection.payload,
        decode(&required("LSF_401_REJECTION_PAYLOAD"))
    );
    println!("REJECTION_RECOVERED");
}
