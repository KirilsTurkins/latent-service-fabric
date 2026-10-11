//! A real owned child exits without Drop; reopened history grants no boot trust.
mod child;
mod inventory;
mod owner;

use super::*;
use latent_effects::{
    authority::{AuthorityError, EffectAuthorityOwner, EffectTime},
    runtime::{DispatcherConfig, DispatcherError, DispatcherOwner, EffectTimeSource},
};
use latent_state::protected_store::{ProtectedStoreConfig, ProtectedStoreOwner};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};

const CASE: &str = concat!(
    "phase4::local_transaction::tests::process_loss::",
    "actual_guest_process_loss_keeps_pending_and_terminal_history_and_requires_boot_review"
);
const CHILD_KIND: &str = "LSF_387_OWNED_PROCESS_LOSS_KIND";
const CHILD_PROBE: &str = "LSF_387_OWNED_PROCESS_LOSS_PROBE";
const LOST_PROCESS_EXIT: i32 = 77;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest and owned real children"]
async fn actual_guest_process_loss_keeps_pending_and_terminal_history_and_requires_boot_review() {
    if let Some(kind) = std::env::var_os(CHILD_KIND) {
        child::run(kind.to_str().unwrap()).await;
        unreachable!("the owned child exits without running destructors");
    }
    let base =
        std::env::var_os("LATENT_STATE_TEST_ROOT").map_or_else(std::env::temp_dir, PathBuf::from);
    let root = tempfile::tempdir_in(base).unwrap().keep();
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
    eprintln!("actual-guest process-loss evidence-root={}", root.display());
    // The three actual child schedules share one absolute setup envelope. It
    // cannot refresh the guest's original ten-second invocation deadline.
    let expires_at = Instant::now() + Duration::from_secs(600);
    for kind in ["pending", "committed", "rejected"] {
        let directory = root.join(kind);
        fs::create_dir(&directory).unwrap();
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
        let probe = owner::run(&directory, kind, expires_at).await;
        assert_eq!(probe.kind, kind);
        assert_eq!(probe.executions, 1);
        assert_eq!(probe.stores_created, 1);
        assert_eq!(probe.live_stores, u64::from(kind == "pending"));
        assert_eq!(probe.root.parent().unwrap(), directory);
        reopen(&probe).await;
    }
}

async fn reopen(probe: &inventory::Probe) {
    let mut config = ProtectedStoreConfig::bounded_linux(probe.root.join("state"));
    config.create_if_missing = false;
    let store = Arc::new(fixture::start_store(config).unwrap().await.unwrap());
    let native =
        latent_core::native_capacity::NativeCapacityOwner::new(Default::default()).unwrap();
    store.bind_native_capacity(&native).unwrap();
    let recovered = inventory::read(&store).await;
    assert_eq!(recovered, probe.inventory);
    assert_eq!(recovered.commands.len(), 1);
    assert_eq!(recovered.attempts.len(), 1);
    assert_eq!(
        recovered.pending_results.len(),
        usize::from(probe.kind == "pending")
    );
    // A checkpoint read from the crash-recovered engine is descriptive. It
    // alone cannot establish an admitted external checkpoint or boot continuity.
    assert!(recovered.checkpoint.is_some());
    for millis in [1000, u64::MAX] {
        let time: Arc<dyn EffectTimeSource> = Arc::new(move || EffectTime {
            unix_millis: millis,
            continuity_proven: false,
        });
        let result = DispatcherOwner::start(
            DispatcherConfig::default(),
            Arc::clone(&store),
            EffectAuthorityOwner::new(128, 16, 100).unwrap(),
            Vec::new(),
            time,
            recovered.checkpoint,
        )
        .await;
        assert!(matches!(
            result,
            Err(DispatcherError::Authority(
                AuthorityError::ClockDiscontinuity
            ))
        ));
        assert_eq!(inventory::read(&store).await, recovered);
    }
    // No dispatcher command owner or transaction manager can be installed on
    // this unqualified boot. Neither a Pending record nor a large wall-clock
    // jump grants another guest, a new state commit or another effect identity.
    let deadline = Instant::now() + Duration::from_secs(10);
    let report = store
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(
        report.clean && report.snapshot.physically_retired(),
        "{report:?}"
    );
    store.reap_retired_threads().unwrap();
    eprintln!(
        "actual-guest process-loss kind={} pid={} executions={} stores-created={} command-rows={} attempt-rows={} state-rows={} result-rows={} effect-ids={:?} boot-review-required=true",
        probe.kind, probe.pid, probe.executions, probe.stores_created,
        recovered.commands.len(), recovered.attempts.len(), recovered.state.len(),
        recovered.results.len(), recovered.effects
    );
}
