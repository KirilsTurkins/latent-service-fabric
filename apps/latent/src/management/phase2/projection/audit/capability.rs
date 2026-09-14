use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

fn digest(value: &String, tree: &mut Tree) -> Result<(), Failure> {
    tree.text(value, 71)?;
    value
        .parse::<latent_core::ArtifactBlobDigest>()
        .map_err(|_| invalid_response())?;
    Ok(())
}
impl Project for proto::AuditCapabilityRevision {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        tree.text(&self.id, 128)?;
        if self.id.is_empty() || self.revision == 0 {
            return Err(invalid_response());
        }
        digest(&self.digest, tree)
    }
    fn project(self) -> Value {
        json!({ "id": self.id, "revision": self.revision.to_string(), "digest": self.digest })
    }
}
impl Project for proto::AuditCapabilityRequestDigest {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        if self.scope == 0 || proto::AuditCapabilityDigestScope::try_from(self.scope).is_err() {
            return Err(invalid_response());
        }
        digest(&self.digest, tree)
    }
    fn project(self) -> Value {
        json!({ "scope": proto::AuditCapabilityDigestScope::try_from(self.scope).expect("validated enum").as_str_name(), "digest": self.digest })
    }
}
impl Project for proto::AuditCapabilityContext {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        for value in [
            &self.activation,
            &self.root_activation,
            &self.service,
            &self.provider_profile,
            &self.capability,
        ] {
            tree.text(value, 128)?;
            if value.is_empty() {
                return Err(invalid_response());
            }
        }
        if let Some(parent) = &self.parent_activation {
            tree.text(parent, 128)?;
        }
        tree.text(&self.operation, 64)?;
        digest(&self.binding_definition_digest, tree)?;
        digest(&self.provider_configuration_digest, tree)?;
        self.binding
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        tree.sequence(&self.policies, 8)?;
        for policy in &self.policies {
            policy.validate(tree)?;
        }
        if let Some(request) = &self.request {
            request.validate(tree)?;
        }
        if self.policies.is_empty()
            || self.provider_configuration_epoch == 0
            || self.resource_class == 0
            || proto::AuditCapabilityResourceClass::try_from(self.resource_class).is_err()
            || self.provider_outcome.is_some_and(|value| {
                value == 0 || proto::AuditProviderOutcome::try_from(value).is_err()
            })
            || latent_core::PHASE3_HOST_ABI_V2
                .interface(&self.capability)
                .is_none()
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
            "activation": self.activation, "parentActivation": self.parent_activation,
            "rootActivation": self.root_activation, "service": self.service,
            "bindingDefinitionDigest": self.binding_definition_digest,
            "binding": self.binding.map(Project::project),
            "policies": self.policies.into_iter().map(Project::project).collect::<Vec<_>>(),
            "providerProfile": self.provider_profile,
            "providerConfigurationDigest": self.provider_configuration_digest,
            "providerConfigurationEpoch": self.provider_configuration_epoch.to_string(),
            "capability": self.capability, "operation": self.operation,
            "resourceClass": proto::AuditCapabilityResourceClass::try_from(self.resource_class).expect("validated enum").as_str_name(),
            "request": self.request.map(Project::project), "required": self.required,
            "providerOutcome": self.provider_outcome.map(|value| proto::AuditProviderOutcome::try_from(value).expect("validated enum").as_str_name()),
        })
    }
}
