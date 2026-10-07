use super::{
    contract, denied, expired, gate, input, invalid, native, recovery_bindings,
    state_authorization, Access, Action, Actions, Arc, AuthenticatedInvocationContext, CallerScope,
    EffectManagementAuthorization, Error, Inner, Instant, ManagementDecision, NamespaceRead, Phase,
    PlatformError, StateManagementReservation,
};
use latent_capabilities::namespace::STATE_CONTRACT;
use latent_policy::capability::{EvaluationInput, ResourceTarget};

impl Access {
    pub(super) fn read(
        inner: Arc<Inner>,
        namespace: state_authorization::Access,
        context: &AuthenticatedInvocationContext,
        node: Arc<dyn ManagementDecision>,
        request: &contract::Request,
        deadline: Instant,
        permit: Arc<dyn StateManagementReservation>,
    ) -> Result<Self, PlatformError> {
        let original = input::original(request)?;
        let command = original
            .effect
            .as_ref()
            .ok_or_else(invalid)?
            .command
            .as_ref()
            .ok_or_else(invalid)?;
        let caller =
            recovery_bindings::scope(&inner, context, command.shared_recovery_scope.as_deref())?;
        let data = state_authorization::EffectDecision {
            services: &inner.services,
            binding: &namespace.binding,
            context,
            caller: &caller,
            entity: command.entity.as_deref(),
            deadline,
            input_bytes: request.encoded_len(),
        }
        .seal("inspect-effect")?;
        Ok(Self {
            inner,
            namespace,
            principal: context.principal().clone(),
            caller,
            entity: command.entity.clone(),
            node,
            data,
            actions: std::sync::OnceLock::new(),
            action: input::action(original.mutation)?,
            deadline,
            permit,
        })
    }

    pub(super) fn seal_action(
        &self,
        context: &AuthenticatedInvocationContext,
        request: &contract::Request,
        planning: bool,
    ) -> Result<(), PlatformError> {
        if input::original(request)?.expected_policy_digest
            != state_authorization::policy_precondition(&self.namespace)
        {
            return Err(native(Error::Conflict));
        }
        let target = state_authorization::EffectDecision {
            services: &self.inner.services,
            binding: &self.namespace.binding,
            context,
            caller: &self.caller,
            entity: self.entity.as_deref(),
            deadline: self.deadline,
            input_bytes: request.encoded_len(),
        };
        self.actions
            .set(Actions {
                mutation: target.seal(input::operation(self.action))?,
                planning: planning.then(|| target.seal("effect-plan")).transpose()?,
            })
            .map_err(|_| invalid())
    }

    fn state(
        &self,
        phase: Phase,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut captured = vec![&self.namespace.inspect, &self.data];
        if phase != Phase::Read {
            captured.push(&self.actions.get().ok_or_else(denied)?.mutation);
        }
        if phase == Phase::Plan {
            captured.push(
                self.actions
                    .get()
                    .ok_or_else(denied)?
                    .planning
                    .as_ref()
                    .ok_or_else(denied)?,
            );
        }
        self.inner
            .services
            .policy
            .with_retained_decisions(&captured, &mut |inputs| {
                if inputs.len() != captured.len() {
                    return Err(denied());
                }
                self.tuple(inputs[0], "namespace-inspect", &self.namespace.caller, None)?;
                self.tuple(
                    inputs[1],
                    "inspect-effect",
                    &self.caller,
                    self.entity.as_deref(),
                )?;
                if phase != Phase::Read {
                    self.tuple(
                        inputs[2],
                        input::operation(self.action),
                        &self.caller,
                        self.entity.as_deref(),
                    )?;
                }
                if phase == Phase::Plan {
                    self.tuple(
                        inputs[3],
                        "effect-plan",
                        &self.caller,
                        self.entity.as_deref(),
                    )?;
                }
                action()
            })
    }

