//! Check exact async kinds and affine own/borrow identities before typed linking.
use super::incompatible;
use latent_core::PlatformError;
use wasmtime::{
    component::{
        types::{Component, ComponentFunc, ComponentInstance, ComponentItem},
        ResourceType, Type,
    },
    Engine,
};

pub(crate) const STATE: &str = "latent:state/key-value@0.2.0";
pub(crate) const INTENTS: &str = "latent:intents/staging@0.1.0";

pub(crate) fn is_async(name: &str) -> Result<bool, PlatformError> {
    match name {
        "acquire-command" | "acquire-query" | "info" | "query-info" | "describe-page" => Ok(false),
        "get" | "get-query" | "scan" | "scan-query" | "page-next" | "put" | "delete" => Ok(true),
        _ => Err(incompatible("unsupported scoped state operation")),
    }
}
pub(crate) fn command_resource(component: &Component, engine: &Engine) -> Option<ResourceType> {
    component.imports(engine).find_map(|(name, item)| {
        if name != STATE {
            return None;
        }
        match item.ty {
            ComponentItem::ComponentInstance(interface) => {
                resource(&interface, engine, "transaction")
            }
            _ => None,
        }
    })
}
fn resource(
    interface: &ComponentInstance,
    engine: &Engine,
    selected: &str,
) -> Option<ResourceType> {
    interface.exports(engine).find_map(|(name, item)| {
        if name != selected {
            return None;
        }
        match item.ty {
            ComponentItem::Resource(resource) => Some(resource),
            _ => None,
        }
    })
}
pub(crate) fn validate(
    contract: &str,
    name: &str,
    function: &ComponentFunc,
    interface: &ComponentInstance,
    engine: &Engine,
    command: Option<ResourceType>,
) -> Result<(), PlatformError> {
    let mismatch =
        || incompatible("transaction resource ownership does not match the host profile");
    let first = function.params().next().map(|(_, ty)| ty);
    let borrowed =
        |selected| matches!(first, Some(Type::Borrow(actual)) if Some(actual) == selected);
    let owned_result = |selected| match function.results().next() {
        Some(Type::Result(result)) => {
            matches!(result.ok(), Some(Type::Own(actual)) if Some(actual) == selected)
        }
        _ => false,
    };
    let valid = match contract {
        STATE => {
            let transaction = resource(interface, engine, "transaction");
            let query = resource(interface, engine, "query-view");
            let page = resource(interface, engine, "page");
            if transaction != command {
                return Err(mismatch());
            }
            match name {
                "acquire-command" => owned_result(transaction),
                "acquire-query" => owned_result(query),
                "info" | "get" | "put" | "delete" => borrowed(transaction),
                "query-info" | "get-query" => borrowed(query),
                "scan" => borrowed(transaction) && owned_result(page),
                "scan-query" => borrowed(query) && owned_result(page),
                "describe-page" | "page-next" => borrowed(page),
                _ => false,
            }
        }
        INTENTS => {
            name == "stage"
                && function.async_()
                && command.is_some()
                && resource(interface, engine, "transaction") == command
                && borrowed(command)
        }
        _ => false,
    };
    if !valid {
        return Err(mismatch());
    }
    Ok(())
}
