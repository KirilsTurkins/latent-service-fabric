//! A prepaid pending result slot is not a terminal application result.
use latent_commit::atomic::{durable_row_format, validate_linked_row};
use latent_state::{
    embedded::{Family, StoreError},
    protected_store::ProtectedStoreOwner,
    store_io::StoreIoKind,
};
use std::sync::Arc;

pub(super) async fn results(store: &Arc<ProtectedStoreOwner>) -> (usize, usize) {
    store
        .with_store(StoreIoKind::Read, 128 * 1024, |store| {
            let view = store.snapshot()?;
            let mut terminal = 0;
            let mut pending = 0;
            for (key, bytes) in view.scan(Family::Result, b"", 256, 128 * 1024)? {
                validate_linked_row(&view, &key, &bytes)?;
                let (format, _) =
                    durable_row_format(&key, &bytes).map_err(|_| StoreError::Corrupt)?;
                if format == "latent.result-pending.v1" {
                    pending += 1;
                } else {
                    terminal += 1;
                }
            }
            Ok((terminal, pending))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}
