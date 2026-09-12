use super::proto;
use latent_core::ErrorDetail;

pub(super) struct ReleaseDetail {
    operation_id: String,
    disposition: &'static str,
    reason: &'static str,
    generation: Option<u64>,
}

impl ReleaseDetail {
    pub(super) fn parse(source: &ErrorDetail) -> Option<Self> {
        if source.fields.keys().any(|v| {
            !matches!(
                v.as_str(),
                "operation_id" | "disposition" | "reason" | "generation"
            )
        }) {
            return None;
        }
        let operation_id = source.fields.get("operation_id")?;
        if operation_id.is_empty()
            || operation_id.len() > 128
            || operation_id
                .chars()
                .any(|v| v.is_whitespace() || v.is_control())
        {
            return None;
        }
        let disposition = match source.fields.get("disposition")?.as_str() {
            "committed" => "committed",
            "rejected" => "rejected",
            "uncertain" => "uncertain",
            _ => return None,
        };
        let reason = REASONS
            .iter()
            .copied()
            .find(|v| Some(*v) == source.fields.get("reason").map(String::as_str))?;
        let generation = if let Some(value) = source.fields.get("generation") {
            let parsed = super::generation(value)?;
            if parsed.to_string() != *value {
                return None;
            }
            Some(parsed)
        } else {
            None
        };
        Some(Self {
            operation_id: operation_id.clone(),
            disposition,
            reason,
            generation,
        })
    }
    pub(super) fn retained_cost(&self) -> usize {
        8 * 128
            + "release-operationoperation_iddispositionreasongeneration".len()
            + self.operation_id.len()
            + self.disposition.len()
            + self.reason.len()
            + 20
    }
    pub(super) fn into_proto(self) -> proto::ErrorDetail {
        let mut fields = std::collections::HashMap::from([
            ("operation_id".to_owned(), self.operation_id),
            ("disposition".to_owned(), self.disposition.to_owned()),
            ("reason".to_owned(), self.reason.to_owned()),
        ]);
        if let Some(value) = self.generation {
            fields.insert("generation".to_owned(), value.to_string());
        }
        proto::ErrorDetail {
            kind: "release-operation".to_owned(),
            fields,
        }
    }
}

const REASONS: &[&str] = &[
    "admitted",
    "evidence-renewed",
    "operator-revocation",
    "security-incident",
    "corrupt-content",
    "superseded",
    "end-of-support",
    "operator-retirement",
    "invalid-package",
    "integrity-mismatch",
    "incompatible-contract",
    "evidence-rejected",
    "policy-denied",
    "release-revoked",
    "release-retired",
    "generation-conflict",
    "content-conflict",
    "mutation-uncertain",
    "evidence-reclamation-pending",
];
