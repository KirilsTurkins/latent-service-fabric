//! Bounded, explicit disclosure of activation-owned metadata.

use latent_core::{Metadata, PlatformError, PlatformErrorCode};

use crate::containment::platform_error;

const MAXIMUM_ENTRIES_PER_LIST: usize = 32;
const MAXIMUM_KEY_BYTES: usize = 256;

/// Node policy for values disclosed by `latent:context`.
///
/// Metadata keys retain their complete namespace. Claims and trace baggage use
/// exact, case-sensitive keys; an empty list discloses none. Each list has at
/// most 32 distinct, nonempty entries of at most 256 UTF-8 bytes, without control
/// characters. Fixed identity and trace fields are independent of this policy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextExposurePolicy {
    pub metadata_prefixes: Vec<String>,
    pub claim_keys: Vec<String>,
    pub baggage_keys: Vec<String>,
}

impl Default for ContextExposurePolicy {
    fn default() -> Self {
        Self {
            metadata_prefixes: vec!["guest.".to_owned()],
            claim_keys: Vec::new(),
            baggage_keys: Vec::new(),
        }
    }
}

impl ContextExposurePolicy {
    pub fn validate(&self) -> Result<(), PlatformError> {
        for entries in [
            &self.metadata_prefixes,
            &self.claim_keys,
            &self.baggage_keys,
        ] {
            if entries.len() > MAXIMUM_ENTRIES_PER_LIST {
                return Err(invalid_policy());
            }
            for (index, entry) in entries.iter().enumerate() {
                if entry.is_empty()
                    || entry.len() > MAXIMUM_KEY_BYTES
                    || entry.chars().any(char::is_control)
                    || entries[..index].contains(entry)
                {
                    return Err(invalid_policy());
                }
            }
        }
        Ok(())
    }

    pub(crate) fn metadata_pairs(&self, metadata: &Metadata) -> Vec<(String, String)> {
        selected_pairs(metadata, |key| {
            self.metadata_prefixes
                .iter()
                .any(|prefix| key.starts_with(prefix))
        })
    }

    pub(crate) fn claim_pairs(&self, claims: &Metadata) -> Vec<(String, String)> {
        selected_pairs(claims, |key| {
            self.claim_keys.iter().any(|allowed| key == allowed)
        })
    }

    pub(crate) fn baggage_pairs(&self, baggage: &Metadata) -> Vec<(String, String)> {
        selected_pairs(baggage, |key| {
            self.baggage_keys.iter().any(|allowed| key == allowed)
        })
    }

    pub(crate) fn append_profile_fields(&self, fields: &mut Metadata) {
        fields.insert(
            "context-exposure-policy".to_owned(),
            "explicit-allowlists-v1".to_owned(),
        );
        for (name, entries) in [
            ("context-metadata-prefix", &self.metadata_prefixes),
            ("context-claim-key", &self.claim_keys),
            ("context-baggage-key", &self.baggage_keys),
        ] {
            // Config validation bounds this temporary reference list. Entry
            // order does not change disclosure or prepared-state compatibility.
            let mut entries = entries.iter().collect::<Vec<_>>();
            entries.sort_unstable();
            fields.insert(format!("{name}-count"), entries.len().to_string());
            for (index, entry) in entries.into_iter().enumerate() {
                fields.insert(format!("{name}-{index}"), entry.clone());
            }
        }
    }
}

fn selected_pairs(metadata: &Metadata, include: impl Fn(&str) -> bool) -> Vec<(String, String)> {
    metadata
        .iter()
        .filter(|(key, _)| include(key))
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect()
}

fn invalid_policy() -> PlatformError {
    platform_error(
        PlatformErrorCode::InvalidArgument,
        "invalid context exposure policy",
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn values() -> Metadata {
        Metadata::from([
            ("guest.visible".to_owned(), "public".to_owned()),
            ("guest.".to_owned(), "namespace".to_owned()),
            ("Guest.visible".to_owned(), "case-sensitive".to_owned()),
            ("private.secret".to_owned(), "secret".to_owned()),
            ("role".to_owned(), "reader".to_owned()),
            ("role.extra".to_owned(), "not-exact".to_owned()),
        ])
    }

    #[test]
    fn default_discloses_only_guest_namespaced_metadata_without_renaming() {
        let policy = ContextExposurePolicy::default();
        policy.validate().unwrap();
        assert_eq!(
            policy.metadata_pairs(&values()),
            vec![
                ("guest.".to_owned(), "namespace".to_owned()),
                ("guest.visible".to_owned(), "public".to_owned()),
            ]
        );
        assert!(policy.claim_pairs(&values()).is_empty());
        assert!(policy.baggage_pairs(&values()).is_empty());
    }

    #[test]
    fn exact_claim_and_baggage_allowlists_are_independent_of_metadata_namespaces() {
        let policy = ContextExposurePolicy {
            metadata_prefixes: Vec::new(),
            claim_keys: vec!["role".to_owned()],
            baggage_keys: vec!["guest.visible".to_owned()],
        };
        policy.validate().unwrap();
        assert!(policy.metadata_pairs(&values()).is_empty());
        assert_eq!(
            policy.claim_pairs(&values()),
            vec![("role".to_owned(), "reader".to_owned())]
        );
        assert_eq!(
            policy.baggage_pairs(&values()),
            vec![("guest.visible".to_owned(), "public".to_owned())]
        );
    }

    #[test]
    fn malformed_or_oversized_lists_fail_before_policy_is_shared() {
        for entries in [
            vec![String::new()],
            vec!["x".repeat(MAXIMUM_KEY_BYTES + 1)],
            vec!["line\nbreak".to_owned()],
            vec!["same".to_owned(), "same".to_owned()],
            (0..=MAXIMUM_ENTRIES_PER_LIST)
                .map(|index| format!("key-{index}"))
                .collect(),
        ] {
            for dimension in 0..3 {
                let mut policy = ContextExposurePolicy::default();
                match dimension {
                    0 => policy.metadata_prefixes = entries.clone(),
                    1 => policy.claim_keys = entries.clone(),
                    _ => policy.baggage_keys = entries.clone(),
                }
                let error = policy.validate().unwrap_err();
                assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
                assert_eq!(error.message, "invalid context exposure policy");
            }
        }
        let valid = ContextExposurePolicy {
            metadata_prefixes: vec!["x".repeat(MAXIMUM_KEY_BYTES)],
            claim_keys: (0..MAXIMUM_ENTRIES_PER_LIST)
                .map(|index| format!("key-{index}"))
                .collect(),
            baggage_keys: Vec::new(),
        };
        valid.validate().unwrap();
    }
}
