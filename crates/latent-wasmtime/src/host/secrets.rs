//! Synchronous WIT contract, cooperative asynchronous host implementation.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::secrets::{SecretError, SecretInvoker, SECRETS_CAPABILITY};
use latent_component_bindings::host::phase3::latent::secrets::reader as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::component::{ComponentType, Linker, Lower};
use zeroize::Zeroize;

// The generated public DTO derives Debug. Keep this private lowering equivalent
// free of Debug/serialization, and wipe its transient host plaintext on Drop.
#[derive(ComponentType, Lower)]
#[component(record)]
struct SecretValue {
    bytes: Vec<u8>,
    #[component(name = "media-type")]
    media_type: String,
    version: Option<String>,
    #[component(name = "expires-at-unix-millis")]
    expires_at_unix_millis: Option<u64>,
}
impl Drop for SecretValue {
    fn drop(&mut self) {
        self.bytes.zeroize();
    }
}

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn SecretInvoker>,
) -> wasmtime::Result<()> {
    linker.instance(SECRETS_CAPABILITY)?.func_wrap_async(
        "read",
        move |mut store, (reference,): (String,)| {
            let invoker = invoker.clone();
            Box::new(async move {
                let started = Instant::now();
                checkpoint(&mut store)?;
                let invocation = store
                    .data()
                    .capabilities
                    .session
                    .as_ref()
                    .ok_or(SecretError::PermissionDenied)
                    .and_then(|session| invoker.read(session, reference));
                synchronize(&mut store)?;
                let completion = match invocation {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                checkpoint(&mut store)?;
                let result = match completion {
                    Ok(disclosure) => {
                        let mut value = None;
                        let mut directory_error = None;
                        let owner = disclosure.disclose(&mut |view| {
                            // disclose performs its original final authority
                            // checks before this trusted callback. Reserve the
                            // directory before cloning any plaintext or DTO.
                            if let Err(error) =
                                store.data_mut().capabilities.prepare_secret_lowering()
                            {
                                directory_error = Some(error);
                                return;
                            }
                            value = Some(SecretValue {
                                bytes: view.bytes.to_vec(),
                                media_type: view.media_type.to_owned(),
                                version: Some(view.version.to_owned()),
                                expires_at_unix_millis: view.expires_at_unix_millis,
                            });
                        });
                        if let Some(error) = directory_error {
                            // Preserve the exact original budget error. No DTO
                            // was cloned on refusal; retain this explicit drop
                            // ordering if the trusted builder changes later.
                            drop(value);
                            drop(owner);
                            return Err(error);
                        }
                        match owner {
                            Ok(owner) => {
                                store.data_mut().capabilities.retain_secret_lowering(owner);
                                value.ok_or(SecretError::Unavailable).map_err(convert_error)
                            }
                            Err(error) => Err(convert_error(error)),
                        }
                    }
                    Err(error) => Err(convert_error(error)),
                };
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result,))
            })
        },
    )?;
    Ok(())
}
fn convert_error(error: SecretError) -> wit::SecretError {
    match error {
        SecretError::NotFound => wit::SecretError::NotFound,
        SecretError::PermissionDenied => wit::SecretError::PermissionDenied,
        SecretError::Expired => wit::SecretError::Expired,
        SecretError::Unavailable => wit::SecretError::Unavailable,
    }
}
