use super::super::{CanonicalTarget, Scheme};
use serde::Deserialize;

pub const MAX_POLICIES: usize = 32;
pub const MAX_AGE_SECONDS: u64 = 60;
/// Includes the complete input key; never a hash with collision ambiguity.
pub const MAX_KEY_BYTES: usize = 8192;

/// Operator authority, not a guest response directive. This profile is an
/// assertion that output depends only on the immutable publication, public
/// principal, exact URL and the enumerated headers. Secret or mutable provider
/// dependencies are not eligible for this profile.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicCachePolicy {
    pub dependency_profile: DependencyProfile,
    pub tenant: String,
    pub publication: String,
    pub release: String,
    pub renderer_profile: String,
    pub authority: String,
    pub path: String,
    pub generation: u64,
    pub maximum_age_seconds: u64,
    pub vary: Vec<VaryField>,
}

#[derive(Clone, Copy, Deserialize)]
pub enum DependencyProfile {
    #[serde(rename = "immutable-public-v1")]
    ImmutablePublicV1,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VaryField {
    pub name: String,
    pub values: Vec<String>,
}

impl PublicCachePolicy {
    #[must_use]
    pub fn validate(&self) -> bool {
        if self.generation == 0
            || !(1..=MAX_AGE_SECONDS).contains(&self.maximum_age_seconds)
            || self.vary.len() > 3
            || [
                &self.tenant,
                &self.publication,
                &self.release,
                &self.renderer_profile,
                &self.authority,
            ]
                .iter()
                .any(|v| v.is_empty() || v.len() > 256 || !v.bytes().all(|b| b.is_ascii_graphic()))
            || self.path.len() > 1024
        {
            return false;
        }
        let canonical = [Scheme::Http, Scheme::Https].into_iter().any(|scheme| {
            CanonicalTarget::parse(scheme, &self.authority, &self.path).is_ok_and(|target| {
                target.authority() == self.authority && target.path() == self.path
            })
        });
        canonical
            && !self.path.contains('?')
            && self.vary.iter().enumerate().all(|(index, field)| {
                ["accept", "accept-language", "accept-encoding"].contains(&field.name.as_str())
                    && !self.vary[..index].iter().any(|v| v.name == field.name)
                    && !field.values.is_empty()
                    && field.values.len() <= 16
                    && field.values.iter().enumerate().all(|(index, value)| {
                        value.len() <= 128
                            && value.bytes().all(|b| (32..127).contains(&b))
                            && !field.values[..index].contains(value)
                    })
            })
    }
}
