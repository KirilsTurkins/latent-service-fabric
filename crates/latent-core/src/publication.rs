//! Publication identifiers are distinct from executable and package digests.

use std::{fmt, str::FromStr};

/// Canonical scoped-publication identity. Parsing supplies no authorization.
///
/// ```compile_fail
/// use latent_core::{PublicationId, ReleaseDigest};
/// let component = ReleaseDigest(format!("sha256:{}", "0".repeat(64)));
/// let publication: PublicationId = component.into();
/// ```
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PublicationId(Box<str>);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicationIdParseError;

impl fmt::Display for PublicationIdParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("expected publication:sha256: followed by 64 lowercase hexadecimal digits")
    }
}
impl std::error::Error for PublicationIdParseError {}

impl PublicationId {
    pub const TEXT_BYTES: usize = 83;

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Canonical hexadecimal storage key; never an input filesystem path.
    #[must_use]
    pub fn hex(&self) -> &str {
        &self.0[19..]
    }

    #[must_use]
    pub fn into_string(self) -> String {
        self.0.into_string()
    }
}

impl FromStr for PublicationId {
    type Err = PublicationIdParseError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let hex = value
            .strip_prefix("publication:sha256:")
            .ok_or(PublicationIdParseError)?;
        if hex.len() != 64 || !hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
            return Err(PublicationIdParseError);
        }
        Ok(Self(value.into()))
    }
}

impl TryFrom<String> for PublicationId {
    type Error = PublicationIdParseError;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        // The new allocation is exactly bounded, irrespective of caller capacity.
        value.parse()
    }
}

impl fmt::Display for PublicationId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_round_trip_compacts_spare_capacity() {
        let mut text = String::with_capacity(1024 * 1024);
        text.push_str(&format!(
            "publication:sha256:{}",
            "0123456789abcdef".repeat(4)
        ));
        let id = PublicationId::try_from(text.clone()).unwrap();
        assert_eq!(id.as_str(), text);
        assert_eq!(id.hex(), "0123456789abcdef".repeat(4));
        assert_eq!(
            id.clone().into_string().capacity(),
            PublicationId::TEXT_BYTES
        );
        assert_eq!(id.to_string().parse::<PublicationId>().unwrap(), id);
    }

    #[test]
    fn other_domains_and_noncanonical_inputs_fail_without_echoing_input() {
        for text in [
            String::new(),
            format!("sha256:{}", "a".repeat(64)),
            format!("publication:sha256:{}", "A".repeat(64)),
            format!("publication:sha256:{}", "a".repeat(63)),
            format!("publication:sha256:{}", "a".repeat(65)),
            format!("publication:sha256:{}\n", "a".repeat(64)),
            format!("publication:sha256:{}g", "a".repeat(63)),
            format!("publication:sha256:{}é", "a".repeat(63)),
        ] {
            assert_eq!(text.parse::<PublicationId>(), Err(PublicationIdParseError));
        }
    }
}
