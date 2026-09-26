use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::__serde_json as serde_json;
use latent_policy::capability::ResourceRequest;
use serde::Deserialize;

pub fn parse_inspection_resource(bytes: &[u8]) -> Result<ResourceRequest, PlatformError> {
    let resource = ResourceRequest::parse(bytes)?;
    if matches!(
        resource,
        ResourceRequest::Context | ResourceRequest::Clock | ResourceRequest::Random
    ) {
        serde_json::from_slice::<UnitResource>(bytes).map_err(|_| PlatformError {
            code: PlatformErrorCode::InvalidArgument,
            message: "invalid-inspection-resource".into(),
            retryable: false,
            details: Vec::new(),
        })?;
    }
    Ok(resource)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UnitResource {
    #[serde(rename = "kind")]
    _kind: UnitKind,
}

#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum UnitKind {
    Context,
    Clock,
    Random,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_resources_reject_unknown_and_duplicate_fields_at_every_management_boundary() {
        for kind in ["context", "clock", "random"] {
            assert!(
                parse_inspection_resource(format!(r#"{{"kind":"{kind}"}}"#).as_bytes()).is_ok()
            );
            for extra in [
                r#""principal":"administrator""#,
                r#""label":"unused""#,
                r#""kind":"random""#,
            ] {
                assert!(parse_inspection_resource(
                    format!(r#"{{"kind":"{kind}",{extra}}}"#).as_bytes()
                )
                .is_err());
            }
        }
    }
}
