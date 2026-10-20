//! Default-off closed witnesses before HTTP erases provider refusal identity.
use latent_core::{PlatformError, PlatformErrorCode};
use std::{
    ffi::OsStr,
    io::Write,
    sync::atomic::{AtomicUsize, Ordering},
};

const ENVIRONMENT: &str = "LSF_JAVA_HTTP_REFUSAL_DIAGNOSTIC";
const PREFIX: &str = "LSF-JAVA-HTTP-REFUSAL-V1";
const MAX_RECORDS: usize = 16;
static RECORDS: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Copy)]
pub(in crate::broker) enum Stage {
    TypedHttpConversion,
    PoolActiveDial,
}
impl Stage {
    const fn name(self) -> &'static str {
        match self {
            Self::TypedHttpConversion => "typed-http-conversion",
            Self::PoolActiveDial => "pool-active-dial",
        }
    }
}
fn category(error: &PlatformError) -> Option<&'static str> {
    match error.code {
        PlatformErrorCode::ResourceExhausted => Some("resource-exhausted"),
        PlatformErrorCode::AdmissionRejected => Some("admission-rejected"),
        _ => None,
    }
}
fn reason(error: &PlatformError) -> &'static str {
    match error.message.as_str() {
        "capability-busy" => "busy",
        "capability-capacity" => "capacity",
        _ => "unclassified",
    }
}
fn record(
    enabled: bool,
    counter: &AtomicUsize,
    writer: &mut impl Write,
    stage: Stage,
    error: &PlatformError,
) {
    let Some(category) = category(error).filter(|_| enabled) else {
        return;
    };
    if counter
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |seen| {
            if seen < MAX_RECORDS {
                Some(seen + 1)
            } else {
                None
            }
        })
        .is_err()
    {
        return;
    }
    // Neither arbitrary error text nor request/resource/credential data is
    // formatted. A closed-pipe failure cannot replace the original outcome.
    let _ = writeln!(
        writer,
        "{PREFIX} {} {category} {}",
        stage.name(),
        reason(error)
    );
}
pub(in crate::broker) fn observe(stage: Stage, error: &PlatformError) {
    if category(error).is_some()
        && std::env::var_os(ENVIRONMENT).as_deref() == Some(OsStr::new("1"))
    {
        record(true, &RECORDS, &mut std::io::stderr(), stage, error);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn failure(code: PlatformErrorCode, message: &str) -> PlatformError {
        PlatformError {
            code,
            message: message.into(),
            retryable: false,
            details: Vec::new(),
        }
    }
    #[test]
    fn exact_busy_capacity_and_active_dial_are_closed_static_witnesses() {
        let mut output = Vec::new();
        let counter = AtomicUsize::new(0);
        for (stage, code, message) in [
            (
                Stage::PoolActiveDial,
                PlatformErrorCode::ResourceExhausted,
                "capability-busy",
            ),
            (
                Stage::TypedHttpConversion,
                PlatformErrorCode::ResourceExhausted,
                "capability-capacity",
            ),
            (
                Stage::TypedHttpConversion,
                PlatformErrorCode::AdmissionRejected,
                "untrusted-private-input",
            ),
        ] {
            record(true, &counter, &mut output, stage, &failure(code, message));
        }
        assert_eq!(output, b"LSF-JAVA-HTTP-REFUSAL-V1 pool-active-dial resource-exhausted busy\nLSF-JAVA-HTTP-REFUSAL-V1 typed-http-conversion resource-exhausted capacity\nLSF-JAVA-HTTP-REFUSAL-V1 typed-http-conversion admission-rejected unclassified\n");
    }
    #[test]
    fn disabled_unrelated_and_overbound_observations_cannot_leak_or_expand_capture() {
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        let error = failure(
            PlatformErrorCode::ResourceExhausted,
            "private-/path/token\nFORGED",
        );
        record(
            false,
            &counter,
            &mut output,
            Stage::TypedHttpConversion,
            &error,
        );
        record(
            true,
            &counter,
            &mut output,
            Stage::PoolActiveDial,
            &failure(PlatformErrorCode::PermissionDenied, "capability-busy"),
        );
        assert!(output.is_empty());
        assert_eq!(counter.load(Ordering::Relaxed), 0);
        for _ in 0..100 {
            record(
                true,
                &counter,
                &mut output,
                Stage::TypedHttpConversion,
                &error,
            );
        }
        assert_eq!(counter.load(Ordering::Relaxed), MAX_RECORDS);
        assert_eq!(
            output
                .split(|b| *b == b'\n')
                .filter(|row| !row.is_empty())
                .count(),
            MAX_RECORDS
        );
        assert!(output.len() <= MAX_RECORDS * 128);
        assert!(!String::from_utf8(output).unwrap().contains("private"));
    }
    #[test]
    fn writer_failure_preserves_the_original_typed_error_and_borrowed_source() {
        struct Broken;
        impl Write for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let error = failure(PlatformErrorCode::ResourceExhausted, "capability-busy");
        let original = error.clone();
        record(
            true,
            &AtomicUsize::new(0),
            &mut Broken,
            Stage::PoolActiveDial,
            &error,
        );
        assert_eq!(error, original);
        assert_eq!(
            super::super::HttpError::from(error),
            super::super::HttpError::BudgetExhausted
        );
    }
}
