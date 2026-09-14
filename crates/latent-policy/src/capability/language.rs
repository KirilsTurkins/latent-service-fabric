use latent_core::{InvocationPrincipal, PlatformError, PrincipalKind};
use serde::{Deserialize, Serialize};

use super::{
    identifier, invalid, operation, publication, unique, CapabilityCeiling, ResourceConstraint,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum PrincipalClass {
    User,
    Service,
    Node,
    Trigger,
    Administrator,
}

impl PrincipalClass {
    fn matches(self, kind: PrincipalKind) -> bool {
        matches!(
            (self, kind),
            (Self::User, PrincipalKind::User)
                | (Self::Service, PrincipalKind::Service)
                | (Self::Node, PrincipalKind::Node)
                | (Self::Trigger, PrincipalKind::Trigger)
                | (Self::Administrator, PrincipalKind::Administrator)
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Principal {
    kind: PrincipalClass,
    subject: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
enum Effect {
    Allow,
    Deny,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Rule {
    id: String,
    effect: Effect,
    principals: Vec<Principal>,
    services: Vec<String>,
    publications: Vec<String>,
    capability: String,
    operations: Vec<String>,
    resources: ResourceConstraint,
    ceiling: CapabilityCeiling,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    require_audit: bool,
}

pub(super) struct EvaluatedGrant {
    pub ceiling: CapabilityCeiling,
    pub require_audit: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Document {
    format_version: u32,
    tenant: String,
    rules: Vec<Rule>,
}

/// Validated data, not permission. Construction owns only a bounded document;
/// runtime decisions also require the live configured catalog/policy owner.
#[derive(Debug)]
pub struct CapabilityPolicy {
    document: Document,
    canonical: Box<[u8]>,
    digest: String,
}

impl CapabilityPolicy {
    pub fn parse(bytes: &[u8]) -> Result<Self, PlatformError> {
        super::preflight(bytes)?;
        let document: Document = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        if document.format_version != 1
            || !identifier(&document.tenant)
            || document.rules.len() > super::MAX_RULES
        {
            return Err(invalid());
        }
        let mut ids = std::collections::BTreeSet::new();
        for rule in &document.rules {
            if !identifier(&rule.id)
                || !ids.insert(&rule.id)
                || !unique(&rule.principals, |value| identifier(&value.subject))
                || !unique(&rule.services, |value| identifier(value))
                || !unique(&rule.publications, |value| publication(value))
                || !unique(&rule.operations, |value| operation(&rule.capability, value))
                || latent_core::PHASE3_HOST_ABI_V3
                    .interface(&rule.capability)
                    .is_none()
                || !rule.resources.compatible(&rule.capability)
            {
                return Err(invalid());
            }
            rule.resources.validate()?;
            rule.ceiling.validate()?;
        }
        let canonical = serde_json::to_vec(&document).map_err(|_| invalid())?;
        if canonical.len() > super::MAX_DOCUMENT_BYTES {
            return Err(invalid());
        }
        let digest = latent_artifacts::package::artifact_blob_digest(&canonical).to_string();
        Ok(Self {
            document,
            canonical: canonical.into_boxed_slice(),
            digest,
        })
    }

    #[must_use]
    pub fn tenant(&self) -> &str {
        &self.document.tenant
    }
    #[must_use]
    pub fn canonical(&self) -> &[u8] {
        &self.canonical
    }
    #[must_use]
    pub fn digest(&self) -> &str {
        &self.digest
    }

    pub(super) fn evaluate(
        &self,
        principal: &InvocationPrincipal,
        service: &str,
        publication: &str,
        capability: &str,
        operation: &str,
        resource: &super::ResourceTarget<'_>,
    ) -> Option<EvaluatedGrant> {
        if principal.tenant.as_ref().map(|tenant| tenant.0.as_str()) != Some(self.tenant()) {
            return None;
        }
        let mut allowed: Option<CapabilityCeiling> = None;
        let mut require_audit = false;
        for rule in &self.document.rules {
            if rule.capability != capability
                || !rule.operations.iter().any(|value| value == operation)
                || !rule.services.iter().any(|value| value == service)
                || !rule.publications.iter().any(|value| value == publication)
                || !rule.principals.iter().any(|value| {
                    value.subject == principal.subject && value.kind.matches(principal.kind)
                })
                || !rule.resources.covers(resource)
            {
                continue;
            }
            if rule.effect == Effect::Deny {
                return None;
            }
            // Matching grants narrow one another; disjoint matching rules must
            // never combine selected dimensions into a broader synthetic grant.
            allowed = Some(allowed.map_or(rule.ceiling, |value| value.intersect(rule.ceiling)));
            require_audit |= rule.require_audit;
        }
        allowed.map(|ceiling| EvaluatedGrant {
            ceiling,
            require_audit,
        })
    }
}
