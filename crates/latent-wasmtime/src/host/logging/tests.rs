use super::*;
use latent_core::{
    ClockSample, EffectiveActivationBudget, InvocationPrincipal, PrincipalKind, ResourceBudget,
};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Weak;

fn context(id: &str) -> ActivationHostContext {
    ActivationHostContext::new(
        ActivationId(id.to_owned()),
        ActivationId("root".to_owned()),
        None,
        InvocationPrincipal {
            subject: "private-principal".to_owned(),
            kind: PrincipalKind::User,
            tenant: None,
            service: None,
            claims: Metadata::from([("secret".to_owned(), "never-inject".to_owned())]),
        },
        "trace-id".to_owned(),
        "span-id".to_owned(),
        1,
        Metadata::from([("baggage-secret".to_owned(), "never-inject".to_owned())]),
        None,
        Metadata::from([("metadata-secret".to_owned(), "never-inject".to_owned())]),
    )
}

fn budget(bytes: u64) -> ActivationBudget {
    let grant = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 64 * 1024,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: bytes,
        effect_count: 0,
    };
    ActivationBudget::new(
        EffectiveActivationBudget::admit_at(
            &grant,
            &grant,
            &grant,
            None,
            ClockSample::new(1000, Instant::now()),
        )
        .unwrap(),
    )
}

fn field(name: &str, value: &str) -> log::Field {
    log::Field {
        name: name.to_owned(),
        value: value.to_owned(),
    }
}

fn expected(context: &ActivationHostContext, message: &str, fields: Metadata) -> CapturedLog {
    let mut fields = fields;
    fields.insert(
        "latent.activation_id".to_owned(),
        context.activation_id.0.clone(),
    );
    fields.insert("latent.trace_id".to_owned(), context.trace_id.clone());
    fields.insert("latent.span_id".to_owned(), context.span_id.clone());
    CapturedLog {
        activation_id: context.activation_id.clone(),
        level: "info".to_owned(),
        message: message.to_owned(),
        fields,
    }
}

#[test]
fn exact_canonical_json_bytes_include_utf8_escaping_fields_and_trusted_correlation() {
    let context = context("act-\"\u{2603}");
    let message = "quoted \" line\n";
    let record = expected(
        &context,
        message,
        Metadata::from([("value".to_owned(), "\u{0}\u{2603}".to_owned())]),
    );
    let encoded = serde_json::to_vec(&record).unwrap();
    let accounting = budget(encoded.len() as u64);
    let sink = BoundedLogSink::new(3, 4096);
    let mut logs = InvocationLogBuffer::new(3, 4096, accounting.clone(), sink.clone());
    assert!(logs
        .write(
            &context,
            log::Level::Info,
            message.to_owned(),
            &[field("value", "\u{0}\u{2603}")]
        )
        .unwrap());
    assert_eq!(sink.snapshot(), vec![record]);
    assert_eq!(logs.bytes(), encoded.len() as u64);
    assert_eq!(
        accounting.snapshot_at(Instant::now()).log_bytes,
        encoded.len() as u64
    );
    assert_eq!(accounting.remaining_at(Instant::now()).log_bytes, 0);
    assert_eq!(sink.lock_state().bytes, encoded.len());
    assert!(!String::from_utf8(encoded).unwrap().contains("never-inject"));
    assert!(matches!(
        logs.write(
            &context,
            log::Level::Info,
            message.to_owned(),
            &[field("value", "\u{0}\u{2603}")]
        ),
        Err(log::LogError::BudgetExhausted)
    ));
    assert_eq!(accounting.outstanding_reservations(), 0);
}

#[test]
fn one_byte_under_grant_or_local_limit_rejects_without_capture_or_consumption() {
    let context = context("act");
    let size = serde_json::to_vec(&expected(&context, "hello", Metadata::new()))
        .unwrap()
        .len();
    for (granted, local) in [(size - 1, size), (size, size - 1)] {
        let accounting = budget(granted as u64);
        let sink = BoundedLogSink::new(3, 4096);
        let mut logs = InvocationLogBuffer::new(3, local, accounting.clone(), sink.clone());
        assert!(matches!(
            logs.write(&context, log::Level::Info, "hello".to_owned(), &[]),
            Err(log::LogError::BudgetExhausted)
        ));
        assert!(sink.snapshot().is_empty());
        assert_eq!(logs.bytes(), 0);
        assert_eq!(accounting.snapshot_at(Instant::now()).log_bytes, 0);
        assert_eq!(accounting.outstanding_reservations(), 0);
    }
}

struct InspectingSink {
    capture: Mutex<Weak<Mutex<LogSinkState>>>,
    budget: ActivationBudget,
    unavailable: AtomicBool,
    attempts: AtomicUsize,
}

impl StructuredLogSink for InspectingSink {
    fn try_emit(&self, entry: &CapturedLog, encoded: &[u8]) -> Result<(), LogSinkError> {
        self.attempts.fetch_add(1, Ordering::Relaxed);
        assert_eq!(serde_json::to_vec(entry).unwrap(), encoded);
        let capture = self.capture.lock().unwrap().upgrade().unwrap();
        assert!(
            capture.try_lock().is_ok(),
            "callback must not hold the capture mutex"
        );
        assert_eq!(self.budget.outstanding_reservations(), 1);
        assert_eq!(self.budget.snapshot_at(Instant::now()).log_bytes, 0);
        assert_eq!(
            self.budget.remaining_at(Instant::now()).log_bytes,
            self.budget.granted().log_bytes - encoded.len() as u64
        );
        if self.unavailable.load(Ordering::Relaxed) {
            Err(LogSinkError::Unavailable)
        } else {
            Ok(())
        }
    }
}

