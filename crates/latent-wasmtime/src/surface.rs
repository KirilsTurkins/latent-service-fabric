//! Validated dynamic export indexes and Component Model signatures.

use std::collections::{BTreeMap, BTreeSet};

use latent_artifacts::{CapsuleArtifact, FunctionDescriptor, ValueType};
use latent_core::{PlatformError, PlatformErrorCode};
use wasmtime::component::types::{ComponentFunc, ComponentItem};
use wasmtime::component::{Component, ComponentExportIndex, Type};
use wasmtime::Engine;

use crate::config::WasmtimeConfig;
use crate::containment::platform_error;
use crate::values::validate_signature;

pub(crate) mod blob;
pub(crate) mod streaming;

pub const CONTEXT_IMPORT: &str = "latent:context/context@0.1.0";
pub const LOG_IMPORT: &str = "latent:log/log@0.1.0";
pub const MONOTONIC_CLOCK_IMPORT: &str = "latent:clock/monotonic@0.1.0";
pub const WALL_CLOCK_IMPORT: &str = "latent:clock/wall@0.1.0";

pub(crate) struct Function {
    pub index: ComponentExportIndex,
    pub params: Vec<Type>,
    pub results: Vec<Type>,
}

pub(crate) struct Surface {
    functions: Vec<((String, String), Function)>,
    pub imports: BTreeSet<String>,
    pub retained_bytes: usize,
}

impl Surface {
    pub(crate) fn function(&self, contract: &str, function: &str) -> Option<&Function> {
        lookup_function(&self.functions, contract, function)
    }
}

fn lookup_function<'a, T>(
    functions: &'a [((String, String), T)],
    contract: &str,
    function: &str,
) -> Option<&'a T> {
    let index = functions
        .binary_search_by(|((candidate_contract, candidate_function), _)| {
            candidate_contract
                .as_str()
                .cmp(contract)
                .then_with(|| candidate_function.as_str().cmp(function))
        })
        .ok()?;
    Some(&functions[index].1)
}

#[derive(Clone, Copy, Default)]
pub(crate) struct Providers {
    pub local_services: bool,
    pub http: bool,
    pub streaming_http: bool,
    pub blobs: bool,
    pub secrets: bool,
    pub events: bool,
    pub random: bool,
}
impl Providers {
    fn supports(self, name: &str) -> bool {
        (self.events && name == latent_capabilities::broker::events::EVENTS_CAPABILITY)
            || (self.random && name == latent_capabilities::broker::random::RANDOM_CAPABILITY)
            || (self.secrets && name == latent_capabilities::broker::secrets::SECRETS_CAPABILITY)
            || (self.blobs && name == latent_capabilities::broker::blob::BLOB_CAPABILITY)
            || (self.local_services
                && name == latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY)
            || (self.http && name == latent_capabilities::broker::http::HTTP_CAPABILITY)
            || (self.streaming_http
                && name == latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY)
    }
}
pub(crate) fn validate_with_providers(
    component: &Component,
    engine: &Engine,
    artifact: &CapsuleArtifact,
    config: &WasmtimeConfig,
    providers: Providers,
) -> Result<Surface, PlatformError> {
    let component_type = component.component_type();
    let mut remaining = config.value_codec_limits.max_type_nodes;
    let mut retained_bytes = 0;
    retain(1024, &mut retained_bytes, config)?;
    let imports = validate_imports(
        &component_type,
        engine,
        artifact,
        config,
        &mut remaining,
        &mut retained_bytes,
        providers,
    )?;

    let declared_exports = artifact
        .manifest
        .exports
        .iter()
        .map(|export| export.contract.0.as_str())
        .collect::<BTreeSet<_>>();
    if declared_exports.is_empty() || declared_exports.len() != artifact.manifest.exports.len() {
        return Err(incompatible(
            "manifest must declare distinct exported interfaces",
        ));
    }
    let mut actual_exports = BTreeSet::new();
    let mut functions = BTreeMap::new();
    for (contract, item) in component_type.exports(engine) {
        take_name(contract, config, &mut remaining)?;
        if !declared_exports.contains(contract) {
            return Err(incompatible("manifest exports disagree with the component"));
        }
        let ComponentItem::ComponentInstance(interface) = item.ty else {
            return Err(incompatible(
                "Phase 1 contracts must be exported interfaces",
            ));
        };
        let (_, interface_index) = component
            .get_export(None, contract)
            .ok_or_else(|| incompatible("component interface index is unavailable"))?;
        let mut actual_functions = BTreeMap::new();
        for (name, item) in interface.exports(engine) {
            take_name(name, config, &mut remaining)?;
            match item.ty {
                ComponentItem::ComponentFunc(function) => {
                    let entry_bytes = retained_function_bytes(&function, contract, name)?;
                    retain(entry_bytes, &mut retained_bytes, config)?;
                    let (params, results) = signature(
                        &function,
                        (providers.local_services
                            || providers.http
                            || providers.streaming_http
                            || providers.blobs)
                            && function.async_(),
                        config,
                        &mut remaining,
                    )?;
                    let (_, index) = component
                        .get_export(Some(&interface_index), name)
                        .ok_or_else(|| incompatible("component function index is unavailable"))?;
                    actual_functions.insert(
                        name.to_owned(),
                        (
                            function,
                            Function {
                                index,
                                params,
                                results,
                            },
                        ),
                    );
                }
                ComponentItem::Type(ty) => {
                    check_types(&[ty], config, &mut remaining)?;
                }
                _ => return Err(incompatible("unsupported item in exported interface")),
            }
        }
        if actual_functions.is_empty() {
            return Err(incompatible(
                "exported contract contains no supported function",
            ));
        }
        register_functions(contract, artifact, actual_functions, &mut functions)?;
        actual_exports.insert(contract);
    }
    if actual_exports != declared_exports
        || artifact
            .contracts
            .iter()
            .any(|descriptor| !declared_exports.contains(descriptor.id.0.as_str()))
    {
        return Err(incompatible(
            "manifest or contract metadata disagrees with exported interfaces",
        ));
    }
    Ok(Surface {
        // Keep cold duplicate/descriptor validation and its conservative charge;
        // retain the same sorted keys for borrowed allocation-free invocation.
        functions: functions.into_iter().collect(),
        imports,
        retained_bytes,
    })
}

