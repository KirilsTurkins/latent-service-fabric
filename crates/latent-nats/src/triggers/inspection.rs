//! Read-only observation of a configured input using its original TLS authority.
use super::{consumer, inbox, owner::InstallationMode, NatsTriggers, TriggerConfig};
use crate::{deferred::qualification, network, EventError, NatsCredential, Result};
use latent_capabilities::broker::pools::ProviderPools;
use serde::{Deserialize, Serialize};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrokerInputProgress {
    stream: String,
    stream_created: String,
    consumer: String,
    consumer_created: String,
    delivered_consumer_sequence: String,
    #[serde(serialize_with = "sequence_text")]
    delivered_stream_sequence: u64,
    acknowledgement_floor_consumer_sequence: String,
    acknowledgement_floor_stream_sequence: String,
    pending: String,
    acknowledgement_pending: String,
    waiting_pulls: String,
}

impl BrokerInputProgress {
    #[must_use]
    pub const fn delivered_stream_sequence(&self) -> u64 {
        self.delivered_stream_sequence
    }
}

#[expect(
    clippy::trivially_copy_pass_by_ref,
    reason = "Serde passes a borrowed field"
)]
fn sequence_text<S: serde::Serializer>(
    sequence: &u64,
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    serializer.collect_str(sequence)
}

#[derive(Deserialize)]
struct Progress<'a> {
    #[serde(rename = "type")]
    kind: &'a str,
    created: &'a str,
    delivered: Sequence,
    ack_floor: Sequence,
    num_pending: u64,
    num_ack_pending: u64,
    num_waiting: u64,
}

#[derive(Deserialize)]
struct Sequence {
    consumer_seq: u64,
    stream_seq: u64,
}

/// This handle exposes neither a pull nor an acknowledgement operation.
pub struct NatsTriggerInspector(NatsTriggers);

impl NatsTriggerInspector {
    pub fn install(
        pools: Arc<ProviderPools>,
        provider: &str,
        epoch: u64,
        config: TriggerConfig,
        credentials: Vec<NatsCredential>,
    ) -> Result<Self> {
        if config
            .bindings
            .iter()
            .any(|binding| binding.transaction.is_none())
        {
            return Err(EventError::PermissionDenied);
        }
        NatsTriggers::install_inner(
            pools,
            provider,
            epoch,
            0,
            config,
            credentials,
            InstallationMode::Inspection,
        )
        .map(Self)
    }

    /// An observation describes the live broker. It supplies no restore or ack authority.
    pub async fn inspect(
        mut self,
        tenant: &str,
        binding_id: &str,
        deadline: Instant,
    ) -> Result<BrokerInputProgress> {
        let poller = &mut self.0;
        let index = poller
            .config
            .bindings
            .iter()
            .position(|binding| binding.id == binding_id && binding.tenant == tenant)
            .ok_or(EventError::PermissionDenied)?;
        let tenant_index = poller
            .tenants
            .iter()
            .position(|row| row.bindings.contains(&index))
            .ok_or(EventError::PermissionDenied)?;
        let deadline = deadline
            .min(Instant::now() + Duration::from_millis(poller.config.operation_timeout_millis));
        let (_cancel, mut stop) = tokio::sync::watch::channel(false);
        let mut opened = poller
            .open(tenant_index, index, deadline, &mut stop)
            .await?;
        let binding = &poller.config.bindings[index];
        let reply = format!("{}.0000000000000001", poller.namespace);
        let connection = opened.connection.resource();
        inbox::qualify(connection, &opened.request, binding, &reply).await?;
        let frame = consumer::read_info(connection, &opened.request, binding, &reply).await?;
        consumer::validate(frame.payload(), binding, &poller.config)?;
        let progress = decode_progress(frame.payload())?;
        inbox::qualify(connection, &opened.request, binding, &reply).await?;
        let credential = &poller.credentials[poller.tenants[tenant_index].credential];
        network::check_current(credential, &opened.auth.stamp)?;
        let selected = binding
            .transaction
            .as_ref()
            .ok_or(EventError::PermissionDenied)?;
        Ok(BrokerInputProgress {
            stream: binding.stream.clone(),
            stream_created: selected.qualification.stream_created.clone(),
            consumer: binding.consumer.clone(),
            consumer_created: progress.created.into(),
            delivered_consumer_sequence: progress.delivered.consumer_seq.to_string(),
            delivered_stream_sequence: progress.delivered.stream_seq,
            acknowledgement_floor_consumer_sequence: progress.ack_floor.consumer_seq.to_string(),
            acknowledgement_floor_stream_sequence: progress.ack_floor.stream_seq.to_string(),
            pending: progress.num_pending.to_string(),
            acknowledgement_pending: progress.num_ack_pending.to_string(),
            waiting_pulls: progress.num_waiting.to_string(),
        })
    }
}

fn decode_progress(bytes: &[u8]) -> Result<Progress<'_>> {
    let result: Progress<'_> =
        serde_json::from_slice(bytes).map_err(|_| EventError::Unavailable)?;
    if result.kind != "io.nats.jetstream.api.v1.consumer_info_response"
        || !qualification::created_at(result.created)
        || result.ack_floor.consumer_seq > result.delivered.consumer_seq
        || result.ack_floor.stream_seq > result.delivered.stream_seq
        || result.num_ack_pending > 1
        || result.num_waiting > 1
    {
        return Err(EventError::PermissionDenied);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn progress_keeps_full_width_sequences_and_refuses_an_inconsistent_broker_reply() {
        let mut info = json!({
            "type": "io.nats.jetstream.api.v1.consumer_info_response",
            "created": "2026-11-20T10:23:45.123Z",
            "delivered": {"consumer_seq": u64::MAX, "stream_seq": u64::MAX},
            "ack_floor": {"consumer_seq": u64::MAX - 1, "stream_seq": u64::MAX - 1},
            "num_pending": 0, "num_ack_pending": 1, "num_waiting": 0
        });
        let bytes = serde_json::to_vec(&info).unwrap();
        let exact = decode_progress(&bytes).unwrap();
        assert_eq!(exact.delivered.stream_seq, u64::MAX);
        assert_eq!(exact.ack_floor.stream_seq, u64::MAX - 1);
        info["delivered"]["stream_seq"] = 1.into();
        assert!(decode_progress(&serde_json::to_vec(&info).unwrap()).is_err());
        info["delivered"]["stream_seq"] = u64::MAX.into();
        info["created"] = "different-format".into();
        assert!(decode_progress(&serde_json::to_vec(&info).unwrap()).is_err());
    }
}