    fn tuple(
        &self,
        actual: &EvaluationInput<'_>,
        operation: &str,
        caller: &CallerScope,
        entity: Option<&str>,
    ) -> Result<(), PlatformError> {
        let binding = &self.namespace.binding;
        let valid = matches!(actual.resource, ResourceTarget::State {
            namespace, incarnation, entity: actual_entity, recovery_kind,
            recovery_scope, result_policy,
        } if namespace == binding.namespace.0
            && incarnation == binding.incarnation
            && actual_entity == entity
            && recovery_kind == caller.kind
            && recovery_scope == caller.scope
            && result_policy == binding.result_policy);
        if !valid
            || actual.principal.subject != self.principal.subject
            || actual.principal.kind != self.principal.kind
            || actual.principal.tenant != self.principal.tenant
            || actual.service != binding.service.0
            || actual.publication != binding.publication.id.as_str()
            || actual.capability != STATE_CONTRACT
            || actual.operation != operation
        {
            return Err(denied());
        }
        Ok(())
    }
    pub(super) fn publish(
        &self,
        read: &NamespaceRead,
        publish: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.with_current(read, Phase::Read, self.action, &mut || {
            self.with_live(&mut || {
                publish();
                Ok(())
            })
        })
        .map_err(native)
    }
}

impl EffectManagementAuthorization for Access {
    fn original_deadline(&self) -> Instant {
        self.deadline
    }

    fn before_lookup(&self) -> Result<(), Error> {
        if Instant::now() >= self.deadline {
            return Err(gate(&expired()));
        }
        let mut calls = 0_u8;
        self.node
            .with_current(&mut || {
                calls = calls.saturating_add(1);
                if calls != 1 {
                    return Err(invalid());
                }
                self.state(Phase::Read, &mut || self.permit.with_live(&mut || {}))
            })
            .map_err(|error| gate(&error))?;
        if calls != 1 {
            return Err(Error::InvalidAuthorizationFence);
        }
        Ok(())
    }

    fn with_current(
        &self,
        read: &NamespaceRead,
        phase: Phase,
        action: Action,
        accept: &mut dyn FnMut() -> Result<(), Error>,
    ) -> Result<(), Error> {
        if action != self.action {
            return Err(Error::PermissionDenied);
        }
        if Instant::now() >= self.deadline {
            return Err(gate(&expired()));
        }
        let binding = &self.namespace.binding;
        let record = read.record();
        if Some(&record.tenant) != self.principal.tenant.as_ref()
            || record.id != binding.namespace
            || record.version.incarnation != binding.incarnation
            || record.state_schema != binding.state_schema
        {
            return Err(Error::PermissionDenied);
        }
        let mut calls = 0_u8;
        let mut outcome = None;
        self.node
            .with_current(&mut || {
                self.state(phase, &mut || {
                    self.inner
                        .services
                        .namespaces
                        .lifecycle()
                        .with_current_record(read, || {
                            calls = calls.saturating_add(1);
                            if calls != 1 {
                                return Err(latent_state::namespace::NamespaceError::Invalid);
                            }
                            outcome = Some(accept());
                            Ok(())
                        })
                        .map_err(super::super::namespace_error)
                })
            })
            .map_err(|error| gate(&error))?;
        if calls != 1 {
            return Err(Error::InvalidAuthorizationFence);
        }
        outcome.ok_or(Error::InvalidAuthorizationFence)?
    }

    fn with_live(&self, accept: &mut dyn FnMut() -> Result<(), Error>) -> Result<(), Error> {
        let mut calls = 0_u8;
        let mut outcome = None;
        self.permit
            .with_live(&mut || {
                calls = calls.saturating_add(1);
                if calls == 1 {
                    outcome = Some(accept());
                }
            })
            .map_err(|error| gate(&error))?;
        if calls != 1 {
            return Err(Error::InvalidAuthorizationFence);
        }
        outcome.ok_or(Error::InvalidAuthorizationFence)?
    }
}
