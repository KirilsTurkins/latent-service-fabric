use super::{invalid, Authentication, CanonicalTarget, HttpIngressConfig, PlatformError, Scheme};
use serde::Deserialize;
use std::collections::BTreeSet;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicDocumentNavigation {
    pub authority: String,
    pub tenant: String,
    pub mount: String,
}

impl PublicDocumentNavigation {
    pub(crate) fn matches(&self, target: &CanonicalTarget, tenant: &str) -> bool {
        self.authority == target.authority()
            && self.tenant == tenant
            && (self.mount == "/"
                || target.path() == self.mount
                || target
                    .path()
                    .strip_prefix(&self.mount)
                    .is_some_and(|suffix| suffix.starts_with('/')))
    }
}

pub(super) fn validate(
    http: &HttpIngressConfig,
    scheme: Scheme,
    authentication: &Authentication,
) -> Result<(), PlatformError> {
    let policies = &http.public_document_navigation;
    if policies.is_empty() {
        return Ok(());
    }
    let Authentication::PublicOrigins(origins) = authentication else {
        return Err(invalid("httpIngress.publicDocumentNavigation"));
    };
    if policies.len() > 32 {
        return Err(invalid("httpIngress.publicDocumentNavigation"));
    }
    let mut unique = BTreeSet::new();
    for policy in policies {
        let target = CanonicalTarget::parse(scheme, &policy.authority, &policy.mount)
            .map_err(|_| invalid("httpIngress.publicDocumentNavigation"))?;
        if target.authority() != policy.authority
            || target.path() != policy.mount
            || target.query().is_some()
            || policy.mount.len() > 240
            || (policy.mount != "/" && policy.mount.ends_with('/'))
            || policy.mount == "/_lsf"
            || policy.mount.starts_with("/_lsf/")
            || !unique.insert((&policy.authority, &policy.mount))
            || !origins.iter().any(|(authority, principal)| {
                authority == &policy.authority
                    && principal
                        .tenant
                        .as_ref()
                        .is_some_and(|tenant| tenant.0 == policy.tenant)
            })
        {
            return Err(invalid("httpIngress.publicDocumentNavigation"));
        }
    }
    Ok(())
}
