//! Bounded original caller inputs; installed descriptors supply all authority.
use latent_core::{
    transaction_contract::{CommandFingerprint, Precondition, Value},
    PlatformError,
};
use latent_node::transaction_runtime::command_completion::CommandRetry;

pub struct StateRequest {
    pub(super) kind: RequestKind,
}
pub(super) enum RequestKind {
    Command {
        client_id: String,
        conditions: Vec<Precondition>,
        business_metadata: Vec<(String, String)>,
        retry: Option<CommandRetry>,
    },
    Query {
        minimum_view: Option<Vec<u8>>,
    },
}
impl StateRequest {
    /// Business metadata accepts only the reviewed HTTP method/path/query.
    /// The prepared component supplies canonical typed input bytes later.
    pub fn command(
        client_id: String,
        conditions: Vec<Precondition>,
        business_metadata: Vec<(String, String)>,
        retry: Option<CommandRetry>,
    ) -> Result<Self, PlatformError> {
        client_key(&client_id)?;
        for (name, value) in &business_metadata {
            if !matches!(name.as_str(), "http-method" | "http-path" | "http-query")
                || value.chars().any(char::is_control)
                || (name == "http-method"
                    && !matches!(value.as_str(), "POST" | "PUT" | "PATCH" | "DELETE"))
            {
                return Err(super::denied());
            }
        }
        CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: Value {
                bytes: Vec::new(),
                media_type: "application/vnd.latent.wit-values.v1+json".into(),
                metadata: business_metadata.clone(),
            },
            expected_versions: conditions.clone(),
        }
        .visit_identity_bytes(|_| ())
        .map_err(|_| super::denied())?;
        Ok(Self {
            kind: RequestKind::Command {
                client_id,
                conditions,
                business_metadata,
                retry,
            },
        })
    }

    pub fn query(minimum_view: Option<Vec<u8>>) -> Result<Self, PlatformError> {
        if minimum_view
            .as_ref()
            .is_some_and(|view| view.len() != latent_state::session::version::VIEW_TOKEN_BYTES)
        {
            return Err(super::denied());
        }
        Ok(Self {
            kind: RequestKind::Query { minimum_view },
        })
    }
}
pub(super) fn client_key(value: &str) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        return Err(super::denied());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn command_ids_and_business_metadata_exclude_credentials_and_duplicates() {
        assert!(StateRequest::command(
            "a._-9".into(),
            vec![],
            vec![("http-method".into(), "POST".into())],
            None
        )
        .is_ok());
        for id in [String::new(), "a".repeat(129), "a%2fb".into(), "é".into()] {
            assert!(StateRequest::command(id, vec![], vec![], None).is_err());
        }
        for fields in [
            vec![("authorization".into(), "secret".into())],
            vec![("http-method".into(), "GET".into())],
            vec![("http-path".into(), "x\r\ny".into())],
            vec![
                ("http-method".into(), "POST".into()),
                ("http-method".into(), "POST".into()),
            ],
        ] {
            assert!(StateRequest::command("key".into(), vec![], fields, None).is_err());
        }
    }
    #[test]
    fn query_preserves_absence_and_full_original_view_bytes() {
        assert!(matches!(
            StateRequest::query(None).unwrap().kind,
            RequestKind::Query { minimum_view: None }
        ));
        for size in [0, 16, 51, 66, 68, 257] {
            assert!(StateRequest::query(Some(vec![1; size])).is_err());
        }
        let bytes = vec![1; latent_state::session::version::VIEW_TOKEN_BYTES];
        let RequestKind::Query {
            minimum_view: Some(actual),
        } = StateRequest::query(Some(bytes.clone())).unwrap().kind
        else {
            panic!("original view absent");
        };
        assert_eq!(actual, bytes);
    }
}
