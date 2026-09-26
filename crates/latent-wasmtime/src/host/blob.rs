//! Numeric file handles and owned range chunks belong to one fresh guest Store.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::blob::{
    BlobError as Error, BlobInvoker, BlobReference, BLOB_CAPABILITY,
};
use latent_component_bindings::host::blob::latent::blob0_2_0::blob as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::{
    component::{Linker, Resource, ResourceType},
    AsContextMut,
};
mod open;
mod operations;
pub(super) mod table;
use table::{Kind, Value};

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn BlobInvoker>,
) -> wasmtime::Result<()> {
    let mut host = linker.instance(BLOB_CAPABILITY)?;
    host.resource(
        "chunk",
        ResourceType::host::<wit::Chunk>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .blobs
                .remove(u64::from(rep), Kind::Chunk)
                .map_err(trap)
        },
    )?;
    open::create(&mut host, invoker.clone())?;
    open::open(&mut host, invoker)?;
    operations::write(&mut host)?;
    operations::read(&mut host)?;
    operations::seal(&mut host)?;
    operations::close(&mut host)?;
    operations::chunk_bytes(&mut host)?;
    Ok(())
}
fn trap(_: Error) -> wasmtime::Error {
    wasmtime::Error::msg("invalid blob resource")
}
fn convert(error: Error) -> wit::BlobError {
    match error {
        Error::NotFound => wit::BlobError::NotFound,
        Error::PermissionDenied => wit::BlobError::PermissionDenied,
        Error::InvalidRange => wit::BlobError::InvalidRange,
        Error::InvalidState => wit::BlobError::InvalidState,
        Error::ChecksumMismatch => wit::BlobError::ChecksumMismatch,
        Error::BudgetExhausted => wit::BlobError::BudgetExhausted,
        Error::Unavailable => wit::BlobError::Unavailable,
        Error::Uncertain => wit::BlobError::Uncertain,
        Error::DeadlineExceeded => wit::BlobError::DeadlineExceeded,
        Error::Cancelled => wit::BlobError::Cancelled,
    }
}
