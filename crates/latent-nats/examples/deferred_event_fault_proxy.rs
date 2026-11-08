//! Private bounded test fixture: drop or hold one actual `JetStream` acknowledgement.
//! This is not a production proxy, credential store, or authorization decision.
use latent_nats::{NatsConfig, NatsEndpoint, TopicMapping};
use std::{fs, io::Write, net::Ipv4Addr, path::PathBuf, sync::atomic::Ordering, time::Duration};

mod support {
    use std::time::Duration;
    pub const WATCHDOG: Duration = Duration::from_secs(20);
}
#[allow(
    dead_code,
    reason = "Reuse the same bounded proxy and fault modes as real broker tests"
)]
#[path = "../tests/deferred_events/proxy.rs"]
mod proxy;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let output = PathBuf::from(args.next().ok_or("fresh absolute output required")?);
    let hold = match args.next().as_deref() {
        None => false,
        Some(value) if value == "hold-ack" => true,
        _ => return Err("choose the optional hold-ack fault".into()),
    };
    if args.next().is_some() || !output.is_absolute() || output.exists() {
        return Err("choose one fresh absolute fixture output and optional fault".into());
    }
    let port: u16 = std::env::var("LSF_NATS_TEST_PORT")?.parse()?;
    if port == 0 {
        return Err("loopback broker port required".into());
    }
    let ca =
        PathBuf::from(std::env::var_os("LSF_NATS_TEST_CA").ok_or("original broker CA required")?);
    let metadata = fs::symlink_metadata(&ca)?;
    if !ca.is_absolute()
        || !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > 65536
    {
        return Err("bounded original broker CA required".into());
    }
    let config = NatsConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            server_name: "127.0.0.1".into(),
            peer: (Ipv4Addr::LOCALHOST, port).into(),
            allow_non_public_peer: true,
        },
        public_roots: false,
        extra_roots: vec![fs::read(ca)?],
        topics: vec![TopicMapping {
            tenant: "examples".into(),
            topic: "updated".into(),
            subject: "lsf.deferred.allowed".into(),
            stream: "DURABLE".into(),
            duplicate_window_millis: 30_000,
        }],
        idempotency_namespace: "lsf-java-transaction-event".into(),
        maximum_payload_bytes: 8192,
        timeout_millis: 5000,
    };
    config
        .validate()
        .map_err(|_| "invalid fixture configuration")?;
    fs::create_dir(&output)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&output, fs::Permissions::from_mode(0o700))?;
    }
    let fixture = proxy::Proxy::new(config).await;
    fixture.mode.store(
        if hold {
            proxy::HOLD_ACK
        } else {
            proxy::DROP_ACK
        },
        Ordering::Release,
    );
    let mut metadata = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output.join("proxy.json"))?;
    serde_json::to_writer(&mut metadata, &fixture.config)?;
    metadata.flush()?;
    println!("READY");
    // The caller owns this single process and can end it early by creating a
    // sentinel. A finite deadline prevents an abandoned fixture from persisting.
    let mut observed = false;
    let mut released = false;
    let mut forwarded = false;
    for _ in 0..15000 {
        if output.join("stop").is_file() {
            fixture.close().await;
            return Ok(());
        }
        tokio::select! {
            () = fixture.seen.notified(), if !observed => {
                let name = if hold { "ack-held" } else { "ack-dropped" };
                fs::OpenOptions::new().write(true).create_new(true).open(output.join(name))?;
                observed = true;
            }
            () = fixture.forwarded.notified(), if hold && !forwarded => {
                fs::OpenOptions::new().write(true).create_new(true).open(output.join("ack-forwarded"))?;
                forwarded = true;
            }
            () = tokio::time::sleep(Duration::from_millis(100)) => {}
        }
        if hold && observed && !released && output.join("release").is_file() {
            fixture.mode.store(proxy::HEALTHY, Ordering::Release);
            fixture.release.notify_one();
            released = true;
        }
    }
    fixture.close().await;
    Err("fixture deadline elapsed".into())
}