#[test]
fn target_runs_without_capture_lock_and_rejection_refunds_before_retry() {
    let context = context("act");
    let accounting = budget(4096);
    let target = Arc::new(InspectingSink {
        capture: Mutex::new(Weak::new()),
        budget: accounting.clone(),
        unavailable: AtomicBool::new(true),
        attempts: AtomicUsize::new(0),
    });
    let sink = BoundedLogSink::with_target(3, 4096, Some(target.clone()));
    *target.capture.lock().unwrap() = Arc::downgrade(&sink.state);
    let mut logs = InvocationLogBuffer::new(3, 4096, accounting.clone(), sink.clone());
    assert!(matches!(
        logs.write(&context, log::Level::Info, "hello".to_owned(), &[]),
        Err(log::LogError::Unavailable)
    ));
    assert_eq!(logs.bytes(), 0);
    assert_eq!(accounting.remaining_at(Instant::now()).log_bytes, 4096);
    assert_eq!(accounting.outstanding_reservations(), 0);
    assert!(sink.snapshot().is_empty());
    target.unavailable.store(false, Ordering::Relaxed);
    assert!(logs
        .write(&context, log::Level::Info, "hello".to_owned(), &[])
        .unwrap());
    assert_eq!(target.attempts.load(Ordering::Relaxed), 2);
    assert_eq!(sink.snapshot().len(), 1);
    assert_eq!(accounting.outstanding_reservations(), 0);
    assert_eq!(
        accounting.snapshot_at(Instant::now()).log_bytes,
        logs.bytes()
    );
}

#[test]
fn invalid_and_reserved_guest_fields_are_rejected_without_budget_changes() {
    let context = context("act");
    let accounting = budget(4096);
    let sink = BoundedLogSink::new(3, 4096);
    let mut logs = InvocationLogBuffer::new(3, 4096, accounting.clone(), sink.clone());
    for fields in [
        vec![field("", "empty")],
        vec![field("bad name", "space")],
        vec![field("latent.activation_id", "spoof")],
        vec![field("LaTeNt.Trace_Id", "spoof")],
        vec![field("x", "first"), field("x", "duplicate")],
        vec![field(&"x".repeat(65), "too-long")],
        vec![field("x", &"x".repeat(257))],
        (0..17)
            .map(|index| field(&format!("f{index}"), "x"))
            .collect(),
    ] {
        assert!(matches!(
            logs.write(&context, log::Level::Info, "hello".to_owned(), &fields),
            Err(log::LogError::InvalidField(_))
        ));
    }
    assert!(matches!(
        logs.write(&context, log::Level::Info, "x".repeat(257), &[]),
        Err(log::LogError::InvalidField(_))
    ));
    assert_eq!(logs.bytes(), 0);
    assert_eq!(accounting.remaining_at(Instant::now()).log_bytes, 4096);
    assert_eq!(accounting.outstanding_reservations(), 0);
    assert!(sink.snapshot().is_empty());
}

#[test]
fn capture_eviction_and_clear_do_not_refund_accepted_logs_or_cross_activation_counters() {
    let first_context = context("first");
    let second_context = context("second");
    let first_budget = budget(4096);
    let second_budget = budget(4096);
    let sink = BoundedLogSink::new(1, 4096);
    let mut first = InvocationLogBuffer::new(2, 4096, first_budget.clone(), sink.clone());
    let mut second = InvocationLogBuffer::new(2, 4096, second_budget.clone(), sink.clone());
    assert!(first
        .write(&first_context, log::Level::Info, "first".to_owned(), &[])
        .unwrap());
    let first_bytes = first.bytes();
    assert!(second
        .write(&second_context, log::Level::Info, "second".to_owned(), &[])
        .unwrap());
    assert!(sink.snapshot_for(&first_context.activation_id).is_empty());
    assert_eq!(sink.snapshot_for(&second_context.activation_id).len(), 1);
    sink.clear();
    assert_eq!(
        first_budget.snapshot_at(Instant::now()).log_bytes,
        first_bytes
    );
    assert_eq!(
        second_budget.snapshot_at(Instant::now()).log_bytes,
        second.bytes()
    );
    assert_eq!(first.bytes(), first_bytes);
    assert!(sink.snapshot().is_empty());
}

#[test]
fn entry_ceiling_and_unavailable_capture_never_consume_an_unaccepted_record() {
    let context = context("act");
    let accounting = budget(4096);
    let sink = BoundedLogSink::new(2, 4096);
    let mut logs = InvocationLogBuffer::new(1, 4096, accounting.clone(), sink.clone());
    assert!(logs
        .write(&context, log::Level::Info, "first".to_owned(), &[])
        .unwrap());
    let used = logs.bytes();
    assert!(matches!(
        logs.write(&context, log::Level::Info, "second".to_owned(), &[]),
        Err(log::LogError::BudgetExhausted)
    ));
    assert_eq!(accounting.snapshot_at(Instant::now()).log_bytes, used);
    let mut unavailable =
        InvocationLogBuffer::new(1, 4096, accounting.clone(), BoundedLogSink::new(0, 0));
    assert!(matches!(
        unavailable.write(&context, log::Level::Info, "third".to_owned(), &[]),
        Err(log::LogError::Unavailable)
    ));
    assert_eq!(accounting.snapshot_at(Instant::now()).log_bytes, used);
    assert_eq!(accounting.outstanding_reservations(), 0);
}
