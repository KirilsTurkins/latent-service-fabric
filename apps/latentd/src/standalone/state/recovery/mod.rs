//! Authenticated native offline actions on the current protected owners.
mod assets;
mod authority;
mod catalog;
mod codecs;
mod execution;
mod migration;
mod operation;
mod original_resume;
mod profile;
mod request;
mod restore;
mod restored;
mod scope;
mod selection;

pub use execution::NativeRecoveryReport;
pub(in crate::standalone) use operation::{recover, RecoveryOwners};
pub use request::NativeRecoveryRequest;

fn denied() -> latent_core::PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::PermissionDenied,
        "native-recovery-refused",
    )
}
fn capacity() -> latent_core::PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::ResourceExhausted,
        "native-recovery-capacity",
    )
}

#[cfg(test)]
async fn join_test_workers(
    store: &latent_state::protected_store::ProtectedStoreOwner,
    cutoff: std::time::Instant,
) {
    let mut joined = 0;
    loop {
        joined += store.reap_retired_threads().unwrap();
        if store.pending_thread_joins().unwrap() == 0 {
            break;
        }
        assert!(
            std::time::Instant::now() < cutoff,
            "native thread join cutoff"
        );
        tokio::time::sleep(std::time::Duration::from_millis(1)).await;
    }
    assert!(joined > 0);
}
