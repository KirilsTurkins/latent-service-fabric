//! `Resource<T>` in Wasmtime's typed linker accepts own and borrow alike. The
//! selected WIT profile additionally fixes ownership at every handle position.
use super::incompatible;
use latent_core::PlatformError;
use wasmtime::{
    component::{
        types::{ComponentFunc, ComponentInstance, ComponentItem},
        Type,
    },
    Engine,
};

pub(crate) fn validate(
    name: &str,
    function: &ComponentFunc,
    interface: &ComponentInstance,
    engine: &Engine,
) -> Result<(), PlatformError> {
    let mismatch =
        || incompatible("streaming HTTP resource ownership does not match the host profile");
    if !function.async_() {
        return Err(mismatch());
    }
    let handle = |ty: Option<Type>, resource_name: &str, owned: bool| {
        let Some((_, item)) = interface
            .exports(engine)
            .find(|(name, _)| *name == resource_name)
        else {
            return false;
        };
        let ComponentItem::Resource(expected) = item.ty else {
            return false;
        };
        match ty {
            Some(Type::Own(actual)) if owned => actual == expected,
            Some(Type::Borrow(actual)) if !owned => actual == expected,
            _ => false,
        }
    };
    let first = function.params().next().map(|(_, ty)| ty);
    let ok = match function.results().next() {
        Some(Type::Result(result)) => result.ok(),
        _ => return Err(mismatch()),
    };
    let valid = match name {
        "open" => handle(ok, "upload", true),
        "write" => handle(first, "upload", false),
        "finish" => {
            let body = match ok {
                Some(Type::Record(record)) => record
                    .fields()
                    .find(|field| field.name == "body")
                    .map(|field| field.ty),
                _ => None,
            };
            handle(first, "upload", true) && handle(body, "body", true)
        }
        "read" => {
            let chunk = match ok {
                Some(Type::Option(option)) => Some(option.ty()),
                _ => None,
            };
            handle(first, "body", false) && handle(chunk, "chunk", true)
        }
        "chunk-bytes" => handle(first, "chunk", false),
        "trailers" => handle(first, "body", false),
        "abort-upload" => handle(first, "upload", true),
        "abort-body" => handle(first, "body", true),
        _ => false,
    };
    if !valid {
        return Err(mismatch());
    }
    Ok(())
}

/// The extension carries the same affine owners, never lookalike resources
/// with new component identities. When both versions are imported, aliases
/// must refer to exactly the same original resource types.
pub(crate) fn validate_phase_aliases(
    component: &wasmtime::component::types::Component,
    engine: &Engine,
) -> Result<(), PlatformError> {
    use latent_capabilities::broker::streaming_http::{
        PHASE_TIMING_CAPABILITY, STREAMING_HTTP_CAPABILITY,
    };
    let instance = |selected| {
        component.imports(engine).find_map(|(name, item)| {
            if name != selected {
                return None;
            }
            match item.ty {
                ComponentItem::ComponentInstance(interface) => Some(interface),
                _ => None,
            }
        })
    };
    let Some(phases) = instance(PHASE_TIMING_CAPABILITY) else {
        return Ok(());
    };
    let Some(original) = instance(STREAMING_HTTP_CAPABILITY) else {
        // The complete new interface supplies its own unchanged continuations.
        // Exact semantic WIT validation still binds aliases to the old owners.
        return Ok(());
    };
    let resource = |interface: &ComponentInstance, selected| {
        interface.exports(engine).find_map(|(name, item)| {
            if name != selected {
                return None;
            }
            match item.ty {
                ComponentItem::Resource(resource) => Some(resource),
                _ => None,
            }
        })
    };
    for name in ["upload", "body", "chunk"] {
        let expected = resource(&original, name)
            .ok_or_else(|| incompatible("HTTP phase timing resource dependency is missing"))?;
        if resource(&phases, name) != Some(expected) {
            return Err(incompatible(
                "HTTP phase timing resource alias differs from its original owner",
            ));
        }
    }
    Ok(())
}