type ActualFunctions = BTreeMap<String, (ComponentFunc, Function)>;

#[cfg(test)]
mod tests;

fn validate_imports(
    component_type: &wasmtime::component::types::Component,
    engine: &Engine,
    artifact: &CapsuleArtifact,
    config: &WasmtimeConfig,
    remaining: &mut usize,
    retained_bytes: &mut usize,
    providers: Providers,
) -> Result<BTreeSet<String>, PlatformError> {
    let mut imports = BTreeSet::new();
    for (name, item) in component_type.imports(engine) {
        take_name(name, config, remaining)?;
        let specification = latent_core::PHASE3_HOST_ABI_CURRENT
            .interface(name)
            .ok_or_else(|| incompatible("component imports an unsupported host capability"))?;
        if specification.binding == latent_core::HostInterfaceBinding::Provider
            && !providers.supports(name)
        {
            // Recognition is data-only. Providers require an installed trusted port;
            // a label or a package manifest cannot install I/O.
            return Err(incompatible(
                "required host capability provider is unavailable",
            ));
        }
        let ComponentItem::ComponentInstance(interface) = item.ty else {
            return Err(incompatible(
                "host capabilities must be imported interfaces",
            ));
        };
        let mut resources = Vec::new();
        for (resource_name, item) in interface.exports(engine) {
            if let ComponentItem::Resource(resource) = item.ty {
                if !specification.resource_types().contains(&resource_name)
                    || resources.len() >= 3
                    || resources.contains(&resource)
                {
                    return Err(incompatible("unsupported host resource identity"));
                }
                resources.push(resource);
            }
        }
        for (name, item) in interface.exports(engine) {
            take_name(name, config, remaining)?;
            match item.ty {
                ComponentItem::ComponentFunc(function) => {
                    signature_with_resources(
                        &function,
                        specification.asynchronous,
                        config,
                        remaining,
                        &resources,
                    )?;
                    if !specification.resource_types().is_empty() {
                        match specification.interface {
                            latent_capabilities::broker::blob::BLOB_CAPABILITY => blob::validate(name, &function, &interface, engine)?,
                            latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY => streaming::validate(name, &function, &interface, engine)?,
                            _ => return Err(incompatible("unsupported host resource interface")),
                        }
                    }
                }
                ComponentItem::Type(ty) => {
                    check_host_types(&[ty], config, remaining, &resources)?;
                }
                ComponentItem::Resource(resource) if resources.contains(&resource) => {}
                _ => {
                    return Err(incompatible(
                        "unsupported item in host capability interface",
                    ))
                }
            }
        }
        retain(256 + name.len(), retained_bytes, config)?;
        imports.insert(name.to_owned());
    }
    let declared_imports = artifact
        .manifest
        .imports
        .iter()
        .map(|import| (import.contract.0.as_str(), import.optional))
        .collect::<BTreeMap<_, _>>();
    if declared_imports.len() != artifact.manifest.imports.len()
        || imports
            .iter()
            .any(|name| !declared_imports.contains_key(name.as_str()))
        || declared_imports
            .iter()
            .any(|(name, optional)| !optional && !imports.contains(*name))
    {
        return Err(incompatible("manifest imports disagree with the component"));
    }

    Ok(imports)
}

