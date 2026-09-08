use std::sync::Arc;

use latent_admission::{LocalQuotaProvider, NodeLoadSnapshot, NodeLoadSource};
use latent_core::{ContractId, PlatformError, RouteGeneration, SystemActivationClock};
use latent_node::{
    CacheInventorySource, EmptyCacheInventorySource, EmptyNodeTopologySource, InventoryReporter,
    NodeCacheSummary, NodeTopologySource, StandaloneInventoryReporter, StandaloneInventorySources,
};
use latent_routing::{InvocationTarget, ResolvedBinding, ResolvedRevision, RouteResolver};
use latent_scheduler::LocalScheduler;
use latent_wasmtime::{PreparedCacheSnapshot, WasmtimeComponentEngineFactory};

use super::{cache, CacheSource, InventorySlot};

struct Routes;
impl RouteResolver for Routes {
    fn resolve(
        &self,
        _: &InvocationTarget,
        _: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        panic!("inventory must not resolve or enumerate a service");
    }
    fn resolve_binding(
        &self,
        _: &ResolvedRevision,
        _: &ContractId,
        _: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        panic!("inventory must not inspect bindings");
    }
    fn generation(&self) -> RouteGeneration {
        RouteGeneration(100_000)
    }
}

struct Load;
impl NodeLoadSource for Load {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        Ok(NodeLoadSnapshot {
            accepting: false,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            // A cached past sample avoids a future-dated reading relative to the
            // reporter's clock sample, with no sleep or background sampler.
            observed_at: std::time::Instant::now()
                .checked_sub(std::time::Duration::from_millis(1))
                .expect("test clock supports a prior millisecond"),
        })
    }
}

fn settings() -> crate::config::NodeSettings {
    let config: crate::config::NodeConfig = serde_json::from_value(serde_json::json!({
        "formatVersion": 1,
        "dataDirectory": std::env::temp_dir().join("latent-observation-test-unused"),
        "nodeId": "observation-test",
        "bind": "127.0.0.1:0",
        "credentials": [{"token": "test-token-000000000000000000000000000000",
            "subject": "operator", "tenant": "tenant-a", "role": "operator"}]
    }))
    .expect("small operator configuration");
    config
        .derive()
        .expect("validated settings without opening resources")
}

pub(super) fn reporter(
    cache: Arc<dyn CacheInventorySource>,
    topology: Arc<dyn NodeTopologySource>,
    maximum_rows: usize,
) -> StandaloneInventoryReporter {
    let mut settings = settings();
    settings.node.endpoint = "http://127.0.0.1:23456".to_owned();
    settings.inventory.maximum_cache_descriptors = 32;
    settings.inventory.maximum_topology_entries = maximum_rows;
    let quotas = LocalQuotaProvider::new(settings.admission).expect("quota policy");
    let scheduler =
        Arc::new(LocalScheduler::new(settings.scheduler, quotas.clone()).expect("fixed scheduler"));
    StandaloneInventoryReporter::new(
        settings.inventory,
        settings.node,
        StandaloneInventorySources {
            scheduler,
            routes: Arc::new(Routes),
            quotas,
            load: Arc::new(Load),
            cache,
            topology,
            clock: Arc::new(SystemActivationClock),
        },
    )
    .expect("bounded inventory reporter")
}

#[tokio::test]
async fn inventory_slot_requires_installation_and_never_replaces_its_reporter() {
    let slot = InventorySlot::new();
    assert_eq!(
        slot.snapshot_now().unwrap_err().code,
        latent_core::PlatformErrorCode::Unavailable
    );
    assert_eq!(
        slot.snapshot().await.unwrap_err().code,
        latent_core::PlatformErrorCode::Unavailable
    );
    let initial = Arc::new(reporter(
        Arc::new(EmptyCacheInventorySource),
        Arc::new(EmptyNodeTopologySource),
        32,
    ));
    slot.install(Arc::clone(&initial))
        .expect("first installation");
    let replacement = Arc::new(reporter(
        Arc::new(EmptyCacheInventorySource),
        Arc::new(EmptyNodeTopologySource),
        32,
    ));
    assert_eq!(
        slot.install(Arc::clone(&replacement)).unwrap_err().code,
        latent_core::PlatformErrorCode::StateConflict
    );
    assert_eq!(Arc::strong_count(&initial), 2);
    assert_eq!(Arc::strong_count(&replacement), 1);
    let value = slot.snapshot().await.expect("installed reporter");
    assert_eq!(value.node.endpoint, "http://127.0.0.1:23456");
    assert_eq!(value.route_generation, RouteGeneration(100_000));
    assert!(
        !value.health.ready,
        "installation alone does not open admission"
    );
}

#[test]
fn prepared_cache_mapping_preserves_every_aggregate_and_counter() {
    let value = cache::summary(&PreparedCacheSnapshot {
        entries: 1,
        maximum_entries: 2,
        source_bytes: 3,
        maximum_source_bytes: 4,
        metadata_bytes: 5,
        maximum_metadata_bytes: 6,
        compiled_image_bytes: 7,
        maximum_compiled_image_bytes: 8,
        preparing: 9,
        maximum_concurrent_preparations: 10,
        preparing_source_bytes: 11,
        preparing_metadata_bytes: 12,
        hits: 13,
        misses: 14,
        evictions: 15,
        invalidations: 16,
    });
    assert_eq!(
        value,
        NodeCacheSummary {
            available: true,
            entries: 1,
            maximum_entries: 2,
            source_bytes: 3,
            maximum_source_bytes: 4,
            metadata_bytes: 5,
            maximum_metadata_bytes: 6,
            compiled_image_bytes: 7,
            maximum_compiled_image_bytes: 8,
            preparing: 9,
            maximum_concurrent_preparations: 10,
            preparing_source_bytes: 11,
            preparing_metadata_bytes: 12,
            hits: 13,
            misses: 14,
            evictions: 15,
            invalidations: 16,
        }
    );
}

#[test]
fn real_backend_cache_source_returns_only_its_bounded_aggregate() {
    let settings = settings();
    let factory = WasmtimeComponentEngineFactory::new(settings.wasmtime).expect("engine");
    let backend = Arc::new(factory.create_backend_instance());
    let expected = cache::summary(&backend.cache_snapshot());
    let reporter = reporter(
        Arc::new(CacheSource::new(Arc::clone(&backend))),
        Arc::new(EmptyNodeTopologySource),
        32,
    );
    let inventory = reporter.snapshot_now().expect("real cache aggregate");
    assert_eq!(inventory.cache_summary, expected);
    assert!(
        inventory.cache_entries.is_empty(),
        "even a 32-row allowance must not enumerate descriptors"
    );
    assert!(inventory.retained_bytes <= 256 * 1024);
    drop(reporter);
    drop(backend);
    factory
        .shutdown()
        .expect("reporter releases its backend owner");
}
