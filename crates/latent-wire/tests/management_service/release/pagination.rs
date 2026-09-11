use tonic::Code;

use super::{artifact, list, proto, publish, upload, Harness, ManagementLimits};

fn page(token: Option<String>) -> proto::PageRequest {
    proto::PageRequest {
        page_size: 1,
        page_token: token,
    }
}

#[tokio::test]
async fn release_pages_are_scoped_ordered_and_expire_only_on_visible_publication() {
    let harness = Harness::new(ManagementLimits {
        default_page_size: 1,
        ..ManagementLimits::default()
    })
    .await;
    let first_upload = upload(&artifact("acme", "echo", "page-a"));
    publish(&harness, "alice", first_upload.clone())
        .await
        .unwrap();
    for (identity, tenant, service, marker) in [
        ("alice", "acme", "echo", "page-b"),
        ("alice", "acme", "another", "page-c"),
        ("bob", "other", "echo", "page-other"),
    ] {
        publish(
            &harness,
            identity,
            upload(&artifact(tenant, service, marker)),
        )
        .await
        .unwrap();
    }
    let first = list(&harness, "alice", Some("echo"), None).await.unwrap();
    assert_eq!(first.releases.len(), 1);
    let token = first.page.unwrap().next_page_token.unwrap();
    publish(&harness, "alice", first_upload).await.unwrap();
    let second = list(
        &harness,
        "alice",
        Some("echo"),
        Some(page(Some(token.clone()))),
    )
    .await
    .unwrap();
    assert_eq!(second.releases.len(), 1);
    assert!(second.page.unwrap().next_page_token.is_none());
    assert!(first.releases[0].digest < second.releases[0].digest);
    for scope in [Some("another"), None] {
        assert_eq!(
            list(&harness, "alice", scope, Some(page(Some(token.clone()))))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    assert_eq!(
        list(
            &harness,
            "bob",
            Some("echo"),
            Some(page(Some(token.clone())))
        )
        .await
        .unwrap_err()
        .code(),
        Code::InvalidArgument
    );
    let mut tampered = token.clone();
    tampered.push('x');
    assert_eq!(
        list(&harness, "alice", Some("echo"), Some(page(Some(tampered))))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    publish(
        &harness,
        "alice",
        upload(&artifact("acme", "echo", "page-new")),
    )
    .await
    .unwrap();
    assert_eq!(
        list(&harness, "alice", Some("echo"), Some(page(Some(token))))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    let zero = list(
        &harness,
        "alice",
        None,
        Some(proto::PageRequest {
            page_size: 0,
            page_token: None,
        }),
    )
    .await
    .unwrap();
    assert_eq!(zero.releases.len(), 1);
    assert_eq!(
        list(&harness, "bob", None, None).await.unwrap().releases[0]
            .tenant
            .as_deref(),
        Some("other")
    );
    harness.shutdown().await;
}
