use latent_artifacts::content_digest;
use latent_core::{ContractId, FunctionId, PlatformErrorCode, ServiceId, TenantId};
use latent_routing::InvocationTarget;

use super::super::{search::selection_hash, DirectoryDeploymentRepositoryConfig};
use super::fixtures::*;

// The previous implementation allocated the complete frame then parsed its
// hexadecimal SHA-256 prefix. Keep that independent oracle in tests only.
fn legacy_hash(target: &InvocationTarget, key: &str) -> u64 {
    let mut framed = b"lsf-route-selection-v1\0".to_vec();
    for value in [
        target.tenant.0.as_str(),
        target.service.0.as_str(),
        target.route.as_deref().unwrap_or("default"),
        target.contract.0.as_str(),
        target.function.0.as_str(),
        key,
    ] {
        framed.extend_from_slice(&(value.len() as u64).to_be_bytes());
        framed.extend_from_slice(value.as_bytes());
    }
    let digest = content_digest(&framed);
    u64::from_str_radix(&digest.0[7..23], 16).unwrap()
}

#[test]
fn streamed_selection_preserves_original_framing_unicode_and_empty_keys() {
    for tenant in ["alice", "a:b", "\u{03bb}\u{4e16}"] {
        for service in ["echo", "service|name", "\u{00e9}"] {
            for route in [None, Some("default"), Some("named"), Some("a:b|c")] {
                let mut target = target(tenant, route);
                target.service = ServiceId(service.to_owned());
                for key in ["", "stable", "a\0b", "a:b|c", "\u{00e9}\u{03bb}"] {
                    assert_eq!(selection_hash(&target, key), legacy_hash(&target, key));
                }
                target.contract = ContractId("other:api/api@1.0.0".to_owned());
                target.function = FunctionId("other-function".to_owned());
                assert_eq!(
                    selection_hash(&target, "stable"),
                    legacy_hash(&target, "stable")
                );
            }
        }
    }
}

#[test]
fn packed_weighted_routes_match_reference_and_cover_each_bucket_boundary() {
    let releases = Releases::default();
    let first = releases.add("first");
    let second = releases.add("second");
    let mut desired = vec![
        deployment("zulu", "alice", &first),
        deployment("alpha", "alice", &second),
        deployment("middle", "alice", &first),
    ];
    for (item, weight) in desired.iter_mut().zip([2, 7, 11]) {
        item.route_weight = weight;
    }
    let catalog = compile(&releases, desired, 1, None).unwrap();
    let mut saw_bucket = [false; 20];
    let target = target("alice", None);
    let route = catalog
        .route_views()
        .find(|route| route.id() == "default")
        .unwrap();
    let records = route.revisions().collect::<Vec<_>>();
    assert!(records
        .windows(2)
        .all(|pair| pair[0].revision < pair[1].revision));
    for number in 0..512 {
        let key = format!("routing-{number}");
        let bucket = legacy_hash(&target, &key) % 20;
        saw_bucket[usize::try_from(bucket).unwrap()] = true;
        let mut total = 0;
        let expected = records
            .iter()
            .find(|record| {
                total += u64::from(record.deployment.route_weight);
                bucket < total
            })
            .unwrap();
        let actual = catalog
            .resolve(
                &target,
                Some(&key),
                DirectoryDeploymentRepositoryConfig::default(),
            )
            .unwrap();
        assert_eq!(actual.revision, expected.revision);
        assert_eq!(actual.release, expected.deployment.release);
        assert_eq!(actual.attributes, expected.attributes);
    }
    assert!(saw_bucket.into_iter().all(|seen| seen));
    assert_eq!(
        catalog
            .resolve(
                &target,
                None,
                DirectoryDeploymentRepositoryConfig::default()
            )
            .unwrap(),
        catalog
            .resolve(
                &target,
                Some(""),
                DirectoryDeploymentRepositoryConfig::default()
            )
            .unwrap()
    );
    for record in &catalog.records {
        let named = target_named(&record.deployment.id.0);
        assert_eq!(
            catalog
                .resolve(
                    &named,
                    Some("any"),
                    DirectoryDeploymentRepositoryConfig::default()
                )
                .unwrap()
                .revision,
            record.revision
        );
    }
}

fn target_named(name: &str) -> InvocationTarget {
    target("alice", Some(name))
}

#[test]
fn route_members_are_independent_of_endpoint_members_and_errors_keep_their_order() {
    let releases = Releases::default();
    let first = releases.add("first");
    let second = releases.add("second");
    let extra = ContractId("example:extra/api@1.0.0".to_owned());
    {
        let mut values = releases.values.write().unwrap();
        let artifact = values.get_mut(&second).unwrap();
        artifact.manifest.exports[0].contract = extra.clone();
        artifact.contracts[0].id = extra.clone();
        artifact.contracts[0].package_name = "example:extra".to_owned();
    }
    let catalog = compile(
        &releases,
        vec![
            deployment("blue", "alice", &first),
            deployment("green", "alice", &second),
            deployment("bob", "bob", &first),
        ],
        1,
        None,
    )
    .unwrap();
    let route = catalog
        .tenant_routes(&TenantId("alice".to_owned()))
        .find(|route| route.id() == "default")
        .unwrap();
    assert_eq!(route.revisions().len(), 2);
    let mut requested = target("alice", None);
    requested.contract = extra;
    assert_eq!(
        catalog
            .resolve(
                &requested,
                None,
                DirectoryDeploymentRepositoryConfig::default()
            )
            .unwrap()
            .release,
        second
    );
    for (route, service, function, code, message) in [
        (
            Some("blue"),
            "echo",
            "echo",
            PlatformErrorCode::IncompatibleContract,
            "contract-or-function-not-exported",
        ),
        (
            Some("absent"),
            "echo",
            "echo",
            PlatformErrorCode::RouteUnavailable,
            "route-not-found",
        ),
        (
            None,
            "missing",
            "echo",
            PlatformErrorCode::RouteUnavailable,
            "route-not-found",
        ),
        (
            None,
            "missing",
            "",
            PlatformErrorCode::InvalidArgument,
            "invalid-invocation-target",
        ),
    ] {
        requested.route = route.map(str::to_owned);
        requested.service = ServiceId(service.to_owned());
        requested.function = FunctionId(function.to_owned());
        let error = catalog
            .resolve(
                &requested,
                None,
                DirectoryDeploymentRepositoryConfig::default(),
            )
            .unwrap_err();
        assert_eq!((error.code, error.message.as_str()), (code, message));
    }
}
