//! Closed guest failure classifications, without engine or guest diagnostics.

/// Non-sensitive classification of a trapped guest execution.
///
/// Runtime errors include host-import and component-model failures; this kind
/// does not establish their cause or authorize a retry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum GuestTrapKind {
    StackOverflow,
    MemoryOutOfBounds,
    HeapMisaligned,
    TableOutOfBounds,
    IndirectCallToNull,
    BadSignature,
    IntegerOverflow,
    IntegerDivisionByZero,
    BadConversionToInteger,
    UnreachableCode,
    AllocationTooLarge,
    GuestFault,
    RuntimeError,
}

impl GuestTrapKind {
    /// All currently accepted classifications. Unknown names stay unclassified.
    pub const ALL: &'static [Self] = &[
        Self::StackOverflow,
        Self::MemoryOutOfBounds,
        Self::HeapMisaligned,
        Self::TableOutOfBounds,
        Self::IndirectCallToNull,
        Self::BadSignature,
        Self::IntegerOverflow,
        Self::IntegerDivisionByZero,
        Self::BadConversionToInteger,
        Self::UnreachableCode,
        Self::AllocationTooLarge,
        Self::GuestFault,
        Self::RuntimeError,
    ];

    /// Maximum size of one classification token, independent of error text.
    pub const MAX_WIRE_NAME_BYTES: usize = 32;

    /// Returns a fixed token rather than any supplied error or metadata value.
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            Self::StackOverflow => "stack-overflow",
            Self::MemoryOutOfBounds => "memory-out-of-bounds",
            Self::HeapMisaligned => "heap-misaligned",
            Self::TableOutOfBounds => "table-out-of-bounds",
            Self::IndirectCallToNull => "indirect-call-to-null",
            Self::BadSignature => "bad-signature",
            Self::IntegerOverflow => "integer-overflow",
            Self::IntegerDivisionByZero => "integer-division-by-zero",
            Self::BadConversionToInteger => "bad-conversion-to-integer",
            Self::UnreachableCode => "unreachable-code",
            Self::AllocationTooLarge => "allocation-too-large",
            Self::GuestFault => "guest-fault",
            Self::RuntimeError => "runtime-error",
        }
    }

    /// Parses only an exact closed token, without trimming or coercion.
    #[must_use]
    pub fn from_wire_name(value: &str) -> Option<Self> {
        if value.len() > Self::MAX_WIRE_NAME_BYTES {
            return None;
        }
        Self::ALL
            .iter()
            .copied()
            .find(|kind| kind.wire_name() == value)
    }
}

#[cfg(test)]
mod tests {
    use super::GuestTrapKind;

    #[test]
    fn fixed_trap_kinds_round_trip_without_duplicate_tokens() {
        let mut names = std::collections::BTreeSet::new();
        for kind in GuestTrapKind::ALL {
            let name = kind.wire_name();
            assert!(name.len() <= GuestTrapKind::MAX_WIRE_NAME_BYTES);
            assert!(names.insert(name));
            assert_eq!(GuestTrapKind::from_wire_name(name), Some(*kind));
        }
        assert_eq!(names.len(), 13);
    }

    #[test]
    fn arbitrary_trap_text_is_not_a_classification() {
        for value in [
            "",
            "future-trap",
            "guest-trap",
            "RuntimeError",
            " runtime-error",
            "runtime-error ",
            "unreachable-code\n",
            "unreachable-code /private/request secret-token",
            "runt\u{0456}me-error",
        ] {
            assert_eq!(GuestTrapKind::from_wire_name(value), None);
        }
        assert_eq!(
            GuestTrapKind::from_wire_name(&"secret-token".repeat(128)),
            None
        );
    }
}
