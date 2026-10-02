//! One maintained matrix for actual authored guests and the native node owners.
//! Real maintained build observations and independent publisher/builder test
//! keys pass enforced catalog admission. Installed Standalone distribution,
//! production clock sampling and ordinary RPC transport remain separate gates.
#![cfg(target_os = "linux")]

#[path = "../../latent-node/tests/activation_lifecycle/model.rs"]
#[allow(dead_code)]
mod admission_fixture;
#[path = "transaction_guests/artifact.rs"]
mod artifact;
#[path = "transaction_guests/fixture.rs"]
mod fixture;
#[path = "guest_sdk/runtime.rs"]
mod guest_runtime;
#[path = "transaction_guests/http.rs"]
mod http;
#[path = "transaction_guests/policy.rs"]
mod policy;
#[path = "transaction_guests/signing.rs"]
mod signing;

use latent_activation::ActivationOutcome;
use latent_node::transaction_runtime::{CommandCompletionDisposition, TransactionCompletionResult};
use latent_state::embedded::Family;
use serde_json::{json, Value};

fn output(result: &TransactionCompletionResult) -> Value {
    let bytes = match result {
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
            result,
            cleanup_failure,
            ..
        }) => {
            assert!(
                cleanup_failure.is_none(),
                "durability cannot hide cleanup failure"
            );
            result
                .value()
                .expect("full retained result")
                .bytes
                .as_slice()
        }
        TransactionCompletionResult::Query {
            outcome: ActivationOutcome::Succeeded(value),
            ..
        } => value.output.as_slice(),
        _ => panic!("expected actual durable command or fresh query result"),
    };
    serde_json::from_slice(bytes).expect("canonical WIT result JSON")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires actual observed packages from prepare_transaction_guest_packages.py"]
async fn authored_command_query_scan_and_rejection_use_actual_native_owners() {
    let fixture = fixture::Fixture::new().await;
    let committed = fixture
        .invoke(
            "update",
            "command-one",
            json!([{"delta":7,"reject":false}]),
            None,
        )
        .await;
    let response = output(&committed.result);
    eprintln!("actual aggregate result: {response}");
    assert_eq!(response[0]["ok"]["count"], "7");
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 1);
    let version = response[0]["ok"]["version"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| u8::try_from(item.as_u64().unwrap()).unwrap())
        .collect::<Vec<_>>();
    drop(committed);

    let queried = fixture
        .invoke("query", "query-one", json!([]), Some(version))
        .await;
    assert_eq!(output(&queried.result)[0]["ok"]["count"], "7");
    drop(queried);
    let scanned = fixture
        .invoke(
            "scan",
            "scan-one",
            json!([[97, 103, 103, 114, 101, 103, 97, 116, 101], 1, {"none":null}]),
            None,
        )
        .await;
    assert_eq!(output(&scanned.result)[0]["ok"]["count"], 1);
    drop(scanned);

    let rejection = fixture
        .invoke(
            "update",
            "command-rejection",
            json!([{"delta":9,"reject":true}]),
            None,
        )
        .await;
    assert!(matches!(&rejection.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {result,..})
        if result.outcome() == latent_commit::atomic::Outcome::Rejected));
    drop(rejection);
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 1);
    assert_eq!(fixture.rows(Family::Command).await, 2);
    let fresh = fixture
        .invoke("query", "query-after-rejection", json!([]), None)
        .await;
    assert_eq!(output(&fresh.result)[0]["ok"]["count"], "7");
    drop(fresh);
    fixture.idle().await;
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires actual observed packages from prepare_transaction_guest_packages.py"]
async fn authored_response_retains_read_authority_and_finite_frame_owner() {
    let fixture = fixture::Fixture::new().await;
    let completion = fixture
        .invoke(
            "update",
            "response-owner",
            json!([{"delta":1,"reject":false}]),
            None,
        )
        .await;
    assert!(completion.authority.reserved_response_bytes() >= 8 * 1024 * 1024 + 16 * 1024);
    let mut released = false;
    completion
        .authority
        .with_current(&mut || released = true)
        .unwrap();
    assert!(released);
    fixture.revoke();
    assert!(completion
        .authority
        .with_current(&mut || panic!("revoked data released"))
        .is_err());
    drop(completion);
    fixture.idle().await;
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires actual forbidden-HTTP authored variant"]
async fn authored_immediate_http_returns_typed_denial_without_starting_the_real_provider() {
    let fixture = fixture::Fixture::variant("forbidden-http").await;
    // Preparation accepts the supported exact HTTP shape without creating a
    // Store. This call must reach the imported send in the real guest instead.
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 0);
    fixture.assert_no_http_start();
    let rejected = fixture
        .invoke(
            "update",
            "forbidden-immediate-http",
            json!([{"delta":9,"reject":false}]),
            None,
        )
        .await;
    assert!(matches!(&rejected.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {result,..})
        if result.outcome() == latent_commit::atomic::Outcome::Rejected));
    // Every maintained controlled variant returns this declared rejection only
    // after checking exact HTTP PermissionDenied; all other HTTP results trap.
    assert_eq!(output(&rejected.result), json!([{"err":"rejected"}]));
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 1);
    fixture.assert_no_http_start();
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    drop(rejected);
    fixture.idle().await;

    let fresh = fixture
        .invoke("query", "fresh-after-http-denial", json!([]), None)
        .await;
    assert_eq!(output(&fresh.result)[0]["ok"]["count"], "0");
    drop(fresh);
    fixture.assert_no_http_start();
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    fixture.idle().await;
    fixture.shutdown().await;
}
