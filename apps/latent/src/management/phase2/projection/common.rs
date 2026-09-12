//! Closed typed projection; all protobuf u64 fields remain decimal strings.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

impl Project for proto::AuditAck {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.status == 0 || proto::AuditAckStatus::try_from(self.status).is_err() {
            return Err(invalid_response());
        }
        if self.attempt_sequence == Some(0)
            || ((self.status == proto::AuditAckStatus::Durable as i32
                || self.status == proto::AuditAckStatus::OutcomeUnknown as i32)
                && self.attempt_sequence.is_none())
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "status": json!(proto::AuditAckStatus::try_from(self.status).expect("validated enum").as_str_name()),
        "attemptSequence": self.attempt_sequence.map(|value| json!(value.to_string())),
        })
    }
}

impl Project for proto::PageResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.next_page_token {
            b.text(value, 8192)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "nextPageToken": self.next_page_token.map(|value| json!(value)),
        })
    }
}
