//! Canonical SHA-256 identities for immutable packages and their artifact blobs.
//!
//! Parsing checks the textual representation only. Callers must independently
//! verify the identity against the exact bytes at their trust boundary.
//! The existing component `ReleaseDigest` and capability `BlobDigest` retain
//! their separate meanings and APIs.

use std::fmt;
use std::str::FromStr;

/// A digest is not `sha256:` followed by exactly 64 lowercase ASCII hex digits.
///
/// Diagnostics deliberately omit the rejected input.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DigestParseError;

impl fmt::Display for DigestParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("expected sha256: followed by 64 lowercase hexadecimal digits")
    }
}

impl std::error::Error for DigestParseError {}

fn validate(value: &str) -> Result<(), DigestParseError> {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return Err(DigestParseError);
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    {
        return Err(DigestParseError);
    }
    Ok(())
}

macro_rules! artifact_digest {
    ($(#[$meta:meta])* $name:ident) => {
        $(#[$meta])*
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            /// Borrows the validated canonical digest text.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }

            /// Returns the owned canonical digest text.
            #[must_use]
            pub fn into_string(self) -> String {
                self.0
            }
        }

        impl TryFrom<String> for $name {
            type Error = DigestParseError;

            fn try_from(value: String) -> Result<Self, Self::Error> {
                validate(&value)?;
                Ok(Self(value))
            }
        }

        impl FromStr for $name {
            type Err = DigestParseError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                validate(value)?;
                Ok(Self(value.to_owned()))
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                fmt::Display::fmt(&self.0, formatter)
            }
        }
    };
}

artifact_digest! {
    /// SHA-256 identity of the exact immutable OCI package manifest bytes.
    ///
    /// This identity is distinct from the component-only `ReleaseDigest` and
    /// the identities of individual artifact blobs. Parsing does not verify
    /// bytes, publisher trust, or package completeness.
    ///
    /// Component identity cannot implicitly become package identity:
    ///
    /// ```compile_fail
    /// use latent_core::{PackageDigest, ReleaseDigest};
    /// let component = ReleaseDigest(format!("sha256:{}", "0".repeat(64)));
    /// let package: PackageDigest = component.into();
    /// ```
    PackageDigest
}

artifact_digest! {
    /// SHA-256 identity of exact artifact bytes, such as a package config or layer.
    ///
    /// This is not the existing guest blob-capability `BlobDigest` identifier.
    /// Artifact blob and package identities are not interchangeable:
    ///
    /// ```compile_fail
    /// use latent_core::{ArtifactBlobDigest, PackageDigest};
    /// let blob: ArtifactBlobDigest = format!("sha256:{}", "0".repeat(64)).parse().unwrap();
    /// let package: PackageDigest = blob.into();
    /// ```
    ArtifactBlobDigest
}

#[cfg(test)]
mod tests {
    use super::{ArtifactBlobDigest, DigestParseError, PackageDigest};
    use std::collections::{BTreeSet, HashSet};

    #[test]
    fn canonical_sha256_text_round_trips_in_each_identity_domain() {
        for hex in ["0".repeat(64), "f".repeat(64), "0123456789abcdef".repeat(4)] {
            let text = format!("sha256:{hex}");
            let package: PackageDigest = text.parse().unwrap();
            let blob: ArtifactBlobDigest = text.parse().unwrap();

            assert_eq!(PackageDigest::try_from(text.clone()).unwrap(), package);
            assert_eq!(ArtifactBlobDigest::try_from(text.clone()).unwrap(), blob);
            assert_eq!(package.as_str(), text);
            assert_eq!(blob.as_str(), text);
            assert_eq!(package.to_string(), text);
            assert_eq!(blob.to_string(), text);
            assert_eq!(package.into_string(), text);
            assert_eq!(blob.into_string(), text);
        }
    }

    #[test]
    fn noncanonical_and_malformed_digests_are_rejected_without_normalization() {
        let hex = "a".repeat(64);
        let invalid = [
            String::new(),
            hex.clone(),
            "sha256:".to_owned(),
            format!("sha256:{}", "a".repeat(63)),
            format!("sha256:{}", "a".repeat(65)),
            format!("sha256:{}", "A".repeat(64)),
            format!("sha256:{}g", "a".repeat(63)),
            format!("sha256:{}é", "a".repeat(63)),
            format!("SHA256:{hex}"),
            format!("sha512:{hex}"),
            format!("sha256::{hex}"),
            format!(" sha256:{hex}"),
            format!("sha256:{hex} "),
            format!("sha256:{hex}\n"),
            format!("sha256:{}\0", "a".repeat(63)),
            format!("sha256:{}\t", "a".repeat(63)),
        ];

        for text in invalid {
            assert_eq!(text.parse::<PackageDigest>(), Err(DigestParseError));
            assert_eq!(text.parse::<ArtifactBlobDigest>(), Err(DigestParseError));
            assert_eq!(PackageDigest::try_from(text.clone()), Err(DigestParseError));
            assert_eq!(ArtifactBlobDigest::try_from(text), Err(DigestParseError));
        }
    }

    #[test]
    fn validated_identities_support_deterministic_keys_and_deduplication() {
        let first = format!("sha256:{}", "0".repeat(64));
        let last = format!("sha256:{}", "f".repeat(64));
        let package: PackageDigest = first.parse().unwrap();
        let blob: ArtifactBlobDigest = first.parse().unwrap();

        let packages = BTreeSet::from([last.parse().unwrap(), package.clone(), package]);
        let blobs = HashSet::from([blob.clone(), blob, last.parse().unwrap()]);

        assert_eq!(packages.len(), 2);
        assert_eq!(packages.first().unwrap().as_str(), first);
        assert_eq!(packages.last().unwrap().as_str(), last);
        assert_eq!(blobs.len(), 2);
    }
}
