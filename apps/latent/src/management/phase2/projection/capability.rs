use super::{invalid_response, json, proto, Failure, Project, Tree, Value};
use crate::management::canonical_digest;
use std::collections::BTreeSet;

fn digest(value: &String, tree: &mut Tree) -> Result<(), Failure> {
    tree.text(value, 71)?;
    if !canonical_digest(value) {
        return Err(invalid_response());
    }
    Ok(())
}

fn identity(value: &String, tree: &mut Tree, maximum: usize) -> Result<(), Failure> {
    tree.text(value, maximum)?;
    if value.is_empty() || !value.is_ascii() {
        return Err(invalid_response());
    }
    Ok(())
}

fn state(value: &str) -> bool {
    matches!(
        value,
        "configured-current"
            | "policy-changed-or-revoked"
            | "provider-unavailable"
            | "publication-unavailable"
            | "route-changed-or-unavailable"
            | "inspection-indeterminate"
    )
}

impl Project for proto::CapabilityInspectionRevision {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        identity(&self.deployment_id, tree, 256)?;
        identity(&self.revision_id, tree, 128)?;
        digest(&self.component_digest, tree)?;
        if let Some(publication) = &self.publication_id {
            identity(publication, tree, 83)?;
            publication
                .parse::<latent_core::PublicationId>()
                .map_err(|_| invalid_response())?;
        }
        if !self
            .revision_id
            .strip_prefix("revision-v1:")
            .is_some_and(canonical_digest)
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"deploymentId":self.deployment_id,"revisionId":self.revision_id,
            "componentDigest":self.component_digest,"publicationId":self.publication_id,
            "routeGeneration":self.route_generation.to_string(),"catalogTransaction":self.catalog_transaction.to_string()})
    }
}

impl Project for proto::CapabilityInspectionPolicy {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        identity(&self.id, tree, 256)?;
        digest(&self.digest, tree)?;
        if self.revision == 0 {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"id":self.id,"revision":self.revision.to_string(),"digest":self.digest})
    }
}

impl Project for proto::CapabilityBindingInspection {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        if let Some(value) = &self.definition_digest {
            digest(value, tree)?;
        }
        self.provider_binding
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        tree.sequence(&self.policies, 8)?;
        let mut ids = BTreeSet::new();
        for policy in &self.policies {
            policy.validate(tree)?;
            if !ids.insert(&policy.id) {
                return Err(invalid_response());
            }
        }
        identity(&self.provider_profile, tree, 128)?;
        digest(&self.provider_configuration_digest, tree)?;
        tree.text(&self.state, 64)?;
        if self.provider_configuration_epoch == 0 || !state(&self.state) {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"definitionDigest":self.definition_digest,"providerBinding":self.provider_binding.map(Project::project),
            "policies":self.policies.into_iter().map(Project::project).collect::<Vec<_>>(),
            "providerProfile":self.provider_profile,"providerConfigurationDigest":self.provider_configuration_digest,
            "providerConfigurationEpoch":self.provider_configuration_epoch.to_string(),"state":self.state})
    }
}

impl Project for proto::CapabilityDescriptor {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        identity(&self.id, tree, 128)?;
        identity(&self.contract, tree, 128)?;
        identity(&self.provider, tree, 128)?;
        tree.sequence(&self.operations, 128)?;
        let mut operations = BTreeSet::new();
        for operation in &self.operations {
            identity(operation, tree, 64)?;
            if !operations.insert(operation) {
                return Err(invalid_response());
            }
        }
        let inspection = self.inspection.as_ref().ok_or_else(invalid_response)?;
        inspection.validate(tree)?;
        if self.id != self.contract
            || self.provider != inspection.provider_profile
            || !self.attributes.is_empty()
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"id":self.id,"contract":self.contract,"provider":self.provider,"operations":self.operations,
            "inspection":self.inspection.map(Project::project)})
    }
}

impl Project for proto::CapabilityResourceUsage {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        if !matches!(self.scope.as_str(), "tenant" | "node")
            || self.counters.len() > 80
            || self.counters.capacity() > 112
        {
            return Err(invalid_response());
        }
        tree.charge(
            self.counters.len(),
            self.counters.capacity().saturating_mul(64),
        )?;
        for key in self.counters.keys() {
            identity(key, tree, 64)?;
            if !usage_key(&self.scope, key) {
                return Err(invalid_response());
            }
        }
        tree.sequence(&self.unavailable, 3)?;
        for value in &self.unavailable {
            identity(value, tree, 64)?;
            if !matches!(
                value.as_str(),
                "provider-pools-no-retained-owner"
                    | "provider-io-no-retained-pool-owner"
                    | "audit-owner-not-configured"
            ) {
                return Err(invalid_response());
            }
        }
        if self.scope == "tenant" && (self.counters.len() != 10 || !self.unavailable.is_empty()) {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"scope":self.scope,"counters":self.counters.into_iter()
            .map(|(key,value)| (key,value.to_string())).collect::<std::collections::BTreeMap<_,_>>(),
            "unavailable":self.unavailable})
    }
}

