#[derive(Debug, Clone, Copy)]
struct FixedClock(u64);

impl Clock for FixedClock {
    fn now_unix_millis(&self) -> u64 {
        self.0
    }
}

#[derive(Debug, Default)]
struct FakeState {
    owners: HashMap<ActivationId, Option<TenantId>>,
    statuses: HashMap<ActivationId, ActivationStatus>,
    invocations: Vec<InvocationCommand>,
    cancellations: Vec<CancellationCommand>,
    tokens: HashMap<ActivationId, InvocationCancellation>,
}

#[derive(Debug)]
struct FakeRuntime {
    state: Mutex<FakeState>,
    outcome: Mutex<ActivationOutcome>,
    cancellation_disposition: Mutex<CancelDisposition>,
    sequence: AtomicU64,
    pending: AtomicBool,
    released: AtomicBool,
    registered: Notify,
    release: Notify,
}

impl FakeRuntime {
    fn new(outcome: ActivationOutcome) -> Self {
        Self {
            state: Mutex::new(FakeState::default()),
            outcome: Mutex::new(outcome),
            cancellation_disposition: Mutex::new(CancelDisposition::Accepted),
            sequence: AtomicU64::new(0),
            pending: AtomicBool::new(false),
            released: AtomicBool::new(true),
            registered: Notify::new(),
            release: Notify::new(),
        }
    }

    fn set_pending(&self, pending: bool) {
        self.released.store(!pending, Ordering::Release);
        self.pending.store(pending, Ordering::Release);
    }

    fn set_cancellation_disposition(&self, disposition: CancelDisposition) {
        *lock(&self.cancellation_disposition) = disposition;
    }

    fn assigned_activation_id(&self, command: &InvocationCommand) -> ActivationId {
        command
            .request
            .requested_activation_id
            .clone()
            .unwrap_or_else(|| {
                let sequence = self.sequence.fetch_add(1, Ordering::Relaxed);
                ActivationId(format!("activation-runtime-{sequence:04}"))
            })
    }

    fn receipt(&self, activation_id: ActivationId) -> InvocationReceipt {
        InvocationReceipt {
            activation_id,
            revision_id: RevisionId("revision-1".to_owned()),
            release_digest: ReleaseDigest(
                "sha256:1111111111111111111111111111111111111111111111111111111111111111"
                    .to_owned(),
            ),
            route_generation: RouteGeneration(42),
        }
    }

    fn publish_terminal(&self, response: &InvocationResponse) {
        let (terminal_state, terminal_outcome, consumption) = match &response.outcome {
            ActivationOutcome::Succeeded(success) => (
                ActivationTerminalState::Completed,
                RetainedActivationOutcome::Succeeded(ActivationSuccessSummary::from(success)),
                success.consumption.clone(),
            ),
            ActivationOutcome::DeclaredError { error, consumption } => (
                ActivationTerminalState::Completed,
                RetainedActivationOutcome::DeclaredError(error.clone()),
                consumption.clone(),
            ),
            ActivationOutcome::Failed {
                terminal_state,
                error,
                consumption,
            } => (
                *terminal_state,
                RetainedActivationOutcome::PlatformFailure(error.clone()),
                consumption.clone(),
            ),
        };
        lock(&self.state).statuses.insert(
            response.receipt.activation_id.clone(),
            ActivationStatus {
                activation_id: response.receipt.activation_id.clone(),
                phase: ActivationPhase::Running,
                terminal_state: Some(terminal_state),
                terminal_outcome: Some(terminal_outcome),
                final_consumption: Some(consumption),
                last_updated_unix_millis: 1_001,
                terminal_at_unix_millis: Some(1_001),
                metadata: Metadata::from([("retained".to_owned(), "true".to_owned())]),
            },
        );
    }

    async fn wait_until_registered(&self, activation_id: &ActivationId) {
        loop {
            let notification = self.registered.notified();
            if lock(&self.state).owners.contains_key(activation_id) {
                return;
            }
            notification.await;
        }
    }

    fn token(&self, activation_id: &ActivationId) -> InvocationCancellation {
        lock(&self.state)
            .tokens
            .get(activation_id)
            .cloned()
            .expect("activation token must be registered")
    }

    fn invocations(&self) -> Vec<InvocationCommand> {
        lock(&self.state).invocations.clone()
    }

    fn cancellations(&self) -> Vec<CancellationCommand> {
        lock(&self.state).cancellations.clone()
    }

    fn release_pending(&self) {
        self.released.store(true, Ordering::Release);
        self.release.notify_waiters();
        self.release.notify_one();
    }
}
