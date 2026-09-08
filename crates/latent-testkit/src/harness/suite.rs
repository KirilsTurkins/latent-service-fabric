use std::sync::Arc;

use latent_activation::{
    ActivationEnvelope, ActivationIdSource, ActivationOutcome, ActivationRequest,
    ActivationRequestBuilder, ActivationRequestLimits,
};
use latent_core::{
    ActivationId, ActivationTerminalState, BoxFuture, Metadata, PlatformError, PlatformErrorCode,
};

use crate::{BackendHarness, ConformanceCase, ConformanceResult, ConformanceSuite};

/// Exact terminal comparisons; diagnostic strings and payloads are never copied
/// into failure diagnostics. Consumption is available from the real manager's
/// status/inventory ports rather than invented by this comparison.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExpectedOutcome {
    Success {
        output: Vec<u8>,
        media_type: String,
    },
    DeclaredError {
        code: String,
        payload: Vec<u8>,
        media_type: String,
    },
    PlatformFailure {
        code: PlatformErrorCode,
        terminal_state: ActivationTerminalState,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationCase {
    pub case: ConformanceCase,
    pub envelope: ActivationEnvelope,
    pub expected: ExpectedOutcome,
}

/// Up to eight tiny, explicit cases. Each input/output is at most 4 KiB;
/// retained activation context is at most 32 KiB per case. CPU requests cannot
/// exceed ten million fuel, memory 64 MiB, or relative wall time one second.
///
/// Run with a counting [`super::BorrowedBackendHarness`] and the driver's outer
/// watchdog. This suite does not implement a runtime's interruption mechanism
/// or a timing/scale benchmark, and never retries a failed case.
pub struct InvocationConformanceSuite {
    cases: Vec<InvocationCase>,
}

impl InvocationConformanceSuite {
    pub fn new(cases: Vec<InvocationCase>) -> Result<Self, PlatformError> {
        if cases.is_empty() || cases.capacity() > 8 {
            return Err(invalid());
        }
        let builder = ActivationRequestBuilder::new(
            ActivationRequestLimits {
                maximum_identifier_bytes: 512,
                maximum_context_bytes: 32 * 1024,
                maximum_input_bytes: 4 * 1024,
            },
            Arc::new(ExplicitIdentity),
        )?;
        let mut retained: Vec<InvocationCase> = Vec::with_capacity(cases.len());
        for mut fixture in cases {
            validate_case(&fixture.case)?;
            if retained
                .iter()
                .any(|other| other.case.id == fixture.case.id)
            {
                return Err(invalid());
            }
            validate_expected(&fixture.expected)?;
            let budget = &fixture.envelope.budget;
            if fixture.envelope.resolved_revision.is_some()
                || fixture.envelope.retry_attempt != 0
                || budget.cpu_fuel > 10_000_000
                || budget.memory_bytes > 64 * 1024 * 1024
                || budget.log_bytes > 64 * 1024
                || budget
                    .wall_time_limit_millis
                    .is_none_or(|millis| millis > 1_000)
            {
                return Err(invalid());
            }
            // Reuse production validation before retaining or cloning nested
            // metadata, claims, baggage, and unused payload/string capacities.
            fixture.envelope = builder.build(ActivationRequest::from_envelope(fixture.envelope))?;
            retained.push(fixture);
        }
        Ok(Self { cases: retained })
    }
}

impl ConformanceSuite for InvocationConformanceSuite {
    fn cases(&self) -> Vec<ConformanceCase> {
        self.cases
            .iter()
            .map(|fixture| fixture.case.clone())
            .collect()
    }

    fn run<'a>(
        &'a self,
        harness: &'a dyn BackendHarness,
        case: &'a ConformanceCase,
    ) -> BoxFuture<'a, ConformanceResult> {
        Box::pin(async move {
            let Some(fixture) = self.cases.iter().find(|fixture| fixture.case == *case) else {
                return ConformanceResult {
                    case: ConformanceCase {
                        id: "unknown-case".to_owned(),
                        description: "Unregistered conformance case".to_owned(),
                        tags: Vec::new(),
                    },
                    passed: false,
                    diagnostics: vec!["conformance case is not registered".to_owned()],
                    attributes: Metadata::new(),
                };
            };
            let observed = harness.invoke(fixture.envelope.clone()).await;
            let exhausted = matches!(&observed, ActivationOutcome::Failed { error, .. }
                if error.code == PlatformErrorCode::ResourceExhausted && error.message == "conformance-work-limit");
            let passed = !exhausted && matches_expected(&fixture.expected, &observed);
            ConformanceResult {
                case: fixture.case.clone(),
                passed,
                diagnostics: if passed {
                    Vec::new()
                } else {
                    vec![if exhausted {
                        "conformance work limit exceeded"
                    } else {
                        "activation outcome differs from expected contract"
                    }
                    .to_owned()]
                },
                attributes: Metadata::new(),
            }
        })
    }
}

fn matches_expected(expected: &ExpectedOutcome, observed: &ActivationOutcome) -> bool {
    match (expected, observed) {
        (ExpectedOutcome::Success { output, media_type }, ActivationOutcome::Succeeded(value)) => {
            value.output == *output && value.output_media_type == *media_type
        }
        (
            ExpectedOutcome::DeclaredError {
                code,
                payload,
                media_type,
            },
            ActivationOutcome::DeclaredError { error, .. },
        ) => error.code == *code && error.payload == *payload && error.media_type == *media_type,
        (
            ExpectedOutcome::PlatformFailure {
                code,
                terminal_state,
            },
            ActivationOutcome::Failed {
                terminal_state: observed_state,
                error,
                ..
            },
        ) => error.code == *code && observed_state == terminal_state,
        _ => false,
    }
}

fn validate_case(case: &ConformanceCase) -> Result<(), PlatformError> {
    if case.id.is_empty()
        || case.id.capacity() > 64
        || !case
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        || case.description.capacity() > 512
        || case.description.chars().any(char::is_control)
        || case.tags.capacity() > 8
        || case
            .tags
            .iter()
            .any(|tag| tag.capacity() > 64 || tag.chars().any(char::is_control))
    {
        return Err(invalid());
    }
    Ok(())
}

fn validate_expected(expected: &ExpectedOutcome) -> Result<(), PlatformError> {
    let (payload, media_type) = match expected {
        ExpectedOutcome::Success { output, media_type } => (output, media_type),
        ExpectedOutcome::DeclaredError {
            code,
            payload,
            media_type,
        } => {
            if code.is_empty() || code.capacity() > 512 || code.chars().any(char::is_control) {
                return Err(invalid());
            }
            (payload, media_type)
        }
        ExpectedOutcome::PlatformFailure { .. } => return Ok(()),
    };
    if payload.capacity() > 4096
        || media_type.is_empty()
        || media_type.capacity() > 512
        || media_type.chars().any(char::is_control)
    {
        return Err(invalid());
    }
    Ok(())
}

struct ExplicitIdentity;
impl ActivationIdSource for ExplicitIdentity {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        Err(invalid())
    }
}

fn invalid() -> PlatformError {
    super::error(
        PlatformErrorCode::InvalidArgument,
        "invalid-bounded-invocation-case",
    )
}
