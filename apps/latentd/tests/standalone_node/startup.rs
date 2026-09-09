use latent_node::{NodeTopologyEntry, ResourceOwnership};
use latent_wire::management::{node_inventory_from_proto, proto};
use proto::node_service_client::NodeServiceClient;
use proto::release_service_client::ReleaseServiceClient;
use tonic::{Code, Request};

use super::support::{self, request, CALLER, FOREIGN, NODE_ID, OPERATOR};

pub fn scenario() {
    let directory = tempfile::tempdir().expect("isolated durable node root");
    let config = support::write_config(directory.path());
    let runtimes = support::Runtimes::new();
    runtimes.invocation.block_on(async {
        for _ in 0..2 {
            let node = runtimes.start(support::settings(&config)).await;
            assert!(node.is_running());
            assert_ne!(node.endpoint().port(), 0);
            let channel = support::channel(&node).await;
            let mut nodes = NodeServiceClient::new(channel.clone());
            let get = || proto::GetNodeRequest {
                node_id: NODE_ID.to_owned(),
            };
            assert_eq!(
                nodes
                    .get_node(Request::new(get()))
                    .await
                    .unwrap_err()
                    .code(),
                Code::Unauthenticated
            );
            assert_eq!(
                nodes
                    .get_node(request("wrong-credential", get()))
                    .await
                    .unwrap_err()
                    .code(),
                Code::Unauthenticated
            );
            let mut spoofed = request(CALLER, get());
            spoofed
                .metadata_mut()
                .insert("latent.node.operator", "true".parse().unwrap());
            assert_eq!(
                nodes.get_node(spoofed).await.unwrap_err().code(),
                Code::PermissionDenied
            );
            assert_eq!(
                nodes
                    .get_node(request(FOREIGN, get()))
                    .await
                    .unwrap_err()
                    .code(),
                Code::PermissionDenied
            );
            let inventory = nodes
                .get_node(request(OPERATOR, get()))
                .await
                .expect("operator inventory")
                .into_inner()
                .inventory
                .expect("current node");
            let inventory =
                node_inventory_from_proto(inventory).expect("honest inventory conversion");
            assert_eq!(
                inventory.node.endpoint,
                format!("http://{}", node.endpoint())
            );
            assert_eq!(inventory.route_generation.0, 0);
            assert_eq!(inventory.cell_capacity.len(), 1);
            assert_eq!(
                (
                    inventory.cell_capacity[0].total,
                    inventory.cell_capacity[0].available
                ),
                (1, 1)
            );
            assert!(inventory.cache_summary.available);
            assert_eq!(inventory.cache_summary.entries, 0);
            assert!(inventory.cache_entries.is_empty());
            assert!(inventory.topology.available && inventory.topology.complete);
            assert_eq!(inventory.topology.entries.len(), 22);
            assert_compiler_topology(&inventory.topology.entries);
            assert_cleanup_topology(&inventory.topology.entries);
            for row in inventory
                .topology
                .entries
                .iter()
                .filter(|row| row.ownership == ResourceOwnership::ServiceResident)
            {
                assert_eq!((row.configured_count, row.active_count), (0, Some(0)));
            }
            let mut releases = ReleaseServiceClient::new(channel.clone());
            let listed = releases
                .list_releases(request(OPERATOR, proto::ListReleasesRequest::default()))
                .await
                .expect("empty scoped release list")
                .into_inner();
            assert!(listed.releases.is_empty());
            drop(releases);
            drop(nodes);
            drop(channel);
            support::stop(node).await;
        }
    });
    runtimes.finish();
}

fn assert_compiler_topology(entries: &[NodeTopologyEntry]) {
    let compiler = entries
        .iter()
        .find(|row| row.name == "wasmtime-compiler")
        .expect("actual compiler topology");
    assert_eq!(compiler.kind, "thread");
    assert_eq!(compiler.ownership, ResourceOwnership::NodeFixed);
    assert!(compiler.configured_count > 0);
    assert!(compiler
        .active_count
        .is_some_and(|live| live <= compiler.configured_count));
}

fn assert_cleanup_topology(entries: &[NodeTopologyEntry]) {
    for (name, kind, configured, active) in [
        ("invocation-cleanup-driver", "task", 1, 1),
        // The fixture has one cell plus two queue slots and no Invoke requests.
        ("invocation-cleanup-slots", "continuation", 3, 0),
    ] {
        let mut matching = entries.iter().filter(|row| row.name == name);
        let row = matching.next().expect("actual cleanup topology");
        assert!(matching.next().is_none(), "duplicate cleanup row: {name}");
        assert_eq!(row.kind, kind);
        assert_eq!(row.ownership, ResourceOwnership::NodeFixed);
        assert_eq!(
            (row.configured_count, row.active_count),
            (configured, Some(active))
        );
    }
}
