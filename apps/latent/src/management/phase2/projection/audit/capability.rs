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
        // Read-only recognition of this exact existing V6 audit port grants no
        // provider authority and leaves the ordinary CURRENT profile unchanged.
        let native_threads = self.capability == "latent:runtime-native/threads@0.1.0"
            && latent_core::PHASE3_HOST_ABI_V6
                .interface(&self.capability)
                .is_some()
            && self.operation == "start"
            && self.resource_class == proto::AuditCapabilityResourceClass::Context as i32;
        if self.policies.is_empty()
            || self.provider_configuration_epoch == 0
            || self.resource_class == 0
            || proto::AuditCapabilityResourceClass::try_from(self.resource_class).is_err()
            || self.provider_outcome.is_some_and(|value| {
                value == 0 || proto::AuditProviderOutcome::try_from(value).is_err()
            })
            || latent_core::PHASE3_HOST_ABI_CURRENT
                .interface(&self.capability)
                .is_none()
                && latent_core::PHASE4_HOST_ABI_V1
                    .interface(&self.capability)
                    .is_none()
                && !native_threads
            || native_threads
                && self.provider_outcome.is_some_and(|outcome| {
                    !matches!(
                        proto::AuditProviderOutcome::try_from(outcome),
                        Ok(proto::AuditProviderOutcome::NotStarted
                            | proto::AuditProviderOutcome::HostCompleted
                            | proto::AuditProviderOutcome::Rejected
                            | proto::AuditProviderOutcome::Unknown)
                    )
                })
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::management::phase2::projection::checked;

    fn native() -> proto::AuditCapabilityContext {
        let digest = format!("sha256:{}", "1".repeat(64));
        let revision = proto::AuditCapabilityRevision {
            id: "native-binding".into(),
            revision: 1,
            digest: digest.clone(),
        };
        proto::AuditCapabilityContext {
            activation: "c-thread-cancel".into(),
            parent_activation: None,
            root_activation: "c-thread-cancel".into(),
            service: "examples/c-thread-runtime".into(),
            binding_definition_digest: digest.clone(),
            binding: Some(revision.clone()),
            policies: vec![revision],
            provider_profile: "conservative-native-total-starts-v1".into(),
            provider_configuration_digest: digest,
            provider_configuration_epoch: 1,
            capability: "latent:runtime-native/threads@0.1.0".into(),
            operation: "start".into(),
            resource_class: proto::AuditCapabilityResourceClass::Context as i32,
            request: None,
            required: false,
            provider_outcome: None,
        }
    }

    #[test]
    fn native_thread_audit_projection_preserves_exact_v6_facts_without_default_authority() {
        assert_eq!(
            latent_core::PHASE3_HOST_ABI_CURRENT,
            latent_core::PHASE3_HOST_ABI_V5
        );
        assert!(latent_core::PHASE3_HOST_ABI_CURRENT
            .interface(&native().capability)
            .is_none());
        for outcome in [
            None,
            Some(proto::AuditProviderOutcome::NotStarted),
            Some(proto::AuditProviderOutcome::HostCompleted),
            Some(proto::AuditProviderOutcome::Rejected),
            Some(proto::AuditProviderOutcome::Unknown),
        ] {
            let mut row = native();
            row.provider_outcome = outcome.map(|value| value as i32);
            checked(&row, 16384).unwrap();
            let expected = row.clone();
            let value = row.project();
            assert_eq!(value["capability"], expected.capability);
            assert_eq!(value["operation"], "start");
            assert_eq!(
                value["resourceClass"],
                "AUDIT_CAPABILITY_RESOURCE_CLASS_CONTEXT"
            );
            assert_eq!(value["required"], false);
            assert_eq!(
                value["providerOutcome"].as_str(),
                outcome.map(|value| value.as_str_name())
            );
        }
        let mut original = native();
        original.capability = "latent:runtime/activation@0.1.0".into();
        original.operation = "register".into();
        original.resource_class = proto::AuditCapabilityResourceClass::Clock as i32;
        checked(&original, 16384).unwrap();
    }

    #[test]
    fn native_thread_audit_projection_refuses_foreign_versions_classes_operations_and_outcomes() {
        for capability in [
            "latent:runtime-native/threads@0.2.0",
            "latent:runtime-native/other@0.1.0",
            "latent:runtime-native/threads@0.1.0/extra",
            "unknown:runtime/threads@0.1.0",
        ] {
            let mut row = native();
            row.capability = capability.into();
            assert!(checked(&row, 16384).is_err());
        }
        for operation in ["", "spawn", "resume"] {
            let mut row = native();
            row.operation = operation.into();
            assert!(checked(&row, 16384).is_err());
        }
        for class in [
            0,
            proto::AuditCapabilityResourceClass::Clock as i32,
            proto::AuditCapabilityResourceClass::Http as i32,
            999,
        ] {
            let mut row = native();
            row.resource_class = class;
            assert!(checked(&row, 16384).is_err());
        }
        for outcome in [
            0,
            proto::AuditProviderOutcome::LocalDispatchAccepted as i32,
            proto::AuditProviderOutcome::HttpResponseReceived as i32,
            proto::AuditProviderOutcome::BrokerAcknowledged as i32,
            proto::AuditProviderOutcome::BlobSealed as i32,
            proto::AuditProviderOutcome::SecretResolved as i32,
            999,
        ] {
            let mut row = native();
            row.provider_outcome = Some(outcome);
            assert!(checked(&row, 16384).is_err());
        }
        for field in ["binding", "policies", "digest", "epoch"] {
            let mut row = native();
            match field {
                "binding" => row.binding = None,
                "policies" => row.policies.clear(),
                "digest" => row.provider_configuration_digest = "private".into(),
                "epoch" => row.provider_configuration_epoch = 0,
                _ => unreachable!(),
            }
            assert!(checked(&row, 16384).is_err());
        }
    }
}
