use super::{invalid_response, proto, Bounds, Check, Failure};
use prost::Message;

impl Check for proto::InspectHttpTargetResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        if self.schema_version != 1 || self.candidates.len() > 32 || self.live_grants_checked {
            return Err(invalid_response());
        }
        for text in [
            &self.tenant,
            &self.service,
            &self.contract,
            &self.function,
            &self.route,
        ] {
            b.id(text)?;
        }
        b.count(self.candidates.len())?;
        let mut revisions = std::collections::BTreeSet::new();
        for candidate in &self.candidates {
            if !revisions.insert(&candidate.revision_id)
                || candidate.dependencies.len() > 32
                || candidate.reasons.len() > 16
                || candidate.routing_weight > u32::from(u16::MAX)
                || (self.state != 1 && candidate.eligible)
            {
                return Err(invalid_response());
            }
            b.id(&candidate.deployment_id)?;
            b.id(&candidate.revision_id)?;
            b.digest(&candidate.component_digest)?;
            for publication in [&candidate.publication, &candidate.requested_publication]
                .into_iter()
                .flatten()
            {
                b.id(&publication.tenant)?;
                b.id(&publication.id)?;
                if publication
                    .id
                    .parse::<latent_core::PublicationId>()
                    .is_err()
                {
                    return Err(invalid_response());
                }
            }
            if let Some(digest) = &candidate.package_digest {
                b.digest(digest)?;
            }
            if let Some(kind) = &candidate.publication_kind {
                if !matches!(kind.as_str(), "capsule" | "browser-assets" | "ssr-package")
                    || candidate.package_digest.is_none()
                {
                    return Err(invalid_response());
                }
            }
            b.count(candidate.dependencies.len())?;
            if candidate.http_bindings.len() > 32 {
                return Err(invalid_response());
            }
            for binding in &candidate.http_bindings {
                b.id(&binding.id)?;
                if !matches!(
                    binding.state.as_str(),
                    "configured-current" | "deployment-changed"
                ) || binding.generation == 0
                {
                    return Err(invalid_response());
                }
            }
            for dependency in &candidate.dependencies {
                b.id(&dependency.capability)?;
                b.id(&dependency.provider_profile)?;
                b.id(&dependency.configuration_digest)?;
                hex(&dependency.policy_identity_digest)?;
                if !matches!(
                    dependency.state.as_str(),
                    "configured-current"
                        | "policy-changed-or-revoked"
                        | "provider-unavailable"
                        | "publication-unavailable"
                        | "route-changed-or-unavailable"
                        | "inspection-indeterminate"
                ) || dependency.policies.len() > 32
                {
                    return Err(invalid_response());
                }
                let binding = dependency.binding.as_ref().ok_or_else(invalid_response)?;
                for revision in std::iter::once(binding).chain(&dependency.policies) {
                    b.id(&revision.id)?;
                    b.id(&revision.digest)?;
                }
            }
            let preparation = candidate
                .preparation
                .as_ref()
                .ok_or_else(invalid_response)?;
            if preparation.imports.len() > 64 || preparation.exports.len() > 128 {
                return Err(invalid_response());
            }
            for text in [
                &preparation.engine_version,
                &preparation.engine_configuration_digest,
                &preparation.target_triple,
                &preparation.cpu_feature_set,
            ]
            .into_iter()
            .flatten()
            {
                b.id(text)?;
            }
            if let Some(fingerprint) = &preparation.sealed_metadata_fingerprint {
                hex(fingerprint)?;
            }
            if let Some(digest) = &preparation.engine_configuration_digest {
                hex(digest
                    .strip_prefix("blake3:")
                    .ok_or_else(invalid_response)?)?;
            }
            for import in &preparation.imports {
                b.id(import)?;
            }
            for export in &preparation.exports {
                b.id(&export.contract)?;
                b.id(&export.function)?;
            }
            if preparation.state == 1
                && (preparation.profile.is_none()
                    || preparation.engine_version.is_none()
                    || preparation.engine_configuration_digest.is_none()
                    || preparation.target_triple.is_none()
                    || preparation.cpu_feature_set.is_none()
                    || preparation.declared_budget.is_none()
                    || preparation.import_count != Some(preparation.imports.len() as u64)
                    || preparation.function_count != Some(preparation.exports.len() as u64)
                    || preparation.hostcall_fuel.is_none()
                    || preparation.maximum_lifted_bytes.is_none()
                    || preparation.maximum_type_nodes.is_none())
            {
                return Err(invalid_response());
            }
            if let Some(diagnostic) = &preparation.diagnostic {
                if diagnostic.schema_version != 1 {
                    return Err(invalid_response());
                }
                if let Some(digest) = &diagnostic.profile_digest {
                    hex(digest)?;
                }
            }
            if candidate.eligible
                && (!candidate.export_compatible
                    || candidate.publication.is_none()
                    || candidate.package_digest.is_none()
                    || candidate.publication_generation.is_none()
                    || candidate.routing_weight == 0
                    || candidate.reasons != [1]
                    || !matches!(preparation.state, 1 | 4)
                    || candidate
                        .dependencies
                        .iter()
                        .any(|dependency| dependency.state != "configured-current"))
            {
                return Err(invalid_response());
            }
        }
        if self.encoded_len() > 64 * 1024 {
            return Err(invalid_response());
        }
        Ok(())
    }
}
fn hex(value: &str) -> Result<(), Failure> {
    if value.len() == 64
        && value
            .bytes()
            .all(|value| matches!(value,b'0'..=b'9'|b'a'..=b'f'))
    {
        Ok(())
    } else {
        Err(invalid_response())
    }
}
