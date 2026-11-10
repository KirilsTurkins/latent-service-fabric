//! Explicit live-node probe; the caller provisions the signed guest and node.
#![cfg(feature = "transport")]

use latent_core::TenantId;
use latent_sdk::{
    management::{CallOptions, PublicationRef},
    network::{ClientConfig, ClientLimits, RpcClient},
    transaction::{
        self, CommandOutcome, CommandSelector, LookupCommandRequest, NamespaceSelector,
        TransactionClient,
    },
};
use std::{env, time::Duration};
use tokio::time::Instant;

fn required(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("required live-node fixture field missing: {name}"))
}

#[tokio::test]
#[ignore = "requires an explicitly provisioned separate signed node and committed fixture"]
async fn committed_command_lookup_uses_real_shared_client_and_retires() {
    let tenant = required("LSF_401_TENANT");
    let key = required("LSF_401_COMMAND_KEY");
    let client = RpcClient::new(ClientConfig {
        endpoint: required("LSF_401_ENDPOINT")
            .parse()
            .expect("loopback node endpoint"),
        tenant: TenantId(tenant.clone()),
        credential: required("LSF_401_TOKEN").into(),
        limits: ClientLimits::default(),
    })
    .expect("bounded client configuration");
    let request = LookupCommandRequest {
        profile: Some(transaction::current_profile()),
        command: Some(CommandSelector {
            namespace: Some(NamespaceSelector {
                tenant: tenant.clone(),
                namespace: required("LSF_401_NAMESPACE"),
                incarnation: required("LSF_401_INCARNATION"),
            }),
            operation: required("LSF_401_OPERATION"),
            entity: None,
            client_key: key.clone(),
            shared_recovery_scope: None,
        }),
        attempt_id: None,
        authorization_publication: Some(PublicationRef {
            tenant,
            id: required("LSF_401_PUBLICATION"),
        }),
    };
    let first = client
        .lookup_command(request.clone(), CallOptions::default())
        .await;
    let second = client.lookup_command(request, CallOptions::default()).await;
    let shutdown = client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await;
    assert!(shutdown.is_ok(), "client shutdown did not retire");
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
    let first = first
        .expect("first authorized lookup")
        .value
        .command
        .expect("original command");
    let second = second
        .expect("second authorized lookup")
        .value
        .command
        .expect("original command");
    assert_eq!(first.command_id, required("LSF_401_COMMAND_ID"));
    assert_eq!(first.attempt_id, required("LSF_401_ATTEMPT_ID"));
    assert_eq!(first.outcome, CommandOutcome::COMMITTED);
    assert!(first.metadata_durable && first.application_state_committed && first.commit.is_some());
    assert_eq!(first.key.as_ref().expect("command key").client_key, key);
    assert_eq!(first.command_id, second.command_id);
    assert_eq!(first.attempt_id, second.attempt_id);
    assert_eq!(first.key, second.key);
    assert_eq!(first.fingerprint_sha256, second.fingerprint_sha256);
    assert_eq!(first.outcome, second.outcome);
    assert_eq!(first.source, second.source);
    assert_eq!(first.commit, second.commit);
}
