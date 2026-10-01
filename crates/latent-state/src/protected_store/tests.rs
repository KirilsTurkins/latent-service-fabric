use std::fs::{self, OpenOptions};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::{mpsc, Arc};
use std::time::Instant;

use latent_core::test_support::coordination::{
    with_watchdog, PollProbe, Rendezvous, Stage, WATCHDOG,
};
use latent_core::test_support::{block_on, TestClock};
use latent_core::ActivationClock;

use super::*;
use crate::embedded::{Family, RowKey, RowMutation};

mod initialization;
mod lifecycle;
mod recovery;
mod reserved;
mod validation;

fn wait<T>(future: impl Future<Output = T>) -> T {
    block_on(with_watchdog(WATCHDOG, future))
}

fn fixture() -> (tempfile::TempDir, ProtectedStoreConfig) {
    let directory =
        std::env::var_os("LATENT_STATE_TEST_ROOT").map_or_else(std::env::temp_dir, PathBuf::from);
    let root = tempfile::tempdir_in(directory).unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let mut config = ProtectedStoreConfig::bounded_linux(root.path().to_path_buf());
    config.create_if_missing = true;
    (root, config)
}

fn start(config: ProtectedStoreConfig) -> ProtectedStoreOwner {
    wait(ProtectedStoreOwner::start_validated(config, 0, |key, value| {
        if matches!(key.family, Family::State | Family::Command | Family::Outbox) && !value.is_empty() {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }).unwrap()).unwrap_or_else(|error| {
        panic!("protected engine readiness failed: {error:?}; use LATENT_STATE_TEST_ROOT on the qualified Linux ext4 local volume")
    })
}

fn key(family: Family, name: &str) -> RowKey {
    RowKey {
        family,
        key: name.as_bytes().to_vec(),
    }
}

fn batch(value: &[u8]) -> AtomicBatch {
    AtomicBatch {
        expectations: vec![],
        mutations: [Family::State, Family::Command, Family::Outbox]
            .into_iter()
            .map(|family| RowMutation {
                key: key(family, "command"),
                value: Some(value.to_vec()),
            })
            .collect(),
    }
}

fn finish(owner: &ProtectedStoreOwner) -> crate::store_io::StoreIoShutdown {
    wait(
        owner
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    )
}

fn read(
    owner: &ProtectedStoreOwner,
    view: ProtectedStoreView,
) -> (ProtectedStoreView, Vec<Option<Vec<u8>>>) {
    let (view, values) = wait(
        owner
            .with_view(view, 4096, |native| {
                [Family::State, Family::Command, Family::Outbox]
                    .into_iter()
                    .map(|family| native.get(&key(family, "command")))
                    .collect()
            })
            .unwrap(),
    )
    .unwrap();
    (view, values.unwrap())
}

fn failed_start(config: ProtectedStoreConfig) -> ProtectedStoreError {
    let mut startup = Box::pin(ProtectedStoreOwner::start(config).unwrap());
    let error = wait(startup.as_mut()).err().unwrap();
    let shutdown = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
    error
}