fn register_functions(
    contract: &str,
    artifact: &CapsuleArtifact,
    mut actual_functions: ActualFunctions,
    functions: &mut BTreeMap<(String, String), Function>,
) -> Result<(), PlatformError> {
    let mut descriptors = artifact
        .contracts
        .iter()
        .filter(|descriptor| descriptor.id.0 == contract);
    let descriptor = descriptors.next();
    if descriptors.next().is_some() {
        return Err(incompatible("duplicate contract metadata"));
    }
    if let Some(descriptor) = descriptor {
        for described in descriptor
            .interfaces
            .iter()
            .flat_map(|interface| &interface.functions)
        {
            let Some((actual, function)) = actual_functions.remove(&described.name) else {
                return Err(incompatible(
                    "contract metadata names a missing or repeated function",
                ));
            };
            validate_descriptor(described, &actual)?;
            if functions
                .insert((contract.to_owned(), described.id.0.clone()), function)
                .is_some()
            {
                return Err(incompatible(
                    "contract metadata repeats a function identity",
                ));
            }
        }
        if !actual_functions.is_empty() {
            return Err(incompatible("contract metadata omits component functions"));
        }
    } else {
        // Direct backend callers (including the retained Phase 0 harness)
        // may provide no descriptor. Actual component types remain the
        // authority; directory catalog publication supplies descriptors.
        for (name, (_, function)) in actual_functions {
            functions.insert((contract.to_owned(), name), function);
        }
    }
    Ok(())
}

fn signature(
    function: &ComponentFunc,
    asynchronous: bool,
    config: &WasmtimeConfig,
    remaining: &mut usize,
) -> Result<(Vec<Type>, Vec<Type>), PlatformError> {
    signature_with_resources(function, asynchronous, config, remaining, &[])
}
fn signature_with_resources(
    function: &ComponentFunc,
    asynchronous: bool,
    config: &WasmtimeConfig,
    remaining: &mut usize,
    resources: &[wasmtime::component::ResourceType],
) -> Result<(Vec<Type>, Vec<Type>), PlatformError> {
    if function.async_() != asynchronous {
        return Err(incompatible(
            "Component Model function kind does not match the host/export profile",
        ));
    }
    let count = function
        .params()
        .len()
        .checked_add(function.results().len())
        .ok_or_else(exhausted)?;
    *remaining = remaining.checked_sub(count).ok_or_else(exhausted)?;
    let params = function.params().map(|(_, ty)| ty).collect::<Vec<_>>();
    let results = function.results().collect::<Vec<_>>();
    // Use the same fuel that the store will receive. Increasing it later to
    // accommodate host imports would invalidate the lifted-allocation proof.
    check_host_types(&params, config, remaining, resources)?;
    check_host_types(&results, config, remaining, resources)?;
    Ok((params, results))
}

fn check_types(
    types: &[Type],
    config: &WasmtimeConfig,
    remaining: &mut usize,
) -> Result<(), PlatformError> {
    let plan = validate_signature(types, config.value_codec_limits, config.hostcall_fuel)?;
    *remaining = remaining
        .checked_sub(plan.examined_type_nodes)
        .ok_or_else(exhausted)?;
    Ok(())
}

fn check_host_types(
    types: &[Type],
    config: &WasmtimeConfig,
    remaining: &mut usize,
    resources: &[wasmtime::component::ResourceType],
) -> Result<(), PlatformError> {
    let plan = crate::values::validate_host_signature(
        types,
        config.value_codec_limits,
        config.hostcall_fuel,
        resources,
    )?;
    *remaining = remaining
        .checked_sub(plan.examined_type_nodes)
        .ok_or_else(exhausted)?;
    Ok(())
}

