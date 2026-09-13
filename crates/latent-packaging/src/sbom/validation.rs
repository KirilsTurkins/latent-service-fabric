use super::{
    SbomDigestScope, SbomEntryKind, SbomInventory, SbomInventoryEntry, SbomLimits, SBOM_PATH,
};
use latent_artifacts::package::{validate_package_path, PackageLimits};
use latent_core::PlatformError;
use spdx::lexer::Token;
use std::collections::{BTreeMap, BTreeSet};

pub(super) fn inventory(value: &SbomInventory, limits: SbomLimits) -> Result<(), PlatformError> {
    limits.validate()?;
    if value.format_version != 1 {
        return Err(crate::invalid("unsupported-sbom-inventory-version"));
    }
    text(&value.package_name, 128, limits)?;
    text(&value.package_version, 128, limits)?;
    if value.entries.len() > limits.max_entries {
        return Err(crate::exceeded("sbom-entry-limit"));
    }
    // No caller-controlled comparison/sort or clone before every field is bounded.
    for row in &value.entries {
        entry(row, limits)?;
    }
    drop(super::json::encode(value, limits.max_document_bytes)?);
    let mut identities = BTreeSet::new();
    let mut paths = BTreeSet::new();
    let mut dependencies: BTreeMap<_, &SbomInventoryEntry> = BTreeMap::new();
    for row in &value.entries {
        if !identities.insert((row.kind, &row.name, &row.version, &row.source, &row.path)) {
            return Err(crate::invalid("duplicate-sbom-entry"));
        }
        if row.path.as_ref().is_some_and(|path| !paths.insert(path)) {
            return Err(crate::invalid("duplicate-sbom-output-path"));
        }
        if row.kind.is_dependency() {
            let key = (&row.name, &row.version, &row.source);
            if let Some(previous) = dependencies.insert(key, row) {
                if previous.license_expression != row.license_expression
                    || previous.digest != row.digest
                    || previous.digest_scope != row.digest_scope
                    || previous.size != row.size
                    || previous.manifest_digest != row.manifest_digest
                    || previous.manifest_size != row.manifest_size
                    || previous.origin != row.origin
                {
                    return Err(crate::invalid("conflicting-sbom-dependency-attribution"));
                }
            }
        }
    }
    Ok(())
}
fn text(value: &str, maximum: usize, limits: SbomLimits) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > maximum.min(limits.max_string_bytes)
        || !value.is_ascii()
        || value.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err(crate::invalid("invalid-sbom-string"));
    }
    Ok(())
}
fn entry(row: &SbomInventoryEntry, limits: SbomLimits) -> Result<(), PlatformError> {
    text(&row.name, 256, limits)?;
    if let Some(version) = &row.version {
        text(version, 128, limits)?;
    }
    if let Some(source) = &row.source {
        text(source, 512, limits)?;
        validate_source(source)?;
    }
    if let Some(expression) = &row.license_expression {
        text(expression, 1024, limits)?;
        license(expression)?;
    }
    if row.digest.is_some() != row.digest_scope.is_some()
        || row.manifest_digest.is_some() != row.manifest_size.is_some()
        || row.size.is_some_and(|size| size > 268_435_456)
        || row
            .manifest_size
            .is_some_and(|size| size == 0 || size > 4_194_304)
    {
        return Err(crate::invalid("invalid-sbom-digest-association"));
    }
    if let Some(path) = &row.path {
        text(path, 256, limits)?;
        validate_package_path(path, PackageLimits::default())?;
        if path == SBOM_PATH || path == crate::BUILD_INPUTS_PATH {
            return Err(crate::invalid("recursive-sbom-output"));
        }
    }
    let required_scope = match row.kind {
        SbomEntryKind::Component | SbomEntryKind::Renderer | SbomEntryKind::Asset => {
            Some(SbomDigestScope::OutputBytes)
        }
        SbomEntryKind::WitPackage => Some(SbomDigestScope::WitSource),
        SbomEntryKind::BuildTool => Some(SbomDigestScope::ToolExecutable),
        _ => None,
    };
    if let Some(scope) = required_scope {
        if row.digest_scope != Some(scope)
            || row.size.is_none()
            || row.path.is_some() == (row.kind == SbomEntryKind::BuildTool)
            || row.manifest_digest.is_some()
        {
            return Err(crate::invalid("invalid-sbom-role-association"));
        }
    } else if row.path.is_some()
        || row.size.is_some()
        || !matches!(
            row.digest_scope,
            None | Some(SbomDigestScope::RegistryArchiveDeclared | SbomDigestScope::SourceManifest)
        )
    {
        return Err(crate::invalid("invalid-sbom-dependency-association"));
    }
    if row.digest_scope == Some(SbomDigestScope::SourceManifest)
        && (row.digest != row.manifest_digest || row.manifest_size.is_none())
    {
        return Err(crate::invalid("sbom-source-manifest-mismatch"));
    }
    Ok(())
}
fn validate_source(source: &str) -> Result<(), PlatformError> {
    let valid = if let Some(rest) = source.strip_prefix("https://") {
        let (host, path) = rest.split_once('/').unwrap_or((rest, ""));
        !host.is_empty()
            && host.len() <= 253
            && host.split('.').all(|label| {
                !label.is_empty()
                    && label.len() <= 63
                    && !label.starts_with('-')
                    && !label.ends_with('-')
                    && label
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'-')
            })
            && path
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-._~/".contains(&b))
            && !path.split('/').any(|part| matches!(part, "." | ".."))
    } else if let Some(rest) = source.strip_prefix("urn:lsf:") {
        rest.split_once(':').is_some_and(|(kind, value)| {
            matches!(
                kind,
                "workspace" | "package-path" | "wit" | "build-tool" | "registry" | "captured"
            ) && !value.is_empty()
                && !value.starts_with('/')
                && value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-._~/:@".contains(&b))
                && !value.split('/').any(|part| matches!(part, "" | "." | ".."))
        })
    } else {
        false
    };
    if !valid {
        return Err(crate::invalid("invalid-sbom-source"));
    }
    Ok(())
}
fn license(value: &str) -> Result<(), PlatformError> {
    // Bound token/parenthesis work before the upstream SPDX parser allocates.
    let mut depth = 0_u8;
    for (index, token) in spdx::lexer::Lexer::new(value).enumerate() {
        if index >= 128 {
            return Err(crate::exceeded("sbom-license-token-limit"));
        }
        let token = token.map_err(|_| crate::invalid("invalid-sbom-license-expression"))?;
        match token.token {
            Token::OpenParen => {
                depth = depth
                    .checked_add(1)
                    .filter(|n| *n <= 16)
                    .ok_or_else(|| crate::exceeded("sbom-license-depth-limit"))?;
            }
            Token::CloseParen => {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| crate::invalid("invalid-sbom-license-expression"))?;
            }
            Token::And | Token::Or | Token::With => {
                if !matches!(&value[token.span], "AND" | "OR" | "WITH") {
                    return Err(crate::invalid("invalid-sbom-license-expression"));
                }
            }
            Token::Spdx(_) | Token::Exception(_) | Token::Plus => {}
            _ => return Err(crate::invalid("invalid-sbom-license-expression")),
        }
    }
    if depth != 0 {
        return Err(crate::invalid("invalid-sbom-license-expression"));
    }
    spdx::Expression::parse(value)
        .map_err(|_| crate::invalid("invalid-sbom-license-expression"))?;
    Ok(())
}
