use std::collections::BTreeMap;

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

#[derive(Serialize)]
pub(super) struct Attempt {
    pub schema: &'static str,
    pub phase: &'static str,
    pub index: String,
    pub batch: String,
    pub activation_id: String,
    pub service: String,
    pub scheduled_nanos: String,
    pub dispatch_nanos: Option<String>,
    pub completed_nanos: String,
    pub dispatch_lag_nanos: Option<String>,
    pub request_deadline_unix_millis: String,
    pub deadline_nanos: String,
    pub absolute_deadline_quantization_nanos: String,
    pub grpc_timeout_header: Option<String>,
    pub grpc_timeout_nanos: Option<String>,
    pub overshoot_nanos: String,
    pub latency_nanos: Option<String>,
    pub outcome: &'static str,
    pub code: Option<String>,
    pub semantic_match: Option<bool>,
    pub rpc_received: bool,
    pub response: Option<Value>,
}

#[derive(Default)]
pub(super) struct Counts {
    pub attempts: u64,
    pub dispatched: u64,
    pub received: u64,
    pub successful: u64,
    pub semantic_mismatches: u64,
    pub outcomes: BTreeMap<&'static str, u64>,
    pub first_scheduled: Option<u64>,
    pub last_completed: u64,
}

impl Counts {
    pub fn observe(&mut self, row: &Attempt) {
        self.attempts += 1;
        self.dispatched += u64::from(row.dispatch_nanos.is_some());
        self.received += u64::from(row.rpc_received);
        self.successful += u64::from(row.outcome == "success");
        self.semantic_mismatches += u64::from(row.semantic_match == Some(false));
        *self.outcomes.entry(row.outcome).or_default() += 1;
        let scheduled = row.scheduled_nanos.parse().expect("collector timestamp");
        self.first_scheduled = Some(self.first_scheduled.map_or(scheduled, |v| v.min(scheduled)));
        self.last_completed = self
            .last_completed
            .max(row.completed_nanos.parse().expect("collector timestamp"));
    }

    pub fn value(&self) -> Value {
        let elapsed = self
            .last_completed
            .saturating_sub(self.first_scheduled.unwrap_or(0));
        serde_json::json!({
            "attempts":self.attempts.to_string(),"dispatched":self.dispatched.to_string(),
            "undispatched":(self.attempts-self.dispatched).to_string(),
            "received":self.received.to_string(),"successful":self.successful.to_string(),
            "semantic_mismatches":self.semantic_mismatches.to_string(),
            "outcomes":self.outcomes.iter().map(|(key,value)|(*key,value.to_string())).collect::<BTreeMap<_,_>>(),
            "first_scheduled_nanos":self.first_scheduled.map(|v|v.to_string()),
            "last_completed_nanos":self.last_completed.to_string(),"elapsed_nanos":elapsed.to_string(),
            "throughput":{"completed_attempts":self.attempts.to_string(),"successful_responses":self.successful.to_string(),"elapsed_nanos":elapsed.to_string()}
        })
    }
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
