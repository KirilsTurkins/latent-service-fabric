use super::io::{charge, state_error};
use super::{authorization::StateAuthorization, CommandHostSelection, SessionPayload};
use latent_core::{transaction_contract::Precondition, ActivationId, HostMemoryReservation};
use latent_executor::transaction::{Mode, StateFailure};
use latent_state::{
    embedded::{ReadView, StoreError},
    session::{SessionLimits, StateError, StateMode, StateScope, StateSession},
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) fn configuration(
    authorization: &StateAuthorization,
    activation: &ActivationId,
    scope: &StateScope,
    command: Option<&CommandHostSelection>,
    conditions: &[Precondition],
) -> Result<(Mode, SessionLimits, u64), StateFailure> {
    let mode = match scope.mode {
        StateMode::Command => Mode::Command,
        StateMode::Query => Mode::Query,
    };
    let ownership = authorization.authority.ownership();
    if activation != authorization.authority.activation_id()
        || scope.tenant != ownership.tenant
        || scope.namespace.0 != ownership.namespace
        || scope.incarnation != ownership.incarnation
        || scope.entity != ownership.entity
        || scope.state_schema != authorization.namespace.record().state_schema
        || (mode == Mode::Command) != command.is_some()
        || conditions.len() > 128
        || (mode == Mode::Query && !conditions.is_empty())
    {
        return Err(StateFailure::PermissionDenied);
    }
    if command.as_ref().is_some_and(|command| {
        command.key.tenant != ownership.tenant.0
            || command.key.namespace != ownership.namespace
            || command.key.incarnation != ownership.incarnation.to_string()
            || command.key.entity != ownership.entity
            || command.key.recovery_scope != ownership.caller.scope
            || command.publication != authorization.publication()
    }) {
        return Err(StateFailure::PermissionDenied);
    }
    let budget = &authorization.budget;
    let read_bytes = usize::try_from(budget.granted().state_read_bytes.min(4 * 1024 * 1024))
        .map_err(|_| StateFailure::ReadBudgetExhausted)?;
    let staged_bytes =
        usize::try_from(budget.granted().state_write_bytes.clamp(1, 8 * 1024 * 1024))
            .map_err(|_| StateFailure::WriteBudgetExhausted)?;
    if read_bytes < 1024 {
        return Err(StateFailure::ReadBudgetExhausted);
    }
    let age = budget
        .deadline()
        .remaining_at(Instant::now())
        .ok_or(StateFailure::Unavailable)?
        .min(Duration::from_secs(30));
    if age.is_zero() {
        return Err(StateFailure::Cancelled);
    }
    let limits = SessionLimits {
        read_bytes,
        staged_bytes,
        maximum_age: age,
        host_calls: authorization.authority.ceiling().operations.clamp(1, 256),
        ..SessionLimits::default()
    };
    let retained_bytes = u64::try_from(read_bytes + staged_bytes * 2 + 3 * 1024 * 1024)
        .map_err(|_| StateFailure::Unavailable)?;
    Ok((mode, limits, retained_bytes))
}

pub(super) struct ViewPreconditions<'a> {
    pub records: &'a [Precondition],
    pub minimum: Option<&'a [u8]>,
}

pub(super) fn initialize(
    view: &ReadView,
    selected: StateScope,
    limits: SessionLimits,
    mode: Mode,
    preconditions: &ViewPreconditions<'_>,
    auth: &StateAuthorization,
    memory: Arc<HostMemoryReservation>,
) -> Result<Result<SessionPayload, StateFailure>, StoreError> {
    let opened = StateSession::open(view, selected, limits, |_, _| {
        auth.authorize(
            if mode == Mode::Command {
                "info"
            } else {
                "query-info"
            },
            0,
            0,
            || Ok(()),
        )
        .map_err(|_| StateError::PermissionDenied)
    });
    let mut session = match opened {
        Ok(session) => session,
        Err(error) => {
            if let Some(fatal) = error.storage_error() {
                return Err(fatal);
            }
            return Ok(Err(state_error(error, false)));
        }
    };
    if session.view_version() != auth.namespace.record().version {
        // The original authority and the actual native snapshot must describe
        // the same generation. A concurrent write cannot become an invented
        // view version or silently refresh the command's original observation.
        return Ok(Err(StateFailure::Conflict));
    }
    if let Some(minimum) = preconditions.minimum {
        if let Err(error) = session
            .view_identity()
            .require_minimum(session.scope(), minimum)
        {
            return Ok(Err(state_error(error, false)));
        }
    }
    if mode == Mode::Command {
        if let Err(error) = session.check_preconditions(view, preconditions.records, |_, _| {
            auth.authorize("get", 0, 0, || Ok(()))
                .map_err(|_| StateError::PermissionDenied)
        }) {
            if let Some(fatal) = error.storage_error() {
                return Err(fatal);
            }
            return Ok(Err(state_error(error, false)));
        }
    }
    if let Err(error) = charge(&auth.budget, (0, 0), session.charged_bytes()) {
        return Ok(Err(error));
    }
    let view_token = match session.view_token() {
        Ok(token) => token,
        Err(error) => return Ok(Err(state_error(error, false))),
    };
    Ok(Ok(SessionPayload {
        session,
        view_token,
        intents: Vec::with_capacity(128),
        memory,
    }))
}
