//! Fixed public reasons, not mutation dispositions or arbitrary storage errors.
use latent_core::ErrorDetail;

pub(super) fn details(reason: &str) -> Vec<ErrorDetail> {
    // Keep failure evidence independent of outcome knowledge: these errors can
    // arise before dispatch, during a query, or after a catalog commit.
    if !matches!(
        reason,
        "audit-capacity"
            | "audit-critical-pending"
            | "audit-busy"
            | "audit-unavailable"
            | "audit-closed"
            | "audit-corrupt"
    ) {
        return Vec::new();
    }
    vec![ErrorDetail {
        kind: "audit-journal".into(),
        fields: [("reason".into(), reason.into())].into(),
    }]
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::PlatformErrorCode;

    #[test]
    fn known_reason_survives_without_claiming_mutation_disposition() {
        for reason in [
            "audit-capacity",
            "audit-critical-pending",
            "audit-busy",
            "audit-unavailable",
            "audit-closed",
            "audit-corrupt",
        ] {
            let value = details(reason);
            assert_eq!(value.len(), 1);
            assert_eq!(value[0].kind, "audit-journal");
            assert_eq!(value[0].fields.len(), 1);
            assert_eq!(value[0].fields["reason"], reason);
        }
        let value = super::super::capacity();
        assert_eq!(value.code, PlatformErrorCode::ResourceExhausted);
        assert!(!value.retryable);
        assert_eq!(value.details, details("audit-capacity"));
    }

    #[test]
    fn unrecognized_text_is_not_a_public_diagnostic() {
        for reason in ["audit-invalid", "/private/journal", "credential=secret", ""] {
            assert!(details(reason).is_empty());
        }
    }
}