fn retain(
    bytes: usize,
    retained: &mut usize,
    config: &WasmtimeConfig,
) -> Result<(), PlatformError> {
    let next = retained.checked_add(bytes).ok_or_else(exhausted)?;
    if next > config.maximum_artifact_metadata_bytes {
        return Err(exhausted());
    }
    *retained = next;
    Ok(())
}

fn validate_descriptor(
    described: &FunctionDescriptor,
    actual: &ComponentFunc,
) -> Result<(), PlatformError> {
    if described.id.0.is_empty()
        || described.asynchronous != actual.async_()
        || described.parameters.len() != actual.params().len()
        || described.results.len() != actual.results().len()
        || described
            .parameters
            .iter()
            .zip(actual.params())
            .any(|(field, (name, ty))| field.name != name || !matches_type(&field.value_type, &ty))
        || described
            .results
            .iter()
            .zip(actual.results())
            .any(|(field, ty)| !matches_type(&field.value_type, &ty))
    {
        return Err(incompatible(
            "contract metadata signature disagrees with the component",
        ));
    }
    Ok(())
}

fn matches_type(described: &ValueType, actual: &Type) -> bool {
    match (described, actual) {
        (ValueType::Bool, Type::Bool)
        | (ValueType::U8, Type::U8)
        | (ValueType::U16, Type::U16)
        | (ValueType::U32, Type::U32)
        | (ValueType::U64, Type::U64)
        | (ValueType::S8, Type::S8)
        | (ValueType::S16, Type::S16)
        | (ValueType::S32, Type::S32)
        | (ValueType::S64, Type::S64)
        | (ValueType::F32, Type::Float32)
        | (ValueType::F64, Type::Float64)
        | (ValueType::Char, Type::Char)
        | (ValueType::String, Type::String)
        | (ValueType::Record(_), Type::Record(_))
        | (ValueType::Variant(_), Type::Variant(_) | Type::Enum(_)) => true,
        (ValueType::Bytes, Type::List(list)) => list.ty() == Type::U8,
        (ValueType::List(inner), Type::List(list)) => matches_type(inner, &list.ty()),
        (ValueType::Option(inner), Type::Option(option)) => matches_type(inner, &option.ty()),
        (ValueType::Tuple(fields), Type::Tuple(tuple)) => {
            fields.len() == tuple.types().len()
                && fields
                    .iter()
                    .zip(tuple.types())
                    .all(|(field, ty)| matches_type(field, &ty))
        }
        (ValueType::Result { ok, error }, Type::Result(result)) => {
            optional_type(ok.as_deref(), result.ok())
                && optional_type(error.as_deref(), result.err())
        }
        _ => false,
    }
}

fn optional_type(described: Option<&ValueType>, actual: Option<Type>) -> bool {
    match (described, actual) {
        (Some(described), Some(actual)) => matches_type(described, &actual),
        (None, None) => true,
        _ => false,
    }
}

fn take_name(
    name: &str,
    config: &WasmtimeConfig,
    remaining: &mut usize,
) -> Result<(), PlatformError> {
    *remaining = remaining.checked_sub(1).ok_or_else(exhausted)?;
    if name.is_empty() || name.len() > config.value_codec_limits.max_type_name_bytes {
        return Err(exhausted());
    }
    Ok(())
}

fn incompatible(message: &str) -> PlatformError {
    platform_error(PlatformErrorCode::IncompatibleContract, message, false)
}

fn exhausted() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "component interface exceeds its configured bound",
        false,
    )
}

fn retained_function_bytes(
    function: &ComponentFunc,
    contract: &str,
    name: &str,
) -> Result<usize, PlatformError> {
    let value_bytes = function
        .params()
        .len()
        .checked_add(function.results().len())
        .and_then(|count| count.checked_mul(std::mem::size_of::<Type>()))
        .ok_or_else(exhausted)?;
    let bytes = value_bytes
        .checked_add(contract.len())
        .and_then(|bytes| bytes.checked_add(name.len()))
        .and_then(|bytes| bytes.checked_add(4096))
        .ok_or_else(exhausted)?;
    Ok(bytes)
}
