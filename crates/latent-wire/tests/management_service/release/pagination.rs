use tonic::Code;

use super::{artifact, list, proto, publish, upload, Harness, ManagementLimits};

fn page(token: Option<String>) -> proto::PageRequest {
    proto::PageRequest {
        page_size: 1,
        page_token: token,
    }
}

#[tokio::test]
async fn multirow_release_pages_preserve_publication_order_across_page_sizes() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut expected = std::collections::BTreeSet::new();
    for ordinal in 0..32 {
        let release = publish(
            &harness,
            "alice",
            upload(&artifact("acme", "echo", &format!("cohort-{ordinal:02}"))),
        )
        .await
        .unwrap();
        expected.insert(release.digest);
    }
    let all = list(
        &harness,
        "alice",
        Some("echo"),
        Some(proto::PageRequest {
            page_size: 64,
            page_token: None,
        }),
    )
    .await
    .unwrap();
    assert!(all.page.unwrap().next_page_token.is_none());
    assert_eq!(all.releases.len(), 32);
    assert_eq!(
        all.releases
            .iter()
            .map(|row| row.digest.clone())
            .collect::<std::collections::BTreeSet<_>>(),
        expected
    );
    assert!(
        all.releases
            .windows(2)
            .any(|pair| pair[0].digest > pair[1].digest),
        "fixture distinguishes component order from publication order"
    );
    let mut token = None;
    let mut collected = Vec::new();
    for _ in 0..5 {
        let response = list(
            &harness,
            "alice",
            Some("echo"),
            Some(proto::PageRequest {
                page_size: 7,
                page_token: token,
            }),
        )
        .await
        .unwrap();
        collected.extend(response.releases);
        token = response.page.unwrap().next_page_token;
        if token.is_none() {
            break;
        }
    }
    assert!(token.is_none());
    assert_eq!(collected, all.releases);
    harness.shutdown().await;
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
    // Format-2 cursors order exact publications, whose component digests need
    // not be ordered (and may even be identical). Every matching row is returned.
    let actual = std::collections::BTreeSet::from([
        first.releases[0].digest.clone(),
        second.releases[0].digest.clone(),
    ]);
    let expected = std::collections::BTreeSet::from([
        artifact("acme", "echo", "page-a")
            .descriptor
            .release_digest
            .0,
        artifact("acme", "echo", "page-b")
            .descriptor
            .release_digest
            .0,
    ]);
    assert_eq!(actual, expected);
    let repeat = list(&harness, "alice", Some("echo"), None).await.unwrap();
    assert_eq!(repeat.releases, first.releases);
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
