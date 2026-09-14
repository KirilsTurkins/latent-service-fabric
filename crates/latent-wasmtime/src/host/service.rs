//! Canonical async service calls use the normal node lifecycle through an affine
//! broker call. The Store is borrowed only for bounded synchronous checkpoints.
use super::{capabilities::host_error, HostState};
use latent_capabilities::broker::{
    LocalServiceCompletion, LocalServiceInvoker, LocalServiceRequest, SERVICE_INVOCATION_CAPABILITY,
};
use latent_component_bindings::host::phase3::latent::service::invoke as wit;
use latent_core::{
    ContractId, FunctionId, IdempotencyKey, PlatformError, PlatformErrorCode, ServiceId, TenantId,
};
use latent_routing::InvocationTarget;
use std::{sync::Arc, time::Instant};
use wasmtime::{component::Linker, AsContextMut, StoreContextMut};
mod outcome;

const MAX_INPUT_BYTES: usize = 64 * 1024;
const MAX_OUTPUT_BYTES: usize = 64 * 1024;
const MAX_METADATA_PAIRS: usize = 64;

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn LocalServiceInvoker>,
) -> wasmtime::Result<()> {
    linker
        .instance(SERVICE_INVOCATION_CAPABILITY)?
        .func_wrap_concurrent(
            "call",
            move |access,
                  (target, payload, media_type, options): (
                wit::Target,
                Vec<u8>,
                String,
                wit::CallOptions,
            )| {
                let invoker = invoker.clone();
                Box::pin(async move {
                    let started = Instant::now();
                    let invocation = access.with(|mut access| {
                        let mut store = access.as_context_mut();
                        checkpoint(&mut store)?;
                        let invocation = start(
                            store.data(),
                            invoker.as_ref(),
                            target,
                            payload,
                            media_type,
                            options,
                        );
                        // Failed setup also settles any provisional reservation.
                        synchronize(&mut store)?;
                        Ok::<_, wasmtime::Error>(invocation)
                    })?;
                    let completion = match invocation {
                        Ok(invocation) => invocation.await,
                        Err(failure) => Err(failure),
                    };
                    access.with(|mut access| {
                        let mut store = access.as_context_mut();
                        checkpoint(&mut store)?;
                        let result = match completion {
                            Ok(LocalServiceCompletion {
                                outcome: result,
                                call,
                                child,
                            }) => {
                                let result = outcome::convert(result);
                                // Parent output capacity was reserved before child
                                // admission and remains owned through Store drop.
                                store.data_mut().capabilities.retain_lowering(call);
                                drop(child);
                                result
                            }
                            Err(failure) => outcome::rejected(&failure),
                        };
                        synchronize(&mut store)?;
                        store.data_mut().record_host_call(started);
                        Ok((result,))
                    })
                })
            },
        )?;
    Ok(())
}

fn start(
    state: &HostState,
    invoker: &dyn LocalServiceInvoker,
    target: wit::Target,
    payload: Vec<u8>,
    media_type: String,
    options: wit::CallOptions,
) -> Result<latent_capabilities::broker::LocalServiceInvocation, PlatformError> {
    if payload.capacity() > MAX_INPUT_BYTES || options.metadata.len() > MAX_METADATA_PAIRS {
        return Err(exhausted());
    }
    let mut bytes = payload.capacity().checked_add(512).ok_or_else(exhausted)?;
    for value in [
        &target.service,
        &target.contract,
        &target.function,
        &media_type,
    ]
    .into_iter()
    .chain(target.tenant.iter())
    .chain(target.route.iter())
    .chain(options.idempotency_key.iter())
    {
        if value.len() > 512 {
            return Err(exhausted());
        }
        bytes = bytes.checked_add(value.capacity()).ok_or_else(exhausted)?;
    }
    bytes = bytes
        .checked_add(
            options
                .metadata
                .capacity()
                .checked_mul(96)
                .ok_or_else(exhausted)?,
        )
        .ok_or_else(exhausted)?;
    for (key, value) in &options.metadata {
        if key.len() > 512 || value.len() > 512 {
            return Err(exhausted());
        }
        bytes = bytes
            .checked_add(key.capacity())
            .and_then(|bytes| bytes.checked_add(value.capacity()))
            .ok_or_else(exhausted)?;
    }
    if bytes > MAX_INPUT_BYTES {
        return Err(exhausted());
    }
    let target = InvocationTarget {
        tenant: target
            .tenant
            .map(TenantId)
            .map_or_else(|| state.capabilities.local_tenant(), Ok)?,
        service: ServiceId(target.service),
        contract: ContractId(target.contract),
        function: FunctionId(target.function),
        route: target.route,
    };
    let call = state
        .capabilities
        .local_call(&target, &[], bytes, MAX_OUTPUT_BYTES)?;
    let mut metadata = latent_core::Metadata::new();
    for (key, value) in options.metadata {
        if metadata.insert(key, value).is_some() {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "duplicate local service metadata",
            ));
        }
    }
    invoker.start(
        call,
        LocalServiceRequest {
            target,
            deadline_unix_millis: options.deadline_unix_millis,
            priority: options.priority,
            idempotency_key: options.idempotency_key.map(IdempotencyKey),
            metadata,
            input: payload,
            input_media_type: media_type,
        },
    )
}
fn checkpoint(store: &mut StoreContextMut<'_, HostState>) -> wasmtime::Result<()> {
    let fuel = store.get_fuel()?;
    let state = store.data_mut();
    state.limiter.confirm_memory_growth();
    state
        .accounting
        .observe_runtime(fuel, state.limiter.peak_memory_bytes())
        .map_err(host_error)
}
fn synchronize(store: &mut StoreContextMut<'_, HostState>) -> wasmtime::Result<()> {
    let state = store.data();
    let remaining = state
        .accounting
        .budget()
        .remaining_at(state.clock.monotonic_now())
        .cpu_fuel;
    store.set_fuel(remaining)?;
    store.data_mut().accounting.reset_fuel_watermark(remaining);
    Ok(())
}
pub(super) fn denied() -> PlatformError {
    failure(
        PlatformErrorCode::PermissionDenied,
        "local service provider unavailable",
    )
}
fn exhausted() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "local service input limit exceeded",
    )
}
fn failure(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: vec![],
    }
}
