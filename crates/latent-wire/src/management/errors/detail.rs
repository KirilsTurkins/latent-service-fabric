use latent_core::ErrorDetail;
mod release;

use super::super::{proto, ManagementLimits};

const MAX_SOURCE_FIELDS: usize = 32;
// Fixed protocol words and decimal u64 stamps do not consume caller-name limits.
const DIAGNOSTIC_STRING_FLOOR: usize = 64;

pub(super) enum PublicDetail {
    Release(release::ReleaseDetail),
    Catalog(&'static str),
    Mutation {
        object_generation: u64,
        catalog_generation: u64,
        operation: &'static str,
    },
}

impl PublicDetail {
    pub(super) fn parse(source: &ErrorDetail, limits: &ManagementLimits) -> Option<Self> {
        let string_bound = limits.max_string_bytes.max(DIAGNOSTIC_STRING_FLOOR);
        if source.kind.capacity() > string_bound
            || source.fields.len() > limits.auth.max_platform_error_fields.min(MAX_SOURCE_FIELDS)
        {
            return None;
        }
        // Check all retained source allocations before field lookup or reconstruction.
        if source.fields.iter().any(|(key, value)| {
            let value_bound = if source.kind == "release-operation" && key == "operation_id" {
                128.min(limits.max_id_bytes)
            } else if source.kind == "deployment-mutation" && key == "deployment_id" {
                limits.max_id_bytes
            } else {
                string_bound
            };
            key.capacity() > string_bound || value.capacity() > value_bound
        }) {
            return None;
        }
        match source.kind.as_str() {
            "release-operation" => release::ReleaseDetail::parse(source).map(Self::Release),
            "deployment-catalog" => {
                let reason = source.fields.get("reason")?;
                CATALOG_REASONS
                    .iter()
                    .copied()
                    .find(|candidate| *candidate == reason.as_str())
                    .map(Self::Catalog)
            }
            "deployment-mutation" => {
                if source.fields.get("committed")? != "true" {
                    return None;
                }
                let operation = match source.fields.get("operation")?.as_str() {
                    "apply" => "apply",
                    "delete" => "delete",
                    _ => return None,
                };
                Some(Self::Mutation {
                    object_generation: generation(source.fields.get("object_generation")?)?,
                    catalog_generation: generation(source.fields.get("catalog_generation")?)?,
                    operation,
                })
            }
            _ => None,
        }
    }

    /// Includes canonical string storage and conservative hash-map buckets/slack.
    /// Source strings and their spare capacities are never moved into the result.
    pub(super) fn retained_cost(&self) -> usize {
        match self {
            Self::Release(value) => value.retained_cost(),
            Self::Catalog(reason) => {
                4 * 128 + "deployment-catalog".len() + "reason".len() + reason.len()
            }
            Self::Mutation { .. } => {
                8 * 128
                    + "deployment-mutation".len()
                    + "object_generationcatalog_generationoperationcommitted".len()
                    + 20
                    + 20
                    + "delete".len()
                    + "true".len()
            }
        }
    }

    pub(super) fn into_proto(self) -> proto::ErrorDetail {
        match self {
            Self::Release(value) => value.into_proto(),
            Self::Catalog(reason) => proto::ErrorDetail {
                kind: "deployment-catalog".to_owned(),
                fields: [("reason".to_owned(), reason.to_owned())]
                    .into_iter()
                    .collect(),
            },
            Self::Mutation {
                object_generation,
                catalog_generation,
                operation,
            } => proto::ErrorDetail {
                kind: "deployment-mutation".to_owned(),
                fields: [
                    (
                        "object_generation".to_owned(),
                        object_generation.to_string(),
                    ),
                    (
                        "catalog_generation".to_owned(),
                        catalog_generation.to_string(),
                    ),
                    ("operation".to_owned(), operation.to_owned()),
                    ("committed".to_owned(), "true".to_owned()),
                ]
                .into_iter()
                .collect(),
            },
        }
    }
}

fn generation(value: &str) -> Option<u64> {
    if value.is_empty() || value.len() > 20 || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    value.parse().ok().filter(|value| *value != 0)
}

// Exact public reasons emitted by the current DirectoryDeploymentRepository.
const CATALOG_REASONS: &[&str] = &[
    "deployment-generation-conflict",
    "deployment-scope-conflict",
    "deployment-not-found",
    "deployment-count-limit",
    "invalid-deployment-target",
    "catalog-root-already-owned",
    "catalog-path-durability-uncertain",
    "catalog-state-byte-limit",
    "snapshot-publication-busy",
    "route-index-limit",
    "route-not-found",
    "route-generation-not-retained",
    "route-generation-exhausted",
    "missing-tenant",
    "invalid-invocation-target",
    "invalid-deployment-page-size",
    "invalid-deployment-page-scope",
    "invalid-deployment-page-token",
    "expired-deployment-page-token",
    "deployment-page-byte-limit",
    "commit-durability-uncertain",
    "stale-route-generation",
];
