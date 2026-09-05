/// A validated invocation request presented to the lifecycle owner.
///
/// Missing IDs remain missing. The activation manager owns ID allocation, root
/// selection, trace construction, routing, admission, status publication, and
/// cleanup; the RPC adapter does not create an `ActivationEnvelope` itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationRequest {
    pub requested_activation_id: Option<ActivationId>,
    pub parent_activation_id: Option<ActivationId>,
    pub root_activation_id: Option<ActivationId>,
    pub target: InvocationTarget,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub idempotency_key: Option<IdempotencyKey>,
    pub budget: ResourceBudget,
    pub metadata: Metadata,
}

/// Authenticated command handed to the activation lifecycle owner.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationCommand {
    pub principal: InvocationPrincipal,
    pub request: InvocationRequest,
}

/// Revision pin returned by the lifecycle owner for a completed invocation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationReceipt {
    pub activation_id: ActivationId,
    pub revision_id: RevisionId,
    pub release_digest: ReleaseDigest,
    pub route_generation: RouteGeneration,
}

/// Lossless domain representation of a terminal invocation response.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationResponse {
    pub receipt: InvocationReceipt,
    pub outcome: ActivationOutcome,
}

/// Authenticated cancellation command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CancellationCommand {
    pub principal: InvocationPrincipal,
    pub activation_id: ActivationId,
    pub reason: String,
}

/// Authenticated current-or-retained status lookup.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusQuery {
    pub principal: InvocationPrincipal,
    pub activation_id: ActivationId,
}

/// Transport-neutral seam implemented by the Phase 1 activation manager.
///
/// Implementations must reserve the activation ID and its authenticated owner
/// atomically before the invocation can yield. `cancel` and `get_activation`
/// must authorize ownership in the same operation that observes or mutates the
/// activation record; a missing status snapshot must never grant cancellation.
/// Implementations also own bounded terminal retention and must never evict an
/// active activation.
pub trait InvocationRuntime: Send + Sync {
    fn invoke<'a>(
        &'a self,
        command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'a, Result<InvocationResponse, PlatformError>>;

    fn cancel<'a>(
        &'a self,
        command: CancellationCommand,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>>;

    fn get_activation<'a>(
        &'a self,
        query: StatusQuery,
    ) -> BoxFuture<'a, Result<Option<ActivationStatus>, PlatformError>>;
}

/// Authenticated identity inserted by a local listener/interceptor.
///
/// This value is carried in Tonic request extensions and is never reconstructed
/// from arbitrary invocation metadata. A concrete listener may replace the
/// local convention without changing the public Protobuf contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthenticatedInvocationContext {
    principal: InvocationPrincipal,
    transport_deadline_unix_millis: Option<u64>,
}

impl AuthenticatedInvocationContext {
    #[must_use]
    pub fn new(principal: InvocationPrincipal) -> Self {
        Self {
            principal,
            transport_deadline_unix_millis: None,
        }
    }

    #[must_use]
    pub fn with_transport_deadline(mut self, deadline_unix_millis: u64) -> Self {
        self.transport_deadline_unix_millis = Some(deadline_unix_millis);
        self
    }

    #[must_use]
    pub fn principal(&self) -> &InvocationPrincipal {
        &self.principal
    }

    #[must_use]
    pub const fn transport_deadline_unix_millis(&self) -> Option<u64> {
        self.transport_deadline_unix_millis
    }

    /// Builds an in-process Tonic request carrying this authenticated context.
    #[must_use]
    pub fn request<T>(&self, message: T) -> Request<T> {
        let mut request = Request::new(message);
        request.extensions_mut().insert(self.clone());
        request
    }
}

/// Replaceable policy for the local authenticated-principal convention.
pub trait PrincipalPolicy: Send + Sync {
    fn authenticate(&self, principal: &InvocationPrincipal) -> Result<(), PlatformError>;

    fn authorize_target(
        &self,
        principal: &InvocationPrincipal,
        target_tenant: &str,
    ) -> Result<(), PlatformError>;
}

/// Default local policy: authenticated administrators may cross tenants;
/// every other principal must carry the exact target tenant.
#[derive(Debug, Clone, Copy, Default)]
pub struct LocalPrincipalPolicy;

impl PrincipalPolicy for LocalPrincipalPolicy {
    fn authenticate(&self, principal: &InvocationPrincipal) -> Result<(), PlatformError> {
        if principal.subject.trim().is_empty() || principal.kind == PrincipalKind::Anonymous {
            return Err(boundary_error(
                PlatformErrorCode::Unauthenticated,
                "authentication is required",
            ));
        }
        Ok(())
    }

    fn authorize_target(
        &self,
        principal: &InvocationPrincipal,
        target_tenant: &str,
    ) -> Result<(), PlatformError> {
        self.authenticate(principal)?;
        if principal.kind == PrincipalKind::Administrator {
            return Ok(());
        }
        if principal
            .tenant
            .as_ref()
            .is_some_and(|tenant| tenant.0 == target_tenant)
        {
            Ok(())
        } else {
            Err(boundary_error(
                PlatformErrorCode::PermissionDenied,
                "the authenticated principal cannot invoke the target tenant",
            ))
        }
    }
}

/// Clock used to validate absolute caller deadlines.
pub trait Clock: Send + Sync {
    fn now_unix_millis(&self) -> u64;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_unix_millis(&self) -> u64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |duration| {
            u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
        })
    }
}

#[derive(Default)]
struct CancellationState {
    cancelled: AtomicBool,
    notification: Notify,
}

/// Per-invocation cancellation signal passed to the lifecycle owner.
///
/// A dropped Tonic request future, a transport timeout, and a caller deadline
/// all signal only this token. Other calls sharing the same connection receive
/// independent tokens.
#[derive(Clone, Default)]
pub struct InvocationCancellation {
    inner: Arc<CancellationState>,
}

impl fmt::Debug for InvocationCancellation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("InvocationCancellation")
            .field("cancelled", &self.is_cancelled())
            .finish()
    }
}

impl InvocationCancellation {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        if !self.inner.cancelled.swap(true, Ordering::AcqRel) {
            self.inner.notification.notify_waiters();
            self.inner.notification.notify_one();
        }
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.inner.cancelled.load(Ordering::Acquire)
    }

    pub async fn cancelled(&self) {
        if self.is_cancelled() {
            return;
        }
        let notification = self.inner.notification.notified();
        if self.is_cancelled() {
            return;
        }
        notification.await;
    }
}

/// Hard ceilings applied before expensive lifecycle work begins.
#[allow(clippy::struct_field_names)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationLimits {
    pub max_message_bytes: usize,
    pub max_payload_bytes: usize,
    pub max_metadata_entries: usize,
    pub max_metadata_bytes: usize,
    pub max_string_bytes: usize,
    pub max_id_bytes: usize,
    pub max_cancel_reason_bytes: usize,
    pub max_timeout_millis: u64,
    pub max_cpu_fuel: u64,
    pub max_memory_bytes: u64,
    pub max_child_calls: u32,
    pub max_outbound_requests: u32,
    pub max_state_read_bytes: u64,
    pub max_state_write_bytes: u64,
    pub max_blob_read_bytes: u64,
    pub max_blob_write_bytes: u64,
    pub max_log_bytes: u64,
    pub max_effect_count: u32,
    pub max_platform_error_details: usize,
    pub max_platform_error_fields: usize,
    pub max_platform_error_message_bytes: usize,
}