fn usage_key(scope: &str, key: &str) -> bool {
    if scope == "tenant" {
        return matches!(
            key,
            "sessions"
                | "retired_sessions_with_resources"
                | "handles"
                | "calls"
                | "waiting"
                | "results"
                | "reserved_buffer_bytes"
                | "live_children"
                | "delegated_memory_bytes"
                | "ledgers_without_delegation"
        );
    }
    if let Some(suffix) = key.strip_prefix("broker_") {
        return matches!(
            suffix,
            "providers"
                | "plans"
                | "sessions"
                | "handles"
                | "calls"
                | "results"
                | "metadata_bytes"
                | "buffer_bytes"
        );
    }
    if let Some(suffix) = key.strip_prefix("pool_") {
        return matches!(
            suffix,
            "closed"
                | "control_failed"
                | "configurations"
                | "retained_configurations"
                | "clients"
                | "connections"
                | "active_connections"
                | "connecting_connections"
                | "retired_connections"
                | "idle_connections"
                | "pending_requests"
                | "running_requests"
                | "workers"
                | "cleanup_jobs"
                | "failed_cleanup"
                | "metadata_bytes"
                | "control_owners"
        );
    }
    if let Some(suffix) = key.strip_prefix("io_") {
        return matches!(
            suffix,
            "calls"
                | "occupied_running_slots"
                | "queued_calls"
                | "staged_bytes"
                | "result_bytes"
                | "buffers"
                | "streams"
                | "metadata_bytes"
        );
    }
    if let Some(suffix) = key.strip_prefix("audit_") {
        return matches!(
            suffix,
            "capture_dropped"
                | "closed"
                | "dropped_observations"
                | "unavailable_events"
                | "pending_attempts"
                | "queued_operations"
                | "reserved_records"
                | "reserved_bytes"
                | "query_owners"
                | "query_bytes"
        );
    }
    false
}

impl Project for proto::ListCapabilitiesResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        tree.sequence(&self.capabilities, 128)?;
        let mut ids = BTreeSet::new();
        for entry in &self.capabilities {
            entry.validate(tree)?;
            if !ids.insert(&entry.id) {
                return Err(invalid_response());
            }
        }
        self.revision
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        self.page
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        let tenant = self.tenant_usage.as_ref().ok_or_else(invalid_response)?;
        tenant.validate(tree)?;
        if tenant.scope != "tenant"
            || !matches!(
                self.state.as_str(),
                "compiled-plan" | "binding-plan-unavailable"
            )
            || (self.state == "binding-plan-unavailable" && !self.capabilities.is_empty())
        {
            return Err(invalid_response());
        }
        if let Some(node) = &self.node_usage {
            node.validate(tree)?;
            if node.scope != "node" {
                return Err(invalid_response());
            }
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"capabilities":self.capabilities.into_iter().map(Project::project).collect::<Vec<_>>(),
            "revision":self.revision.map(Project::project),"nextPageToken":self.page.and_then(|value| value.next_page_token),
            "tenantUsage":self.tenant_usage.map(Project::project),"nodeUsage":self.node_usage.map(Project::project),
            "state":self.state,"executionPermission":false})
    }
}

impl Project for proto::ExplainCapabilityGrantResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        tree.sequence(&self.reasons, 1)?;
        let reason = self.reasons.first().ok_or_else(invalid_response)?;
        tree.text(reason, 64)?;
        if self.allowed != (reason == "policy-allows-subject-to-live-admission")
            || !(state(reason)
                || matches!(
                    reason.as_str(),
                    "policy-allows-subject-to-live-admission"
                        | "binding-plan-unavailable"
                        | "capability-not-imported"
                        | "policy-denied"
                ))
            || !self.policy_digest.is_empty()
            || self.obligations.len() != 3
            || self
                .obligations
                .get("live-admission-required")
                .map(String::as_str)
                != Some("true")
            || self
                .obligations
                .get("activation-budget-reserved")
                .map(String::as_str)
                != Some("false")
            || self.obligations.get("descriptive-only").map(String::as_str) != Some("true")
        {
            return Err(invalid_response());
        }
        self.revision
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        if let Some(inspection) = &self.inspection {
            inspection.validate(tree)?;
        }
        if self.allowed && (self.inspection.is_none() || self.ceiling.is_none()) {
            return Err(invalid_response());
        }
        if !self.allowed && (self.requires_audit || self.ceiling.is_some()) {
            return Err(invalid_response());
        }
        if let Some(ceiling) = &self.ceiling {
            if ceiling.operations == 0
                || ceiling.operations > 1_000_000
                || ceiling.input_bytes > 64 * 1024 * 1024
                || ceiling.output_bytes > 64 * 1024 * 1024
                || ceiling.wall_time_millis == 0
                || ceiling.wall_time_millis > 300_000
            {
                return Err(invalid_response());
            }
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"allowed":self.allowed,"reasons":self.reasons,"executionPermission":false,
            "revision":self.revision.map(Project::project),"inspection":self.inspection.map(Project::project),
            "requiresAudit":self.requires_audit,"ceiling":self.ceiling.map(|value| json!({
                "operations":value.operations,"inputBytes":value.input_bytes.to_string(),
                "outputBytes":value.output_bytes.to_string(),"wallTimeMillis":value.wall_time_millis.to_string()}))})
    }
}
