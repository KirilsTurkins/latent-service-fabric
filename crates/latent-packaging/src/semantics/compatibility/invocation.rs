//! Checked targets for the explicit opaque-payload service invocation adapter.
//! This does not compare the service-dispatch ABI with the application's ABI.
use super::{
    lock, preflight, resolved, types, Analysis, ComparedPackageIdentity, Level,
    PackageComparisonLimits,
};
use crate::PackageBundle;
use latent_core::PlatformError;
use wit_parser::{InterfaceId, Resolve};

/// Immutable target facts. Admission, policy, current publication/revision and
/// the canonical service-import proof remain independent compiler requirements.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckedInvocationTarget {
    package: ComparedPackageIdentity,
    interface: Box<str>,
    functions: Box<[String]>,
}
impl CheckedInvocationTarget {
    #[must_use]
    pub fn package(&self) -> &ComparedPackageIdentity {
        &self.package
    }
    #[must_use]
    pub fn interface(&self) -> &str {
        &self.interface
    }
    #[must_use]
    pub fn functions(&self) -> &[String] {
        &self.functions
    }
}

/// Check an exact exported interface against the existing public value profile.
/// Generic invocation decodes payloads against that target at runtime; it does
/// not authorize arbitrary imports, resource handles or signature conversion.
pub fn check_invocation_target(
    package: &PackageBundle,
    interface: &str,
    limits: PackageComparisonLimits,
) -> Result<CheckedInvocationTarget, PlatformError> {
    limits.validate()?;
    let mut analysis = Analysis::new(limits.comparison)?;
    analysis.name(interface)?;
    let lock = lock(package)?;
    preflight(package, &lock, limits, &mut 0, &mut 0, &mut analysis)?;
    let (source, surface) = resolved(package, &lock, limits.semantics)?;
    let exported = *surface.exports.get(interface).ok_or_else(incompatible)?;
    let functions = checked_functions(&source, exported, interface, &mut analysis)?;
    let report = analysis.finish();
    if !report.analysis_complete || report.level != Level::Identical {
        return Err(incompatible());
    }
    Ok(CheckedInvocationTarget {
        package: ComparedPackageIdentity::of(package),
        interface: interface.into(),
        functions,
    })
}

fn checked_functions(
    source: &Resolve,
    exported: InterfaceId,
    interface: &str,
    analysis: &mut Analysis,
) -> Result<Box<[String]>, PlatformError> {
    let functions = &source.interfaces[exported].functions;
    if source.id_of(exported).as_deref() != Some(interface)
        || functions.is_empty()
        || functions.len() > 128
    {
        return Err(incompatible());
    }
    types::inspect_interface(source, exported, analysis)?;
    let mut functions: Vec<_> = functions.keys().cloned().collect();
    functions.sort_unstable();
    Ok(functions.into_boxed_slice())
}
fn incompatible() -> PlatformError {
    crate::semantics::incompatible("unsupported-local-invocation-target")
}

#[cfg(test)]
mod tests {
    use super::*;
    fn checked(body: &str, identity: &str, maximum_nodes: usize) -> bool {
        let mut source = Resolve::default();
        source
            .push_source(
                "target.wit",
                &format!("package tests:target@1.0.0; interface api {{ {body} }}"),
            )
            .unwrap();
        let exported = source
            .interfaces
            .iter()
            .find_map(|(id, _)| {
                (source.id_of(id).as_deref() == Some("tests:target/api@1.0.0")).then_some(id)
            })
            .unwrap();
        let mut analysis = Analysis::new(latent_contracts::ComparisonLimits {
            max_nodes: maximum_nodes,
            ..Default::default()
        })
        .unwrap();
        if checked_functions(&source, exported, identity, &mut analysis).is_err() {
            return false;
        }
        let report = analysis.finish();
        report.analysis_complete && report.level == Level::Identical
    }
    #[test]
    fn targets_require_exact_identity_bounded_value_types_and_a_real_function() {
        use std::fmt::Write;
        let body = "record item { value: u32 } call: func(value: item) -> result<string, string>;";
        assert!(checked(body, "tests:target/api@1.0.0", 128));
        assert!(!checked(body, "tests:target/api@2.0.0", 128));
        assert!(!checked(body, "tests:target/api@1.0.0", 1));
        for body in [
            "",
            "resource file; call: func(value: borrow<file>);",
            "call: func() -> stream<u8>;",
        ] {
            assert!(!checked(body, "tests:target/api@1.0.0", 128));
        }
        assert!(checked(
            "call: async func() -> u32;",
            "tests:target/api@1.0.0",
            128
        ));
        let mut excessive = String::new();
        for n in 0..129 {
            write!(&mut excessive, "call{n}: func();").unwrap();
        }
        assert!(!checked(&excessive, "tests:target/api@1.0.0", 1024));
    }
}
