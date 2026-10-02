//! Producer-owned, versioned operator observations. Never an execution receipt.
//!
//! Invocation/browser adapters deliberately omit this detail. Management may
//! project only the closed vocabulary and finite numeric fields below; names,
//! messages, paths and payloads are never part of this contract.

use crate::{ErrorDetail, Metadata, PlatformError};

/// Fixed node-owned projection sink. Observations never grant authority or
/// certify provider completion. Retention belongs to the existing journal.
pub trait ActivationDiagnosticSink: Send + Sync {
    fn record(
        &self,
        tenant: &crate::TenantId,
        activation: &crate::ActivationId,
        diagnostic: ActivationDiagnostic,
    );
}

macro_rules! vocabulary {
    ($name:ident { $($variant:ident = $number:literal),+ $(,)? }) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        #[repr(u32)]
        pub enum $name { $($variant = $number),+ }
        impl $name {
            #[must_use]
            pub fn from_number(value: u32) -> Option<Self> {
                match value { $($number => Some(Self::$variant),)+ _ => None }
            }
        }
    };
}

vocabulary!(DiagnosticStage {
    Admission = 1, Queue = 2, Preparation = 3, Binding = 4,
    Execution = 5, Provider = 6, Cleanup = 7, OutputValidation = 8
});
vocabulary!(DiagnosticReason {
    SignatureAllocationLimit = 1, ValueAllocationLimit = 2,
    UnsupportedComponentSurface = 3, UnsupportedEngineProfile = 4,
    ProviderAbsent = 5, BindingAbsent = 6, AdmissionDenied = 7,
    GrantDenied = 8, QueuePressure = 9, GuestMemoryExhausted = 10,
    GuestFuelExhausted = 11, GuestResourceExhausted = 12,
    ProviderTimeout = 13, DeadlineExceeded = 14, Cancelled = 15, HttpResponseRejected = 16
});
vocabulary!(DiagnosticProfile {
    WasmtimeServiceValuesV1 = 1, WasmtimeBufferedWebValuesV1 = 2
});

/// Unknown measurements stay absent. A reason never asserts effect completion
/// or resource retirement. Exact profile identity is a digest, never a label
/// supplied by a guest or tenant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationDiagnostic {
    pub stage: DiagnosticStage,
    pub reason: DiagnosticReason,
    pub profile: Option<DiagnosticProfile>,
    pub profile_digest: Option<[u8; 32]>,
    pub configured_bound: Option<u64>,
    pub calculated_requirement: Option<u64>,
    pub fixed_bytes: Option<u64>,
    pub lifting_fuel: Option<u64>,
    pub lift_multiplier: Option<u64>,
}

impl ActivationDiagnostic {
    pub const VERSION: u32 = 1;
    pub const DETAIL_KIND: &'static str = "activation.diagnostic.v1";

    #[must_use]
    pub const fn new(stage: DiagnosticStage, reason: DiagnosticReason) -> Self {
        Self {
            stage,
            reason,
            profile: None,
            profile_digest: None,
            configured_bound: None,
            calculated_requirement: None,
            fixed_bytes: None,
            lifting_fuel: None,
            lift_multiplier: None,
        }
    }

    #[must_use]
    pub fn detail(&self) -> ErrorDetail {
        let mut fields = Metadata::from([
            ("stage".into(), (self.stage as u32).to_string()),
            ("reason".into(), (self.reason as u32).to_string()),
        ]);
        for (key, value) in [
            ("profile", self.profile.map(|value| u64::from(value as u32))),
            ("configured_bound", self.configured_bound),
            ("calculated_requirement", self.calculated_requirement),
            ("fixed_bytes", self.fixed_bytes),
            ("lifting_fuel", self.lifting_fuel),
            ("lift_multiplier", self.lift_multiplier),
        ] {
            if let Some(value) = value {
                fields.insert(key.into(), value.to_string());
            }
        }
        if let Some(digest) = self.profile_digest {
            use std::fmt::Write as _;
            let mut value = String::with_capacity(64);
            for byte in digest {
                let _ = write!(value, "{byte:02x}");
            }
            fields.insert("profile_digest".into(), value);
        }
        ErrorDetail {
            kind: Self::DETAIL_KIND.into(),
            fields,
        }
    }

