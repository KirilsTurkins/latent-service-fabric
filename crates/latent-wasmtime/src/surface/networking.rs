use super::incompatible;
use latent_core::PlatformError;
use wasmtime::{
    component::{
        types::{ComponentFunc, ComponentInstance, ComponentItem},
        Type,
    },
    Engine,
};

/// This finite linear-memory profile uses borrowed WasmStr/WasmList cursors.
/// Reject transcoding and GC canonical options before any Store exists so host
/// parameter lifting cannot allocate an unbounded string before prepayment.
pub(crate) fn validate_encoding(bytes: &[u8]) -> Result<(), PlatformError> {
    use wasmparser::{CanonicalFunction, CanonicalOption, Parser, Payload};
    let invalid = || incompatible("outbound streams require UTF-8 linear canonical memory");
    for payload in Parser::new(0).parse_all(bytes) {
        if let Payload::ComponentCanonicalSection(section) = payload.map_err(|_| invalid())? {
            for function in section {
                let options = match function.map_err(|_| invalid())? {
                    CanonicalFunction::Lift { options, .. }
                    | CanonicalFunction::Lower { options, .. } => options,
                    _ => continue,
                };
                if options.iter().any(|option| {
                    matches!(
                        option,
                        CanonicalOption::UTF16
                            | CanonicalOption::CompactUTF16
                            | CanonicalOption::Gc
                    )
                }) {
                    return Err(invalid());
                }
            }
        }
    }
    Ok(())
}

pub(crate) fn validate(
    name: &str,
    function: &ComponentFunc,
    interface: &ComponentInstance,
    engine: &Engine,
) -> Result<(), PlatformError> {
    let mismatch = || {
        incompatible("outbound stream ownership or async signature does not match the host profile")
    };
    if function.async_() != (name != "inspect") {
        return Err(mismatch());
    }
    let handle = |ty: Option<Type>, resource: &str, owned: bool| {
        let Some((_, item)) = interface
            .exports(engine)
            .find(|(name, _)| *name == resource)
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
    if name == "inspect" {
        return if handle(first, "connection", false) {
            Ok(())
        } else {
            Err(mismatch())
        };
    }
    let Some(Type::Result(result)) = function.results().next() else {
        return Err(mismatch());
    };
    let valid = match name {
        "connect" => handle(result.ok(), "connection", true),
        "read" => {
            let chunk = match result.ok() {
                Some(Type::Option(value)) => Some(value.ty()),
                _ => None,
            };
            handle(first, "connection", false) && handle(chunk, "chunk", true)
        }
        "write" | "ready" | "shutdown" => handle(first, "connection", false),
        "chunk-bytes" => handle(first, "chunk", false),
        "close" => handle(first, "connection", true),
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(mismatch())
    }
}
