//! One isolated-VM constructor join. Never execute this example on a build host.
//! This uses the existing qualification-only public caller, not a guest transport.
//! Fixed original pool/IoRuntime limits and a 20-second attempt are retained.
//! Final snapshots deliberately retain the original connection and 1 MiB backing;
//! neither descriptor disappearance nor this programme authorizes a quota refund.
#[cfg(all(target_os = "linux", feature = "development-outbound"))]
mod selected {
    use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
    use latent_capabilities::broker::{
        io::{IoLimits, IoRuntime},
        pools::{
            ProviderPoolLimits, ProviderPoolSnapshot, ProviderPools, StreamKernelCloseObservation,
        },
        ActivationCapabilityBroker, CapabilityBrokerLimits,
    };
    use latent_core::SystemActivationClock;
    use latent_network::AddressPolicy;
    use latent_policy::capability::{
        PolicyStore, PolicyStoreLimits, StreamEndpoint, StreamTransport,
    };
    use latent_streams::{
        StreamDestination, StreamErrorCode, StreamLimits, StreamProvider, StreamProviderConfig,
        StreamResolution,
    };
    use std::{
        path::Path,
        sync::Arc,
        time::{Duration, Instant},
    };

    type Checked<T> = Result<T, ()>;

    fn configuration() -> StreamProviderConfig {
        StreamProviderConfig {
            format_version: 1,
            profile: latent_capabilities::broker::network::STREAM_PROFILE.into(),
            destinations: vec![StreamDestination {
                endpoint: StreamEndpoint {
                    host: "127.0.0.1".into(),
                    port: 25,
                    transport: StreamTransport::Tcp,
                },
                addresses: AddressPolicy {
                    networks: vec!["127.0.0.1/32".parse().expect("fixed network")],
                    special_addresses: vec!["127.0.0.1".parse().expect("fixed address")],
                },
                resolution: StreamResolution::Static {
                    addresses: vec!["127.0.0.1".parse().expect("fixed address")],
                },
                tls: None,
            }],
            limits: StreamLimits::default(),
        }
    }

    // Observe only the exact fixed device link, never print arbitrary fd paths.
    // The extra read_dir descriptor is bounded and disappears before each snapshot.
    fn factory_descriptors() -> Checked<usize> {
        let mut seen = 0;
        let mut factory = 0;
        for entry in std::fs::read_dir("/proc/self/fd").map_err(|_| ())? {
            seen += 1;
            if seen > 64 {
                return Err(());
            }
            let entry = entry.map_err(|_| ())?;
            let name = entry.file_name();
            let text = name.to_str().ok_or(())?;
            if text.len() > 10 || !text.bytes().all(|b| b.is_ascii_digit()) {
                return Err(());
            }
            let target = std::fs::read_link(entry.path()).map_err(|_| ())?;
            if target.as_os_str().len() > 4096 {
                return Err(());
            }
            if target == Path::new("/dev/lsf-stream-factory") {
                factory += 1;
            }
        }
        Ok(factory)
    }