    #[must_use]
    pub fn attach(self, mut error: PlatformError) -> PlatformError {
        // Preserve the original producer's more specific observation.
        if !error
            .details
            .iter()
            .any(|detail| detail.kind == Self::DETAIL_KIND)
        {
            error.details.push(self.detail());
        }
        error
    }

    /// Fail closed on unfamiliar fields, unknown enums, hostile atoms and
    /// oversized numbers. This is not a general diagnostic-string sanitizer.
    #[must_use]
    pub fn from_detail(detail: &ErrorDetail) -> Option<Self> {
        const KEYS: &[&str] = &[
            "stage",
            "reason",
            "profile",
            "profile_digest",
            "configured_bound",
            "calculated_requirement",
            "fixed_bytes",
            "lifting_fuel",
            "lift_multiplier",
        ];
        if detail.kind != Self::DETAIL_KIND
            || detail.fields.len() > KEYS.len()
            || detail
                .fields
                .keys()
                .any(|key| !KEYS.contains(&key.as_str()))
        {
            return None;
        }
        let number = |key| -> Option<Option<u64>> {
            detail.fields.get(key).map_or(Some(None), |value| {
                if value.is_empty()
                    || value.len() > 20
                    || !value.bytes().all(|byte| byte.is_ascii_digit())
                {
                    return None;
                }
                value.parse().ok().map(Some)
            })
        };
        let stage = DiagnosticStage::from_number(u32::try_from(number("stage")??).ok()?)?;
        let reason = DiagnosticReason::from_number(u32::try_from(number("reason")??).ok()?)?;
        let profile = number("profile")?
            .map(|value| DiagnosticProfile::from_number(u32::try_from(value).ok()?))
            .transpose_option()?;
        let profile_digest = detail
            .fields
            .get("profile_digest")
            .map(|value| {
                if value.len() != 64
                    || !value
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                {
                    return None;
                }
                let mut digest = [0; 32];
                for (index, byte) in digest.iter_mut().enumerate() {
                    *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).ok()?;
                }
                Some(digest)
            })
            .transpose_option()?;
        Some(Self {
            stage,
            reason,
            profile,
            profile_digest,
            configured_bound: number("configured_bound")?,
            calculated_requirement: number("calculated_requirement")?,
            fixed_bytes: number("fixed_bytes")?,
            lifting_fuel: number("lifting_fuel")?,
            lift_multiplier: number("lift_multiplier")?,
        })
    }

    #[must_use]
    pub fn from_error(error: &PlatformError) -> Option<Self> {
        error.details.iter().take(32).find_map(Self::from_detail)
    }
}

// Missing, valid-present and invalid-present are distinct validation states.
#[allow(clippy::option_option)]
trait OptionalTranspose<T> {
    fn transpose_option(self) -> Option<Option<T>>;
}
impl<T> OptionalTranspose<T> for Option<Option<T>> {
    fn transpose_option(self) -> Option<Option<T>> {
        self.map_or(Some(None), |value| value.map(Some))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn closed_projection_preserves_absence_and_maximum_unsigned_values() {
        let mut observation = ActivationDiagnostic::new(
            DiagnosticStage::Preparation,
            DiagnosticReason::SignatureAllocationLimit,
        );
        observation.configured_bound = Some(0);
        observation.calculated_requirement = Some(u64::MAX);
        observation.profile_digest = Some([0xff; 32]);
        assert_eq!(
            ActivationDiagnostic::from_detail(&observation.detail()),
            Some(observation)
        );
    }
    #[test]
    fn hostile_atoms_unknown_enums_and_oversized_values_never_project() {
        let safe = ActivationDiagnostic::new(
            DiagnosticStage::Preparation,
            DiagnosticReason::UnsupportedComponentSurface,
        )
        .detail();
        for (key, value) in [
            ("function", "secret\n/path"),
            ("reason", "999"),
            ("configured_bound", "18446744073709551616"),
            ("profile_digest", "private-component"),
        ] {
            let mut hostile = safe.clone();
            hostile.fields.insert(key.into(), value.into());
            assert!(ActivationDiagnostic::from_detail(&hostile).is_none());
        }
    }
}
