#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#![allow(
    clippy::duplicate_mod,
    reason = "reuse maintained provider fixtures with distinct generated component types"
)]

#[path = "phase3_resource/blob.rs"]
mod blob;
#[path = "phase3_resource/child.rs"]
mod child;
#[path = "phase3_resource/events.rs"]
mod events;
#[path = "phase3_resource/http.rs"]
mod http;
#[path = "phase3_resource/observation.rs"]
mod observation;
#[path = "phase3_resource/secrets.rs"]
mod secrets;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

#[test]
fn phase3_resource_small_provider_ownership_checkpoint() {
    let mut observations = Vec::new();
    let provider_runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    provider_runtime.block_on(async {
        tokio::time::timeout(std::time::Duration::from_mins(1), async {
            http::measure(&mut observations).await;
            blob::measure(&mut observations).await;
            secrets::measure(&mut observations).await;
            events::measure(&mut observations).await;
        })
        .await
        .expect("finite direct-provider resource checkpoint");
    });
    drop(provider_runtime);
    let child_runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap();
    child_runtime.block_on(async {
        tokio::time::timeout(
            std::time::Duration::from_secs(30),
            child::measure(&mut observations),
        )
        .await
        .expect("finite two-worker child-call resource checkpoint");
    });
    drop(child_runtime);
    observation::publish(&observations);
}
