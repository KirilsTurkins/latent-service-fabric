//! Exact legacy descriptor compilation. Rich named types require checked WIT.
use crate::{
    compare_descriptors, BindingCompiler, BindingPlan, ComparisonLimits, ContractDescriptor,
    FieldDescriptor, StructuralCompatibility, ValueType,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

/// Pure bounded ABI comparison; the returned DTO grants no execution authority.
/// No adapter, version substitution, or unresolved named-type inference occurs.
#[derive(Debug, Clone, Copy, Default)]
pub struct BoundedBindingCompiler {
    pub limits: ComparisonLimits,
}
impl BoundedBindingCompiler {
    pub fn compile_exact(
        &self,
        consumer: &ContractDescriptor,
        provider: &ContractDescriptor,
    ) -> Result<BindingPlan, PlatformError> {
        let report = compare_descriptors(consumer, provider, self.limits)?;
        if !report.analysis_complete
            || report.level != StructuralCompatibility::Identical
            || consumer.id != provider.id
            || consumer.package_name != provider.package_name
            || consumer.semantic_version != provider.semantic_version
            || !qualified(consumer)
        {
            return Err(PlatformError {
                code: PlatformErrorCode::IncompatibleContract,
                message: "binding-contract-not-exact".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        // Hash actual checked ABI, never caller-supplied digest labels. Comparison
        // bounded every collection, string and recursive type before this walk.
        let mut hash = Sha256::new();
        hash.update(b"lsf-descriptor-binding-v1\0");
        text(&mut hash, &consumer.id.0);
        text(&mut hash, &consumer.package_name);
        text(&mut hash, &consumer.semantic_version);
        let mut dependencies: Vec<_> = consumer.dependencies.iter().collect();
        dependencies.sort();
        count(&mut hash, dependencies.len());
        for id in dependencies {
            text(&mut hash, &id.0);
        }
        let mut interfaces: Vec<_> = consumer.interfaces.iter().collect();
        interfaces.sort_by_key(|value| &value.id);
        count(&mut hash, interfaces.len());
        for interface in interfaces {
            text(&mut hash, &interface.id.0);
            let mut functions: Vec<_> = interface.functions.iter().collect();
            functions.sort_by_key(|value| &value.name);
            count(&mut hash, functions.len());
            for function in functions {
                text(&mut hash, &function.id.0);
                text(&mut hash, &function.name);
                fields(&mut hash, &function.parameters);
                fields(&mut hash, &function.results);
            }
        }
        Ok(BindingPlan {
            consumer: consumer.id.clone(),
            provider: provider.id.clone(),
            required_adapters: Vec::new(),
            plan_digest: format!("sha256:{:x}", hash.finalize()),
        })
    }
}
fn qualified(contract: &ContractDescriptor) -> bool {
    if semver::Version::parse(&contract.semantic_version).is_err() {
        return false;
    }
    let matches = |id: &str| {
        id.rsplit_once('@').is_some_and(|(interface, version)| {
            version == contract.semantic_version
                && interface.split_once('/').is_some_and(|(package, name)| {
                    package == contract.package_name
                        && package.contains(':')
                        && !name.is_empty()
                        && !name.contains('/')
                })
        })
    };
    matches(&contract.id.0)
        && contract
            .interfaces
            .iter()
            .all(|interface| matches(&interface.id.0))
}
impl BindingCompiler for BoundedBindingCompiler {
    fn compile<'a>(
        &'a self,
        consumer: &'a ContractDescriptor,
        provider: &'a ContractDescriptor,
    ) -> BoxFuture<'a, Result<BindingPlan, PlatformError>> {
        Box::pin(async move { self.compile_exact(consumer, provider) })
    }
}
fn count(hash: &mut Sha256, value: usize) {
    hash.update((value as u64).to_le_bytes());
}
fn text(hash: &mut Sha256, value: &str) {
    count(hash, value.len());
    hash.update(value.as_bytes());
}
fn fields(hash: &mut Sha256, values: &[FieldDescriptor]) {
    count(hash, values.len());
    for field in values {
        text(hash, &field.name);
        ty(hash, &field.value_type);
    }
}
fn ty(hash: &mut Sha256, value: &ValueType) {
    use ValueType as T;
    let tag = match value {
        T::Bool => 0,
        T::U8 => 1,
        T::U16 => 2,
        T::U32 => 3,
        T::U64 => 4,
        T::S8 => 5,
        T::S16 => 6,
        T::S32 => 7,
        T::S64 => 8,
        T::F32 => 9,
        T::F64 => 10,
        T::Char => 11,
        T::String => 12,
        T::List(_) | T::Bytes => 13,
        T::Option(_) => 14,
        T::Result { .. } => 15,
        T::Tuple(_) => 16,
        // Rejected by structural preflight, retained for an exhaustive encoding.
        T::Record(_) => 17,
        T::Variant(_) => 18,
        T::Resource(_) => 19,
        T::Future(_) => 20,
        T::Stream(_) => 21,
    };
    hash.update([tag]);
    match value {
        T::Bytes => ty(hash, &T::U8),
        T::List(inner) | T::Option(inner) | T::Future(inner) | T::Stream(inner) => ty(hash, inner),
        T::Result { ok, error } => {
            for inner in [ok, error] {
                hash.update([u8::from(inner.is_some())]);
                if let Some(inner) = inner {
                    ty(hash, inner);
                }
            }
        }
        T::Tuple(values) => {
            count(hash, values.len());
            for inner in values {
                ty(hash, inner);
            }
        }
        T::Record(name) | T::Variant(name) | T::Resource(name) => text(hash, name),
        _ => (),
    }
}

#[cfg(test)]
mod tests;
