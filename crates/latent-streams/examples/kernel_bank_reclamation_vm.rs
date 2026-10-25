//! One isolated-VM fixed-bank reclamation join. Never execute this example on a build host.
//! This uses the existing qualification-only public caller, not a guest transport.
//! Fixed original pool/IoRuntime limits and a 20-second attempt are retained.
//! Final snapshots retain the original connection, 512 KiB overhead and observer;
//! only the same protected-read flow can return the prepartitioned 512 KiB bank.
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
    fn factory_descriptors() -> Checked<(usize, usize)> {
        let mut seen = 0;
        let mut factory = 0;
        let mut observer = 0;
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
            } else if target == Path::new("anon_inode:lsf-root-retirement") {
                observer += 1;
            }
        }
        Ok((factory, observer))
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

    fn emit(name: &str, value: ProviderPoolSnapshot, descriptors: (usize, usize)) {
        // Closed call sites below are the only labels; all values are original counters.
        println!("LSFBANK1 state={name} connections={} failedCleanup={} cleanupJobs={} pending={} running={} workers={} metadataBytes={} controlFailed={} descriptors={} observerDescriptors={}",
            value.connections, value.failed_cleanup, value.cleanup_jobs, value.pending_requests,
            value.running_requests, value.workers, value.metadata_bytes, u8::from(value.control_failed), descriptors.0, descriptors.1);
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
        if factory_descriptors()? != (0, 0)
            || baseline.connections != 0
            || baseline.failed_cleanup != 0
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
        emit("baseline", baseline, (0, 0));
        let provider = StreamProvider::install_kernel_bank_reclamation_for_qualification(
            Arc::clone(&pools),
            "streams",
            1,
            0,
            configuration(),
            deadline,
        )
        .await
        .map_err(|_| ())?;
        println!("LSFRETURNDIAG stage=install-complete");
        let ready = loop {
            let value = snapshot(&pools, deadline).await?;
            if value.workers == 0 {
                break value;
            }
            if Instant::now() >= deadline {
                return Err(());
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        };
        if Instant::now() >= deadline {
            return Err(());
        }
        let ready_descriptors = factory_descriptors()?;
        if ready_descriptors != (1, 1)
            || ready.connections != 1
            || ready.failed_cleanup != 0
            || ready.cleanup_jobs != baseline.cleanup_jobs + 1
            || ready.metadata_bytes < baseline.metadata_bytes + 1024 * 1024 + 4096
        {
            emit("ready-rejected", ready, ready_descriptors);
            return Err(());
        }
        emit("ready", ready, (1, 1));
        // Narrow the existing quota; no new allowance or policy kind. Reserve
        // the same fixed amount only after the protected physical proof.
        let mut limits = pools.limits().map_err(|_| ())?;
        limits.maximum_metadata_bytes = ready.metadata_bytes.checked_add(64 * 1024).ok_or(())?;
        loop {
            match pools.lower_limits(limits) {
                Ok(()) => break,
                Err(failure)
                    if failure.code == latent_core::PlatformErrorCode::ResourceExhausted
                        && failure.message == "capability-busy"
                        && Instant::now() < deadline =>
                {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
                Err(_) => return Err(()),
            }
        }
        match pools.reserve_protocol_metadata(512 * 1024) {
            Err(failure)
                if failure.code == latent_core::PlatformErrorCode::ResourceExhausted
                    && failure.message == "capability-capacity" => {}
            _ => return Err(()),
        }

        // Require the authenticated fixed observation FD after original File close.
        // Neither UART nor descriptor disappearance supplies this typed result.
        // The returned affine receipt STILL owns the additional cleanup charge.
        let receipt = provider
            .retire_kernel_constructor_for_qualification(deadline)
            .await
            .map_err(|_| ())?;
        if receipt.observation() != StreamKernelCloseObservation::KernelRootReturned {
            return Err(());
        }
        let held = snapshot(&pools, deadline).await?;
        if factory_descriptors()? != (0, 0)
            || held.connections != 1
            || held.failed_cleanup != 1
            || held.cleanup_jobs != ready.cleanup_jobs + 1
            || held.metadata_bytes < baseline.metadata_bytes + 512 * 1024 + 4096
            || held.metadata_bytes >= baseline.metadata_bytes + 1024 * 1024 + 4096
        {
            return Err(());
        }
        emit("root-return-observed-held", held, (0, 0));
        drop(receipt); // The bank already returned; only paid close-job billing drops here.
        drop(provider);
        let retained = loop {
            if Instant::now() >= deadline {
                return Err(());
            }
            let retained = snapshot(&pools, deadline).await?;
            if retained.failed_cleanup == 1 && retained.cleanup_jobs == ready.cleanup_jobs {
                if factory_descriptors()? != (0, 0)
                    || retained.connections != 1
                    || retained.pending_requests != 0
                    || retained.running_requests != 0
                    || retained.workers != 0
                    || retained.control_failed
                    || retained.metadata_bytes < baseline.metadata_bytes + 512 * 1024 + 4096
                    || retained.metadata_bytes >= baseline.metadata_bytes + 1024 * 1024 + 4096
                {
                    return Err(());
                }
                emit("quarantined", retained, (0, 0));
                break retained;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        };
        let reused_charge = pools
            .reserve_protocol_metadata(512 * 1024)
            .map_err(|_| ())?;
        let reused = snapshot(&pools, deadline).await?;
        let mut counters = reused;
        counters.metadata_bytes = retained.metadata_bytes;
        if counters != retained || reused.metadata_bytes != retained.metadata_bytes + 512 * 1024 {
            return Err(());
        }
        emit("bank-capacity-reused", reused, factory_descriptors()?);
        drop(reused_charge);
        let returned = snapshot(&pools, deadline).await?;
        if returned != retained || factory_descriptors()? != (0, 0) || Instant::now() >= deadline {
            return Err(());
        }
        emit("bank-capacity-returned", returned, (0, 0));
        println!("LSFBANK1 result=PASS constructorReady=1 kernelRootReturned=1 descriptorClosed=1 observerClosed=1 bankReservationBytes=524288 overheadReservationBytes=524288 bankCapacityReused=1 connectionQuarantined=1 fullNativeQuotaReleased=0 productionInstalled=0");
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
        std::panic::set_hook(Box::new(|_| eprintln!("LSFBANK1 result=FAIL stage=panic")));
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
            eprintln!("LSFBANK1 result=FAIL stage=native-constructor");
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
