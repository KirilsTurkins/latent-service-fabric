use super::{BlobError, CapabilityCallCost, Inner, PoolAdmission, BLOB_CAPABILITY};
use latent_capabilities::broker::{pools::PoolCall, AuditProviderOutcome};
use latent_policy::capability::ResourceTarget;
pub(super) struct Completion<T> {
    pub value: Result<T, BlobError>,
    pub call: PoolCall,
}
pub(super) async fn dispatch(
    inner: &Inner,
    admission: PoolAdmission,
    operation: &str,
    cost: CapabilityCallCost,
) -> Result<PoolCall, BlobError> {
    Ok(admission
        .wait()
        .await?
        .dispatch(
            BLOB_CAPABILITY,
            operation,
            ResourceTarget::Blob {
                namespace: inner.store.namespace(),
            },
            &[],
            cost,
        )
        .await?)
}
pub(super) async fn run<T: Send + 'static>(
    inner: &Inner,
    call: PoolCall,
    operation: &'static str,
    work: impl FnOnce(&mut PoolCall) -> Result<T, BlobError> + Send + 'static,
) -> Result<Completion<T>, BlobError> {
    // Hashing, bounded JSON and descriptor bookkeeping have a prepaid workspace.
    let scratch = call.io().reserve_scratch(16384, 2048)?;
    let waiter = call.io().job_waiter();
    let job = inner.pools.spawn_blocking(call, move |mut call| {
        let _scratch = scratch;
        let value = work(&mut call);
        let outcome = match &value {
            Ok(_) if operation == "seal" => AuditProviderOutcome::BlobSealed,
            Ok(_) => AuditProviderOutcome::HostCompleted,
            Err(BlobError::Uncertain) => AuditProviderOutcome::Unknown,
            Err(_) => AuditProviderOutcome::Rejected,
        };
        let _ = call.io_mut().record_provider_outcome(outcome);
        Completion { value, call }
    })?;
    let mut completion = waiter.wait(job.wait()).await??;
    completion.call.io_mut().finish_audit().await;
    Ok(completion)
}
