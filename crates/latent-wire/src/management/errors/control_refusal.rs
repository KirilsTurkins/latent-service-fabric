//! Opt-in host witnesses; neither error details nor execution authority.
use std::{
    ffi::OsStr,
    io::Write,
    sync::atomic::{AtomicUsize, Ordering},
};

use super::{platform_status, ManagementLimits, PlatformError, PlatformErrorCode, Status};

const ENVIRONMENT: &str = "LSF_JAVA_CONTROL_REFUSAL_DIAGNOSTIC";
const PREFIX: &str = "LSF-JAVA-CONTROL-REFUSAL-V1";
const MAX_RECORDS: usize = 16;
static RECORDS: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Copy)]
pub(crate) enum Stage {
    TriggerRequest,
    TriggerPreparation,
    TriggerAuditBegin,
    TriggerCommit,
    AuditQueryReservation,
    AuditQueryCompletion,
}

impl Stage {
    const fn name(self) -> &'static str {
        match self {
            Self::TriggerRequest => "trigger-request",
            Self::TriggerPreparation => "trigger-preparation",
            Self::TriggerAuditBegin => "trigger-audit-begin",
            Self::TriggerCommit => "trigger-commit",
            Self::AuditQueryReservation => "audit-query-reservation",
            Self::AuditQueryCompletion => "audit-query-completion",
        }
    }
}

fn reason(error: &PlatformError) -> &'static str {
    match error.message.as_str() {
        "rollout-capacity" => "exclusive-rollout-work",
        "deployment-operation-capacity" => "http-budget",
        "http-trigger-capacity" => "http-table",
        "audit-critical-pending" => "audit-critical-pending",
        "audit-capacity" => "audit-capacity",
        "audit-busy" => "audit-busy",
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
    if !enabled || error.code != PlatformErrorCode::ResourceExhausted {
        return;
    }
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
    // Only fixed literals reach this existing host stderr pipe. I/O failure
    // must never replace or change the original management result.
    let _ = writeln!(writer, "{PREFIX} {} {}", stage.name(), reason(error));
}

pub(crate) fn refusal_status(
    error: PlatformError,
    limits: &ManagementLimits,
    stage: Stage,
) -> Status {
    if error.code == PlatformErrorCode::ResourceExhausted
        && std::env::var_os(ENVIRONMENT).as_deref() == Some(OsStr::new("1"))
    {
        record(true, &RECORDS, &mut std::io::stderr(), stage, &error);
    }
    platform_status(error, limits)
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
    fn only_resource_refusals_consume_the_closed_record_allowance() {
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        for _ in 0..100 {
            for code in [PlatformErrorCode::PermissionDenied, PlatformErrorCode::NotFound] {
                record(
                    true,
                    &counter,
                    &mut output,
                    Stage::TriggerRequest,
                    &failure(code, "audit-busy"),
                );
            }
        }
        assert!(output.is_empty());
        assert_eq!(counter.load(Ordering::Relaxed), 0);
        record(
            true,
            &counter,
            &mut output,
            Stage::TriggerPreparation,
            &failure(PlatformErrorCode::ResourceExhausted, "rollout-capacity"),
        );
        assert_eq!(
            output,
            b"LSF-JAVA-CONTROL-REFUSAL-V1 trigger-preparation exclusive-rollout-work\n"
        );
    }

    #[test]
    fn marker_vocabulary_and_process_capture_are_bounded() {
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        let error = failure(
            PlatformErrorCode::ResourceExhausted,
            "PRIVATE-/path/token\nLSF-JAVA-CONTROL-REFUSAL-V1 fake fake",
        );
        for _ in 0..100 {
            record(true, &counter, &mut output, Stage::TriggerAuditBegin, &error);
        }
        assert_eq!(counter.load(Ordering::Relaxed), MAX_RECORDS);
        assert_eq!(
            output
                .split(|byte| *byte == b'\n')
                .filter(|row| !row.is_empty())
                .count(),
            MAX_RECORDS
        );
        assert!(!String::from_utf8(output.clone()).unwrap().contains("PRIVATE"));
        assert!(output.len() <= MAX_RECORDS * 128);
        for stage in [
            Stage::TriggerRequest,
            Stage::TriggerPreparation,
            Stage::TriggerAuditBegin,
            Stage::TriggerCommit,
            Stage::AuditQueryReservation,
            Stage::AuditQueryCompletion,
        ] {
            for message in [
                "rollout-capacity",
                "deployment-operation-capacity",
                "http-trigger-capacity",
                "audit-critical-pending",
                "audit-capacity",
                "audit-busy",
                "unknown",
            ] {
                let mut row = Vec::new();
                record(
                    true,
                    &AtomicUsize::new(0),
                    &mut row,
                    stage,
                    &failure(PlatformErrorCode::ResourceExhausted, message),
                );
                assert!(row.len() <= 128);
                assert_eq!(String::from_utf8(row).unwrap().split_whitespace().count(), 3);
            }
        }
    }

    #[test]
    fn disabled_capture_and_writer_failure_preserve_the_original_error() {
        struct Broken;
        impl Write for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let error = failure(PlatformErrorCode::ResourceExhausted, "audit-capacity");
        let original = error.clone();
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        record(false, &counter, &mut output, Stage::TriggerCommit, &error);
        assert!(output.is_empty());
        assert_eq!(counter.load(Ordering::Relaxed), 0);
        record(true, &counter, &mut Broken, Stage::TriggerCommit, &error);
        assert_eq!(error, original);
        let limits = ManagementLimits::default();
        let before = platform_status(original, &limits);
        let after = refusal_status(error, &limits, Stage::TriggerCommit);
        assert_eq!(before.code(), after.code());
        assert_eq!(before.message(), after.message());
        assert_eq!(before.details(), after.details());
    }
}
