#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/invocation", "examples/guest_service"],
    world: "tests:caller/service@1.0.0",
    with: { "latent:service/invoke@0.1.0": latent_guest::bindings::service },
});

struct Capsule;
impl exports::tests::caller::api::Guest for Capsule {
    async fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle).await
    }
}
export!(Capsule);

use latent_guest::service::{self, CallOptions, InvocationOutcome, PlatformErrorCode, Target};
async fn probe(which: u32, _text: String, _handle: u64) -> u64 {
    let function = match which {
        0 => "answer",
        1 => "fail",
        _ => "spin",
    };
    let outcome = service::call(
        Target {
            tenant: None,
            service: "callee".into(),
            contract: "tests:local/api@1.0.0".into(),
            function: function.into(),
            route: Some("callee".into()),
        },
        b"[]".to_vec(),
        "application/vnd.latent.wit-values.v1+json".into(),
        CallOptions {
            deadline_unix_millis: None,
            priority: 0,
            idempotency_key: None,
            metadata: vec![],
        },
    )
    .await;
    match outcome {
        InvocationOutcome::Success(result) => {
            assert_eq!(result.payload, b"[42]");
            42
        }
        InvocationOutcome::DeclaredError(error) => {
            assert!(!error.payload.is_empty());
            10
        }
        InvocationOutcome::PlatformFailure(error) => match error.code {
            PlatformErrorCode::PermissionDenied => 11,
            PlatformErrorCode::Cancelled => 12,
            PlatformErrorCode::DeadlineExceeded => 13,
            PlatformErrorCode::ResourceExhausted => 14,
            other => panic!("unexpected platform failure: {other:?}"),
        },
    }
}
