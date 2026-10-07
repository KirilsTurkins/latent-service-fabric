//! Trusted startup constraints on the original protected recovery writer.
//! Installation supplies no state, result, dispatch or recovery permission.
use super::InstalledTransactionOperation;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityOwner, NativeReservation,
        NativeReservationRequest,
    },
    PlatformError,
};
use latent_state::{
    embedded::{EmbeddedStore, FencedStoreError, StoreError},
    protected_store::ProtectedStoreOwner,
    store_io::StoreIoKind,
    tenant::{self, TenantQuota},
};
use std::{sync::Arc, time::Instant};

const REQUEST_BYTES: u64 = 32 * 1024;
const WORK_BYTES: u64 = 256 * 1024;
const RETAINED_BYTES: u64 = REQUEST_BYTES + WORK_BYTES + 8192;

struct Input {
    quotas: Vec<TenantQuota>,
    installed: Vec<Arc<InstalledTransactionOperation>>,
}

pub(super) async fn install(
    store: &Arc<ProtectedStoreOwner>,
    native: &NativeCapacityOwner,
    quotas: &[TenantQuota],
    installed: &[Arc<InstalledTransactionOperation>],
    deadline: Instant,
) -> Result<(), PlatformError> {
    if quotas.len() > tenant::MAXIMUM_TENANTS
        || installed.len() > 128
        || (quotas.is_empty() && !installed.is_empty())
    {
        return Err(super::capacity());
    }
    for quota in quotas {
        quota.validate().map_err(|_| super::denied())?;
    }
    let reservation = native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                request_bytes: REQUEST_BYTES,
                work_bytes: WORK_BYTES,
                response_bytes: 0,
            },
            deadline,
        )
        .map_err(|_| super::capacity())?;
    // Reserve before cloning the finite declarations and actual retained
    // publication owners. Each buffer keeps the original native lease alive.
    let request = reservation
        .reserve_buffer(NativeBufferClass::Request, REQUEST_BYTES)
        .map_err(|_| super::capacity())?
        .attach(Input {
            quotas: quotas.to_vec(),
            installed: installed.to_vec(),
        });
    let work = reservation
        .reserve_buffer(NativeBufferClass::Work, WORK_BYTES)
        .map_err(|_| super::capacity())?;
    let job = store
        .with_store(StoreIoKind::RecoveryWrite, RETAINED_BYTES, move |engine| {
            let input = request.get();
            if reservation.with_live(|| ()).is_err() {
                return Ok(Err(super::unavailable()));
            }
            let prepared = prepare(engine, input)?;
            let Some(prepared) = prepared else {
                return Ok(accept(&reservation, &input.installed).map(|()| reservation));
            };
            if prepared.retained_bytes() as u64 > WORK_BYTES {
                return Err(StoreError::Capacity);
            }
            let (prepared, work) = work.attach(prepared).into_parts();
            let result = prepared.publish(engine, || accept(&reservation, &input.installed));
            // Destroy the original prepared business bytes before refunding
            // their charge. Accepted physical work retains the request/lease.
            drop(work);
            match result {
                Ok(_configuration_digest) => {}
                Err(FencedStoreError::Store(error)) => return Err(error),
                // Authorization expiry is a bounded operation refusal. It is
                // not evidence of a physical store failure and must not latch
                // quarantine on this unchanged engine.
                Err(FencedStoreError::Fence(error)) => return Ok(Err(error)),
            }
            // The original affine owner also survives physical completion
            // until startup checks current delivery. No new lease or deadline.
            Ok(Ok(reservation))
        })
        .map_err(|_| super::unavailable())?;
    let completed = job
        .await
        .map_err(|_| super::unavailable())?
        .map_err(|_| super::unavailable())??;
    accept(&completed, installed)
}

fn prepare(
    engine: &EmbeddedStore,
    input: &Input,
) -> Result<Option<tenant::PreparedTenantInstallation>, StoreError> {
    let view = engine.snapshot()?;
    if input.quotas.is_empty() {
        // The settings-bound opening walk has already refused all business
        // ownership. Recheck the immutable guard/tenant rows under this worker.
        if view.contains_prefix(
            latent_state::embedded::Family::Maintenance,
            tenant::GUARD_PREFIX,
        )? || view.contains_prefix(
            latent_state::embedded::Family::Maintenance,
            tenant::QUOTA_PREFIX,
        )? {
            return Err(StoreError::UnsupportedFormat);
        }
        return Ok(None);
    }
    tenant::prepare_install(&view, &input.quotas).map(Some)
}

fn accept(
    reservation: &NativeReservation,
    installed: &[Arc<InstalledTransactionOperation>],
) -> Result<(), PlatformError> {
    reservation
        .with_live(|| {
            for operation in installed {
                operation.publication().check_current()?;
            }
            Ok::<(), PlatformError>(())
        })
        .map_err(|_| super::unavailable())??;
    // Eligibility reads are finite but may have consumed the original cutoff.
    reservation
        .with_live(|| ())
        .map_err(|_| super::unavailable())
}

#[cfg(test)]
mod tests;
