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

/// A selected phase provider already supplies the original nominal resource
/// host types. This exception never supplies any legacy callable operation.
pub(crate) fn phase_type_owner(
    component: &wasmtime::component::types::Component,
    name: &str,
    interface: &ComponentInstance,
    engine: &Engine,
    selected: bool,
    installed: bool,
) -> bool {
    use latent_capabilities::broker::streaming_http::{
        PHASE_TIMING_CAPABILITY, STREAMING_HTTP_CAPABILITY,
    };
    selected
        && installed
        && name == STREAMING_HTTP_CAPABILITY
        && component.imports(engine).any(|(name, item)| {
            name == PHASE_TIMING_CAPABILITY
                && matches!(item.ty, ComponentItem::ComponentInstance(_))
        })
        && interface
            .exports(engine)
            .all(|(_, item)| matches!(item.ty, ComponentItem::Type(_) | ComponentItem::Resource(_)))
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

/// The upload helper has no independent provider authority. It must use the
/// exact nominal upload resource of an operational original streaming import.
pub(crate) fn validate_upload_window_aliases(
    component: &wasmtime::component::types::Component,
    engine: &Engine,
) -> Result<bool, PlatformError> {
    use latent_capabilities::broker::streaming_http::{
        STREAMING_HTTP_CAPABILITY, UPLOAD_WINDOW_INTERFACE,
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
    let Some(helper) = instance(UPLOAD_WINDOW_INTERFACE) else {
        return Ok(false);
    };
    let original = instance(STREAMING_HTTP_CAPABILITY)
        .ok_or_else(|| incompatible("upload window requires the original streaming import"))?;
    if !original
        .exports(engine)
        .any(|(name, item)| name == "open" && matches!(item.ty, ComponentItem::ComponentFunc(_)))
    {
        return Err(incompatible(
            "upload window requires an operational streaming import",
        ));
    }
    let resource = |interface: &ComponentInstance| {
        interface.exports(engine).find_map(|(name, item)| {
            if name != "upload" {
                return None;
            }
            match item.ty {
                ComponentItem::Resource(resource) => Some(resource),
                _ => None,
            }
        })
    };
    let expected = resource(&original)
        .ok_or_else(|| incompatible("upload window original resource is missing"))?;
    if resource(&helper) != Some(expected) {
        return Err(incompatible(
            "upload window resource differs from its original owner",
        ));
    }
    for required in ["prepare", "write"] {
        if !helper.exports(engine).any(|(name, item)| {
            name == required && matches!(item.ty, ComponentItem::ComponentFunc(_))
        }) {
            return Err(incompatible("upload window operation is missing"));
        }
    }
    Ok(true)
}

pub(crate) fn validate_upload_window(
    name: &str,
    function: &ComponentFunc,
    interface: &ComponentInstance,
    engine: &Engine,
) -> Result<(), PlatformError> {
    let mismatch = || incompatible("upload window signature does not match its original owner");
    if !function.async_() {
        return Err(mismatch());
    }
    let expected = interface.exports(engine).find_map(|(name, item)| {
        if name != "upload" {
            return None;
        }
        match item.ty {
            ComponentItem::Resource(resource) => Some(resource),
            _ => None,
        }
    });
    let mut parameters = function.params();
    let first = parameters.next().map(|(_, ty)| ty);
    if !matches!((first, expected), (Some(Type::Borrow(actual)), Some(expected)) if actual == expected)
    {
        return Err(mismatch());
    }
    let second = parameters.next().map(|(_, ty)| ty);
    let third = parameters.next().map(|(_, ty)| ty);
    if parameters.next().is_some() {
        return Err(mismatch());
    }
    let Some(Type::Result(result)) = function.results().next() else {
        return Err(mismatch());
    };
    let valid = match name {
        "prepare" => {
            if !matches!(second, Some(Type::U32)) || third.is_some() {
                false
            } else if let Some(Type::Record(record)) = result.ok() {
                let mut fields = record.fields();
                matches!(fields.next(), Some(field) if field.name == "generation" && matches!(field.ty, Type::U64))
                    && matches!(fields.next(), Some(field) if field.name == "maximum-bytes" && matches!(field.ty, Type::U32))
                    && fields.next().is_none()
                    && result.err().is_some()
            } else {
                false
            }
        }
        "write" => {
            matches!(second, Some(Type::U64))
                && matches!(third, Some(Type::List(list)) if matches!(list.ty(), Type::U8))
                && result.ok().is_none()
                && result.err().is_some()
        }
        _ => false,
    };
    if !valid || function.results().len() != 1 {
        return Err(mismatch());
    }
    Ok(())
}
