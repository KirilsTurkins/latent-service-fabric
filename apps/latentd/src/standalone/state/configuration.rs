//! Exact boot configuration identity, without current policy or publication authority.
use sha2::{Digest, Sha256};

use crate::config::state::StateSettings;

struct Identity(Sha256);
impl Identity {
    fn number(&mut self, value: u128) {
        self.0.update(value.to_le_bytes());
    }
    fn bytes(&mut self, value: &[u8]) {
        self.number(value.len() as u128);
        self.0.update(value);
    }
    fn text(&mut self, value: &str) {
        self.bytes(value.as_bytes());
    }
    fn optional(&mut self, value: Option<&str>) {
        self.number(u128::from(value.is_some()));
        if let Some(value) = value {
            self.text(value);
        }
    }
}

/// Prevent mixed already-open catalogs/settings from selecting another state
/// root, incarnation, target, native owner envelope or checkpoint. This digest
/// is descriptive only: it is never a policy revision, receipt, or grant.
pub(super) fn identity(settings: &StateSettings) -> [u8; 32] {
    let mut result = Identity(Sha256::new());
    result.bytes(b"latent.standalone-state-config.v2\0");
    result.number(u128::from(settings.configuration_epoch));
    result.number(u128::from(settings.create_if_missing));
    result.bytes(&settings.store_identity.encode());
    result.bytes(settings.checkpoint_root.as_os_str().as_encoded_bytes());
    result.number(settings.startup_timeout.as_nanos());
    result.number(u128::from(settings.startup_work_bytes));
    storage(&mut result, settings);
    native(&mut result, settings);
    dispatcher(&mut result, settings);
    result.number(settings.tenant_quotas.len() as u128);
    for quota in &settings.tenant_quotas {
        result.text(&quota.tenant);
        let value = &quota.limits;
        for count in [
            value.state_keys,
            value.state_bytes,
            value.tombstone_keys,
            value.tombstone_bytes,
            value.result_rows,
            value.result_bytes,
            value.effect_rows,
            value.effect_bytes,
            value.payload_bytes,
            value.recovery_bytes,
            value.metadata_rows,
            value.metadata_bytes,
        ] {
            result.number(u128::from(count));
        }
    }
    result.number(settings.operations.len() as u128);
    for operation in &settings.operations {
        let names: [&str; 9] = [
            &operation.tenant.0,
            &operation.component.0,
            operation.publication.as_str(),
            &operation.contract,
            &operation.function,
            &operation.deployment,
            &operation.binding,
            &operation.companion_digest,
            &operation.result_policy,
        ];
        for text in names {
            result.text(text);
        }
        result.number(u128::from(operation.incarnation));
        result.optional(operation.entity.as_deref());
        result.optional(operation.route.as_deref());
        policies(&mut result, &operation.policies);
        result.number(u128::from(operation.deferred_http.is_some()));
        if let Some(effect) = &operation.deferred_http {
            for text in [
                &effect.requirements_digest,
                &effect.provider_id,
                &effect.provider_incarnation,
                &effect.credential_reference,
                &effect.staging_binding,
                &effect.dispatch_binding,
            ] {
                result.text(text);
            }
            policies(&mut result, &effect.staging_policies);
            policies(&mut result, &effect.dispatch_policies);
        }
    }
    result.0.finalize().into()
}

fn policies(result: &mut Identity, policies: &[String]) {
    result.number(policies.len() as u128);
    for policy in policies {
        result.text(policy);
    }
}

fn storage(result: &mut Identity, settings: &StateSettings) {
    let store = &settings.store;
    result.bytes(store.root.as_os_str().as_encoded_bytes());
    result.text(&store.file_name);
    result.number(u128::from(store.maximum_file_bytes));
    result.number(u128::from(store.create_if_missing));
    let engine = &store.engine;
    for count in [
        engine.cache_bytes,
        engine.maximum_rows,
        engine.maximum_logical_bytes,
        engine.maximum_key_bytes,
        engine.maximum_value_bytes,
        engine.maximum_batch_rows,
        engine.maximum_read_views,
    ] {
        result.number(count as u128);
    }
    result.number(engine.maximum_view_age.as_nanos());
    let io = &store.io;
    for count in [
        io.workers,
        io.queued_jobs,
        io.accepted_jobs,
        io.active_reads,
        io.active_writes,
    ] {
        result.number(count as u128);
    }
    for count in [io.retained_bytes, io.job_bytes, io.resident_bytes] {
        result.number(u128::from(count));
    }
    result.number(u128::from(io.recovery.is_some()));
    if let Some(recovery) = io.recovery {
        for count in [
            recovery.workers,
            recovery.queued_jobs,
            recovery.accepted_jobs,
        ] {
            result.number(count as u128);
        }
        result.number(u128::from(recovery.retained_bytes));
        result.number(u128::from(recovery.job_bytes));
    }
    match store.filesystem {
        latent_state::protected_store::StoreFilesystemProfile::LinuxExt4 => result.number(1),
    }
}

fn native(result: &mut Identity, settings: &StateSettings) {
    for partition in [settings.native.ordinary, settings.native.recovery] {
        result.number(partition.slots as u128);
        result.number(u128::from(partition.bytes));
        result.number(u128::from(partition.maximum_reservation_bytes));
    }
    result.number(settings.native.maximum_lifetime.as_nanos());
}

fn dispatcher(result: &mut Identity, settings: &StateSettings) {
    let dispatcher = &settings.dispatcher;
    for count in [
        dispatcher.workers,
        dispatcher.queued_jobs,
        dispatcher.accepted_jobs,
        dispatcher.maximum_command_owners,
        dispatcher.per_tenant_jobs,
        dispatcher.page_rows,
        dispatcher.page_bytes,
        dispatcher.scan_pages_per_tick,
    ] {
        result.number(count as u128);
    }
    result.number(u128::from(dispatcher.retained_bytes));
    result.number(dispatcher.poll_interval.as_nanos());
    match dispatcher.ordering {
        latent_effects::runtime::DispatchOrdering::Unordered => result.number(0),
        latent_effects::runtime::DispatchOrdering::Ordered => result.number(1),
    }
    result.number(u128::from(dispatcher.start_paused));
    result.number(u128::from(dispatcher.start_in_restore_review));
}
