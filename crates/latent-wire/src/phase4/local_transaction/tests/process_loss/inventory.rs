use super::*;
use latent_effects::{dispatch::EffectRecord, dispatch_store::DispatchCatalog};
use latent_state::{embedded::StoreError, store_io::StoreIoKind};
use serde::{Deserialize, Serialize};

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Inventory {
    pub commands: Vec<Vec<u8>>,
    pub attempts: Vec<Vec<u8>>,
    pub results: Vec<Vec<u8>>,
    pub pending_results: Vec<Vec<u8>>,
    pub state: Vec<(Vec<u8>, Vec<u8>)>,
    pub effects: Vec<String>,
    pub checkpoint: Option<(u64, u64)>,
}

#[derive(Serialize, Deserialize)]
pub(super) struct Probe {
    pub pid: u32,
    pub kind: String,
    pub root: PathBuf,
    pub executions: u64,
    pub stores_created: u64,
    pub live_stores: u64,
    pub inventory: Inventory,
}

pub(super) async fn read(store: &Arc<ProtectedStoreOwner>) -> Inventory {
    store
        .with_store(StoreIoKind::Read, 128 * 1024, |store| {
            let view = store.snapshot()?;
            let rows = |family| view.scan(family, b"", 4, 32 * 1024);
            let values = |family| {
                rows(family).map(|rows| rows.into_iter().map(|(_, bytes)| bytes).collect())
            };
            let mut results = Vec::new();
            let mut pending_results = Vec::new();
            for (key, bytes) in rows(Family::Result)? {
                latent_commit::atomic::validate_linked_row(&view, &key, &bytes)?;
                let (format, _) = latent_commit::atomic::durable_row_format(&key, &bytes)
                    .map_err(|_| StoreError::Corrupt)?;
                if format == "latent.result-pending.v1" {
                    pending_results.push(bytes);
                } else {
                    results.push(bytes);
                }
            }
            let mut effects = rows(Family::Outbox)?
                .into_iter()
                .map(|(_, bytes)| {
                    EffectRecord::decode(&bytes)
                        .and_then(|record| {
                            record
                                .authority()
                                .map(|authority| authority.link().effect.clone())
                        })
                        .map_err(|_| StoreError::Corrupt)
                })
                .collect::<Result<Vec<_>, _>>()?;
            effects.sort();
            Ok(Inventory {
                commands: values(Family::Command)?,
                attempts: values(Family::Attempt)?,
                results,
                pending_results,
                state: rows(Family::State)?
                    .into_iter()
                    .map(|(key, bytes)| (key.key, bytes))
                    .collect(),
                effects,
                checkpoint: DispatchCatalog::checkpoint(&view)?,
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}
