use super::{
    invalid, Authentication, CanonicalTarget, CredentialRole, HttpIngressConfig, NodeConfig,
    PlatformError, Scheme,
};
use serde::Deserialize;
use std::collections::BTreeSet;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BrowserOrigin {
    pub authority: String,
    pub tenant: String,
}

pub(super) fn derive(
    config: &NodeConfig,
    http: &HttpIngressConfig,
    scheme: Scheme,
    authentication: &Authentication,
) -> Result<Vec<BrowserOrigin>, PlatformError> {
    if let Authentication::PublicOrigins(origins) = authentication {
        if !http.browser_origins.is_empty() {
            return Err(invalid("httpIngress.browserOrigins"));
        }
        return Ok(origins
            .iter()
            .map(|(authority, principal)| BrowserOrigin {
                authority: authority.clone(),
                tenant: principal
                    .tenant
                    .as_ref()
                    .expect("validated public tenant")
                    .0
                    .clone(),
            })
            .collect());
    }
    let mut unique = BTreeSet::new();
    if http.browser_origins.len() > 32 {
        return Err(invalid("httpIngress.browserOrigins"));
    }
    for origin in &http.browser_origins {
        let target = CanonicalTarget::parse(scheme, &origin.authority, "/")
            .map_err(|_| invalid("httpIngress.browserOrigins"))?;
        if target.authority() != origin.authority
            || !unique.insert(&origin.authority)
            || !config.credentials.iter().any(|credential| {
                credential.tenant == origin.tenant && credential.role == CredentialRole::Invoke
            })
        {
            return Err(invalid("httpIngress.browserOrigins"));
        }
    }
    Ok(http.browser_origins.clone())
}
