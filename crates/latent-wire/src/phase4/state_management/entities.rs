//! Entity metadata comes from an actual affine Recovery snapshot. Listing and
//! inspection grants, the original global permit and that native view survive
//! transport encoding and detached frame destruction.
mod cursor;
use super::{
    audit, authorization::Access, c, capacity, contract, denied, error, expired, inspection,
    invalid, io_error, missing, protected_error, Arc, Inner, Instant, OwnedPhase4Response,
    PlatformError, PlatformErrorCode, StateManagementReservation, WORK_BYTES,
};
use latent_audit::{AuditOperationResult, AuditReason};
use latent_capabilities::namespace::NamespaceControl;
use latent_state::{
    embedded::{ReadView, StoreError},
    namespace::{catalog::NamespaceRead, lifecycle::NamespaceLifecycleHandle},
    protected_store::ProtectedStoreView,
    session::{
        entities::{inspect_entities, EntityPage, EntityPageRequest},
        StateError,
    },
};
use prost::Message;
use std::sync::{Mutex, OnceLock};

struct Keeper {
    inner: Arc<Inner>,
    access: Access,
    deadline: Instant,
    pin: OnceLock<NamespaceLifecycleHandle>,
    // Last: authorization/metadata must retire before the original byte owner.
    permit: Arc<dyn StateManagementReservation>,
}
impl Keeper {
    fn before_lookup(&self) -> Result<(), PlatformError> {
        if self.inner.services.clock.monotonic_now() >= self.deadline {
            return Err(expired());
        }
        self.inner.services.policy.with_retained_decisions(
            &[
                self.access.listing.as_ref().ok_or_else(denied)?,
                &self.access.inspect,
            ],
            &mut |_| self.permit.with_live(&mut || {}),
        )
    }
    fn with_current(
        &self,
        read: &NamespaceRead,
        publish: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        if self.inner.services.clock.monotonic_now() >= self.deadline {
            return Err(expired());
        }
        if read.record().state_schema != self.access.binding.state_schema {
            return Err(denied());
        }
        NamespaceControl::with_listing_retained(
            &self.inner.services.policy,
            self.access.listing.as_ref().ok_or_else(denied)?,
            &self.access.inspect,
            self.inner.services.namespaces.lifecycle(),
            self.pin.get().ok_or_else(denied)?,
            read,
            || self.permit.with_live(publish),
        )
    }

    fn pin(&self, read: &NamespaceRead) -> Result<(), PlatformError> {
        let handle = self
            .inner
            .services
            .namespaces
            .lifecycle()
            .pin(read)
            .map_err(super::namespace_error)?;
        self.pin.set(handle).map_err(|_| denied())
    }
}

struct ResponseOwner {
    read: NamespaceRead,
    // Mutex confines the non-Sync affine view; no native read runs under it.
    _view: Mutex<Option<ProtectedStoreView>>,
    keeper: Arc<Keeper>,
}
impl crate::phase4::Phase4ResponseOwner for ResponseOwner {
    fn reserved_bytes(&self) -> usize {
        self.keeper.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.keeper.with_current(&self.read, publish)
    }
}

pub(super) async fn select(
    inner: Arc<Inner>,
    request: Box<c::SelectEntityRequest>,
    access: Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    let keeper = Arc::new(Keeper {
        inner: Arc::clone(&inner),
        access,
        deadline,
        pin: OnceLock::new(),
        permit,
    });
    keeper.before_lookup()?;
    let view = inner
        .services
        .store
        .open_recovery_view_retaining(keeper.clone())
        .map_err(protected_error)?
        .await
        .map_err(io_error)?
        .map_err(protected_error)?;
    let worker = Arc::clone(&keeper);
    let job = inner
        .services
        .store
        .with_view(view, WORK_BYTES as u64, move |native| {
            let result = select_in(native, &worker, &request);
            let finish = pending.finish(
                if result.as_ref().is_ok_and(Result::is_ok) {
                    AuditOperationResult::Committed
                } else {
                    AuditOperationResult::Rejected
                },
                AuditReason::Verified,
                None,
                false,
            );
            result.map(|value| (value, finish))
        })
        .map_err(protected_error)?;
    let (view, result) = job.await.map_err(io_error)?;
    let (result, finish) = result.map_err(protected_error)?;
    let (read, response) = result?;
    // Reads have no independent public audit-ack field. Fail closed on an
    // unknown current audit conclusion before returning the metadata.
    inspection::read_ack(finish).await?;
    let response: contract::Response = response.into();
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|bytes| bytes.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > keeper.permit.reserved_response_bytes() {
        return Err(capacity());
    }
    let owner = Arc::new(ResponseOwner {
        read,
        _view: Mutex::new(Some(view)),
        keeper,
    });
    crate::phase4::Phase4ResponseOwner::with_current(owner.as_ref(), &mut || {})?;
    Ok(OwnedPhase4Response::new(response, owner))
}

