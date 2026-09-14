//! Pin resource ownership in addition to Wasmtime's typed linker checks.
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
    let mismatch = || incompatible("blob resource ownership does not match the host profile");
    if !function.async_() {
        return Err(mismatch());
    }
    let chunk = || {
        interface.exports(engine).find_map(|(name, item)| {
            if name != "chunk" {
                return None;
            }
            if let ComponentItem::Resource(resource) = item.ty {
                Some(resource)
            } else {
                None
            }
        })
    };
    let valid = match name {
        "read" => match function.results().next() {
            Some(Type::Result(result)) => {
                matches!(result.ok(), Some(Type::Own(actual)) if Some(actual) == chunk())
            }
            _ => false,
        },
        "chunk-bytes" => {
            matches!(function.params().next(), Some((_, Type::Borrow(actual))) if Some(actual) == chunk())
        }
        "create" | "open" | "write" | "seal" | "close" => true,
        _ => false,
    };
    if !valid {
        return Err(mismatch());
    }
    Ok(())
}
