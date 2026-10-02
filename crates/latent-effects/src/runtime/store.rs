use crate::authority::{DispatchProfile, DurableEffectAuthority, EffectTime};
use crate::dispatch::EffectRecord;
use crate::dispatch_store::{
    effect_row_key, validate_row, DispatchCatalog, DispatchCounts, DispatchEpoch,
    DispatchStoreError, DueRecord, EFFECT_PREFIX,
};
use latent_state::embedded::{EmbeddedStore, Family, StoreError};
use latent_state::protected_store::ProtectedStoreOwner;
use latent_state::store_io::StoreIoKind;

use super::DispatcherError;

pub(super) struct Candidate {
    pub due: DueRecord,
    pub authority: DurableEffectAuthority,
    pub attempt: u32,
}

pub(super) struct CandidatePage {
    pub rows: Vec<Candidate>,
    pub resume: Option<Vec<u8>>,
}

#[derive(Debug)]
pub struct RequiredProfileRow {
    pub effect: String,
    pub profile: DispatchProfile,
    pub unresolved: bool,
    pub command: String,
    pub commit: String,
    pub namespace_incarnation: u64,
}

#[derive(Debug)]
pub struct RequiredProfilePage {
    pub rows: Vec<RequiredProfileRow>,
    pub resume: Option<Vec<u8>>,
}

pub(super) async fn call<T: Send + 'static>(
    owner: &ProtectedStoreOwner,
    kind: StoreIoKind,
    bytes: u64,
    operation: impl FnOnce(&EmbeddedStore) -> Result<T, DispatchStoreError> + Send + 'static,
) -> Result<T, DispatcherError> {
    let job = owner.with_store(kind, bytes, move |store| match operation(store) {
        Err(DispatchStoreError::Storage(error)) => Err(error),
        result => Ok(result),
    })?;
    job.await??.map_err(DispatcherError::from)
}

pub(super) async fn startup(
    owner: &ProtectedStoreOwner,
    time: EffectTime,
    checkpoint: Option<(u64, u64)>,
) -> Result<DispatchEpoch, DispatcherError> {
    let has_history = call(owner, StoreIoKind::Read, 8 * 1024 * 1024, |store| {
        let view = store.snapshot()?;
        DispatchCatalog::validate_view(&view)?;
        Ok(DispatchCatalog::has_owner_history(&view)?)
    })
    .await?;
    if has_history && checkpoint.is_none() {
        return Err(DispatcherError::CheckpointRequired);
    }
    if !time.continuity_proven {
        return Err(DispatcherError::Authority(
            crate::authority::AuthorityError::ClockDiscontinuity,
        ));
    }
    let epoch = call(owner, StoreIoKind::Write, 1024 * 1024, move |store| {
        DispatchCatalog::begin_exclusive_epoch(store, time, checkpoint)
    })
    .await?;
    let mut cursor = None;
    loop {
        cursor = call(owner, StoreIoKind::Write, 8 * 1024 * 1024, move |store| {
            DispatchCatalog::recover_page(store, epoch, cursor.as_deref(), true, time)
        })
        .await?;
        if cursor.is_none() {
            return Ok(epoch);
        }
    }
}

pub(super) async fn control_startup(
    owner: &ProtectedStoreOwner,
    epoch: DispatchEpoch,
) -> Result<Option<(bool, bool)>, DispatcherError> {
    call(owner, StoreIoKind::Read, 32 * 1024, move |store| {
        Ok(crate::dispatch_store::control::ControlCatalog::startup(
            &store.snapshot()?,
            epoch.generation(),
        )?)
    })
    .await
}

pub(super) async fn candidates(
    owner: &ProtectedStoreOwner,
    time: EffectTime,
    cursor: Option<Vec<u8>>,
    rows: usize,
    bytes: usize,
) -> Result<CandidatePage, DispatcherError> {
    call(owner, StoreIoKind::Read, 8 * 1024 * 1024, move |store| {
        let view = store.snapshot()?;
        let page =
            DispatchCatalog::due_page(&view, time.unix_millis, cursor.as_deref(), rows, bytes)?;
        let mut candidates = Vec::with_capacity(page.rows.len());
        for due in page.rows {
            let key = effect_row_key(&due.effect)?;
            let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
            validate_row(&key, &bytes)?;
            let record =
                EffectRecord::decode(&bytes).map_err(crate::dispatch_store::storage_error)?;
            candidates.push(Candidate {
                due,
                authority: record
                    .authority()
                    .map_err(crate::dispatch_store::storage_error)?,
                attempt: record
                    .attempts()
                    .checked_add(1)
                    .ok_or(StoreError::Capacity)?,
            });
        }
        Ok(CandidatePage {
            rows: candidates,
            resume: page.resume,
        })
    })
    .await
}

pub(super) async fn counts(owner: &ProtectedStoreOwner) -> Result<DispatchCounts, DispatcherError> {
    call(owner, StoreIoKind::Read, 2 * 1024 * 1024, |store| {
        Ok(DispatchCatalog::counts(&store.snapshot()?)?)
    })
    .await
}

pub(super) async fn profiles(
    owner: &ProtectedStoreOwner,
    cursor: Option<Vec<u8>>,
    rows: usize,
    bytes: usize,
) -> Result<RequiredProfilePage, DispatcherError> {
    if !(1..=64).contains(&rows)
        || !(4096..=4 * 1024 * 1024).contains(&bytes)
        || cursor.as_ref().is_some_and(|cursor| cursor.len() > 4096)
    {
        return Err(DispatcherError::InvalidConfiguration);
    }
    call(owner, StoreIoKind::Read, 8 * 1024 * 1024, move |store| {
        let view = store.snapshot()?;
        let page = view.scan_after(
            Family::Outbox,
            EFFECT_PREFIX,
            cursor.as_deref(),
            rows,
            bytes,
        )?;
        let mut profiles = Vec::with_capacity(page.rows.len());
        for (key, bytes) in page.rows {
            validate_row(&key, &bytes)?;
            let record =
                EffectRecord::decode(&bytes).map_err(crate::dispatch_store::storage_error)?;
            let authority = record
                .authority()
                .map_err(crate::dispatch_store::storage_error)?;
            profiles.push(RequiredProfileRow {
                effect: authority.link().effect.clone(),
                profile: authority.profile().clone(),
                unresolved: !record.disposition().terminal(),
                command: authority.link().command.clone(),
                commit: authority.link().commit.clone(),
                namespace_incarnation: authority.scope().incarnation,
            });
        }
        Ok(RequiredProfilePage {
            rows: profiles,
            resume: page.resume,
        })
    })
    .await
}