    async fn snapshot(pools: &ProviderPools, deadline: Instant) -> Checked<ProviderPoolSnapshot> {
        loop {
            match pools.snapshot() {
                Ok(value) => return Ok(value),
                Err(error)
                    if error.code == latent_core::PlatformErrorCode::ResourceExhausted
                        && error.message == "capability-busy"
                        && Instant::now() < deadline =>
                {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
                Err(_) => return Err(()),
            }
        }
    }

    fn emit(name: &str, value: ProviderPoolSnapshot, descriptors: usize) {
        // Closed call sites below are the only labels; all values are original counters.
        println!("LSFNATIVE1 state={name} connections={} failedCleanup={} cleanupJobs={} pending={} running={} workers={} metadataBytes={} controlFailed={} descriptors={descriptors}",
            value.connections, value.failed_cleanup, value.cleanup_jobs, value.pending_requests,
            value.running_requests, value.workers, value.metadata_bytes, u8::from(value.control_failed));
    }

    async fn execute() -> Checked<()> {
        let deadline = Instant::now() + Duration::from_secs(20);
        let root = Path::new("/tmp/lsf-native-constructor");
        std::fs::create_dir(root).map_err(|_| ())?;
        let catalog = DirectoryArtifactRepository::open(
            root.join("artifacts"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .map_err(|_| ())?;
        let policies = Arc::new(
            PolicyStore::open(
                &root.join("policies"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .map_err(|_| ())?,
        );
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                catalog.lifecycle_authority(),
                policies,
                Arc::new(SystemActivationClock),
                CapabilityBrokerLimits::default(),
            )
            .map_err(|_| ())?,
        );
        let io = Arc::new(
            IoRuntime::new(IoLimits {
                maximum_chunk_bytes: 16 * 1024,
                ..IoLimits::default()
            })
            .map_err(|_| ())?,
        );
        let pools = Arc::new(
            ProviderPools::new(
                broker,
                io,
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .map_err(|_| ())?,
        );
        let baseline = snapshot(&pools, deadline).await?;
        if factory_descriptors()? != 0 || baseline.connections != 0 || baseline.failed_cleanup != 0
        {
            return Err(());
        }
        // The actual normal installation gate stays Unsupported and allocates no owner.
        let failure = StreamProvider::install(Arc::clone(&pools), "streams", 1, 0, configuration());
        if !matches!(failure, Err(error) if error.code == StreamErrorCode::Unsupported)
            || snapshot(&pools, deadline).await? != baseline
        {
            return Err(());
        }
        emit("baseline", baseline, 0);
        let provider = StreamProvider::install_kernel_constructor_for_qualification(
            Arc::clone(&pools),
            "streams",
            1,
            0,
            configuration(),
            deadline,
        )
        .await
        .map_err(|_| ())?;
        let ready = snapshot(&pools, deadline).await?;
        if Instant::now() >= deadline
            || factory_descriptors()? != 1
            || ready.connections != 1
            || ready.failed_cleanup != 0
            || ready.cleanup_jobs != baseline.cleanup_jobs + 1
            || ready.metadata_bytes < baseline.metadata_bytes + 1024 * 1024
        {
            return Err(());
        }
        emit("ready", ready, 1);
        // Observe actual authenticated CLOSE3/CLOSED4, not File-close success.
        // The returned affine receipt STILL owns the additional cleanup charge.
        let receipt = provider
            .retire_kernel_constructor_for_qualification(deadline)
            .await
            .map_err(|_| ())?;
        if receipt.observation() != StreamKernelCloseObservation::RequestAccepted {
            return Err(());
        }
        let held = snapshot(&pools, deadline).await?;
        if factory_descriptors()? != 0
            || held.connections != 1
            || held.failed_cleanup != 1
            || held.cleanup_jobs != ready.cleanup_jobs + 1
            || held.metadata_bytes < baseline.metadata_bytes + 1024 * 1024
        {
            return Err(());
        }
        emit("close-request-accepted-held", held, 0);
        drop(receipt); // Only the observation/job charge returns, never backing.
        drop(provider);
        loop {
            if Instant::now() >= deadline {
                return Err(());
            }
            let retained = snapshot(&pools, deadline).await?;
            if retained.failed_cleanup == 1 && retained.cleanup_jobs == ready.cleanup_jobs {
                if factory_descriptors()? != 0
                    || retained.connections != 1
                    || retained.pending_requests != 0
                    || retained.running_requests != 0
                    || retained.workers != 0
                    || retained.control_failed
                    || retained.metadata_bytes < baseline.metadata_bytes + 1024 * 1024
                {
                    return Err(());
                }
                emit("quarantined", retained, 0);
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        println!("LSFNATIVE1 result=PASS constructorReady=1 closeRequestAccepted=1 descriptorClosed=1 backingQuarantined=1 nativeQuotaReleased=0 productionInstalled=0");
        Ok(())
    }

    pub fn run() {
        // The hosted programme only builds this file. The PID1 supervisor execs it in
        // the VM; no compiler/parser control invokes this native constructor on host.
        let mut arguments = std::env::args();
        let isolated = arguments.next().as_deref() == Some("/native-init")
            && arguments.next().as_deref() == Some("--constructor-vm-child")
            && arguments.next().is_none()
            && std::fs::read_link("/proc/1/exe").ok().as_deref() == Some(Path::new("/init"));
        if !isolated {
            std::process::exit(2);
        }
        std::panic::set_hook(Box::new(|_| {
            eprintln!("LSFNATIVE1 result=FAIL stage=panic")
        }));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(2)
            .thread_stack_size(2 * 1024 * 1024)
            .thread_name("lsf-native-vm")
            .build();
        let Ok(runtime) = runtime else {
            std::process::exit(2);
        };
        let result = runtime.block_on(execute());
        runtime.shutdown_timeout(Duration::from_secs(1));
        if result.is_err() {
            eprintln!("LSFNATIVE1 result=FAIL stage=native-constructor");
            std::process::exit(2);
        }
    }
}

fn main() {
    #[cfg(all(target_os = "linux", feature = "development-outbound"))]
    selected::run();
    #[cfg(not(all(target_os = "linux", feature = "development-outbound")))]
    std::process::exit(2);
}