fn select_in(
    view: &ReadView,
    keeper: &Keeper,
    request: &c::SelectEntityRequest,
) -> Result<Result<(NamespaceRead, c::SelectEntityResponse), PlatformError>, StoreError> {
    if let Err(error) = keeper.before_lookup() {
        return Ok(Err(error));
    }
    let Some(read) =
        inspection::read_in(view, &keeper.access).map_err(inspection::native_namespace)?
    else {
        return Ok(Err(missing()));
    };
    if let Err(error) = keeper.pin(&read) {
        return Ok(Err(error));
    }
    if let Err(error) = keeper.with_current(&read, &mut || {}) {
        return Ok(Err(error));
    }
    let requested = request.page.as_ref().expect("validated page");
    let (after, expected_view) = match cursor::decode(request, &keeper.access) {
        Ok(value) => value,
        Err(error) => return Ok(Err(error)),
    };
    let mut refusal = None;
    let page = inspect_entities(
        view,
        read.record(),
        EntityPageRequest {
            prefix: request.prefix.as_deref().unwrap_or_default(),
            after,
            expected_view,
            maximum: requested.limit as usize,
        },
        || match keeper.with_current(&read, &mut || {}) {
            Ok(()) => Ok(()),
            Err(error) => {
                refusal = Some(error);
                Err(StateError::PermissionDenied)
            }
        },
    );
    let page = match page {
        Ok(page) => page,
        Err(StateError::Corrupt) => return Err(StoreError::Corrupt),
        Err(StateError::UnsupportedFormat) => return Err(StoreError::UnsupportedFormat),
        Err(StateError::Unavailable) => return Err(StoreError::Unavailable),
        Err(error) => return Ok(Err(refusal.unwrap_or_else(|| state_error(error)))),
    };
    let response = match to_proto(page, request, &keeper.access) {
        Ok(value) => value,
        Err(error) => return Ok(Err(error)),
    };
    if let Err(error) = keeper.with_current(&read, &mut || {}) {
        return Ok(Err(error));
    }
    Ok(Ok((read, response)))
}

fn to_proto(
    page: EntityPage,
    request: &c::SelectEntityRequest,
    access: &Access,
) -> Result<c::SelectEntityResponse, PlatformError> {
    let continuation = page
        .continuation
        .map(|after| cursor::encode(request, access, page.view, after))
        .transpose()?;
    let count = page.entities.len();
    let entities = page
        .entities
        .into_iter()
        .map(|entity| c::EntityInspection {
            entity: entity.entity,
            version: entity.version,
        })
        .collect();
    let mut response = c::SelectEntityResponse {
        entities,
        page: Some(latent_rpc::transaction::v1::PageResponse {
            next_cursor: continuation,
            returned_count: u32::try_from(count).map_err(|_| capacity())?,
            encoded_bytes: 0,
        }),
    };
    // The exact complete encoded page, including its own varint count, is
    // bounded before the transport allocates its retained encoding buffers.
    let first = response.encoded_len();
    response.page.as_mut().expect("page").encoded_bytes = first as u64;
    let second = response.encoded_len();
    response.page.as_mut().expect("page").encoded_bytes = second as u64;
    let encoded = response.encoded_len();
    response.page.as_mut().expect("page").encoded_bytes = encoded as u64;
    if response.encoded_len() != encoded || encoded > contract::MAX_PAGE_BYTES {
        return Err(capacity());
    }
    Ok(response)
}

fn state_error(value: StateError) -> PlatformError {
    match value {
        StateError::Limit => capacity(),
        StateError::PermissionDenied => denied(),
        StateError::Invalid | StateError::InvalidCursor => invalid(),
        StateError::Conflict => error(PlatformErrorCode::StateConflict, "entity-view-conflict"),
        StateError::Expired => expired(),
        _ => error(
            PlatformErrorCode::Unavailable,
            "entity-inspection-unavailable",
        ),
    }
}
