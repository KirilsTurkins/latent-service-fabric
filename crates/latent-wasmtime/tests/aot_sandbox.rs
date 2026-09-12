//! A single-thread test main is necessary: libtest keeps its harness thread alive
//! while an ordinary #[test] runs, violating the production sandbox prerequisite.
#![forbid(unsafe_code)]

#[path = "../src/aot/sandbox.rs"]
mod sandbox;

fn main() {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    linux::run();
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        let error = sandbox::bootstrap(sandbox::SandboxLimits::default(), 1).unwrap_err();
        assert_eq!(
            error.code,
            latent_core::PlatformErrorCode::IncompatibleContract
        );
        println!("AOT sandbox: unsupported host rejected as required");
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod linux {
    use super::sandbox;
    use rustix::fs::{fcntl_getfl, fcntl_setfl, OFlags};
    use rustix::io::{fcntl_setfd, FdFlags};
    use std::{
        fs::{File, OpenOptions},
        io::{Read, Write},
        os::fd::AsFd,
        os::unix::process::CommandExt as _,
        process::{Child, Command, ExitStatus, Stdio},
        time::{Duration, Instant},
    };

    pub(super) fn run() {
        let args: Vec<_> = std::env::args().collect();
        if args
            .get(1)
            .is_some_and(|value| value == "--probe" || value == "--probe-clean")
        {
            assert_eq!(args.len(), 4);
            probe(
                &args[2],
                args[3].parse().unwrap(),
                args[1] == "--probe-clean",
            );
            return;
        }
        let executable = std::env::current_exe().unwrap();
        let cases = [
            "entry",
            "dump-protection",
            "inherited-fd",
            "clean-marker-with-fd",
            "filesystem",
            "network",
            "descendants",
            "memory",
            "executable",
            "extra-fd",
            "extra-thread",
            "bad-pipes",
        ];
        for case in cases {
            let inherited = if matches!(case, "inherited-fd" | "clean-marker-with-fd") {
                let file = File::open("/dev/null").unwrap();
                fcntl_setfd(&file, FdFlags::empty()).unwrap();
                Some(file)
            } else {
                None
            };
            let mut command = Command::new(&executable);
            unprivileged(&mut command);
            command
                .env_clear()
                .arg(if case == "clean-marker-with-fd" {
                    "--probe-clean"
                } else {
                    "--probe"
                })
                .arg(case)
                .arg(std::process::id().to_string());
            let result = bounded(command, &[], case == "bad-pipes");
            assert!(
                result.status.success(),
                "{case}: {}",
                String::from_utf8_lossy(&result.diagnostics)
            );
            assert_eq!(result.output, b"sandbox probe passed\n", "{case}");
            if let Some(file) = inherited {
                // Sanitation changes only the child: our original remains open.
                assert!(file.metadata().is_ok());
            }
        }

        // The safe mapping API can test mprotect, but raw executable mmap and
        // fork APIs are unsafe in Rust. A tiny test-only Python process installs
        // these exact production BPF bytes, then invokes the denied syscalls.
        let policy = sandbox::probe_policy_bytes().unwrap();
        assert!(!policy.is_empty() && policy.len() <= 8192);
        let mut payload = u32::try_from(policy.len()).unwrap().to_le_bytes().to_vec();
        payload.extend_from_slice(&policy);
        let mut command = Command::new("python3");
        unprivileged(&mut command);
        command
            .env_clear()
            .env("PATH", "/usr/local/bin:/usr/bin:/bin")
            .args(["-I", "-B"])
            .arg(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/tests/fixtures/aot_syscall_probe.py"
            ));
        let result = bounded(command, &payload, false);
        assert!(
            result.status.success(),
            "raw syscall probe: {}",
            String::from_utf8_lossy(&result.diagnostics)
        );
        assert_eq!(result.output, b"kernel syscall denial passed\n");
        println!(
            "AOT sandbox: 12 unprivileged real-entry probes and exact-policy syscall probe passed"
        );
    }

    fn unprivileged(command: &mut Command) {
        if rustix::process::geteuid().is_root() {
            // Root-run builders must exercise the same /proc access rules as
            // ordinary CI users. Only each disposable child drops credentials;
            // its PID and the parent's identity used by launch checks persist.
            command.gid(65534).uid(65534);
        }
    }

    fn probe(case: &str, parent_pid: u32, clean: bool) {
        assert!(!rustix::process::geteuid().is_root());
        let limits = sandbox::SandboxLimits::default();
        let arguments = [
            "--probe-clean".into(),
            case.into(),
            parent_pid.to_string().into(),
        ];
        let launch =
            sandbox::prepare_launch(limits, parent_pid, (!clean).then_some(arguments.as_slice()));
        if matches!(case, "bad-pipes" | "clean-marker-with-fd") {
            assert_eq!(
                launch.unwrap_err().message,
                "aot-sandbox-requires-only-three-pipes"
            );
            println!("sandbox probe passed");
            return;
        }
        launch.unwrap();
        let prepared = sandbox::bootstrap(limits, parent_pid).unwrap();
        if case == "extra-fd" {
            let extra = File::open("/dev/null").unwrap();
            assert_eq!(
                prepared.enter().unwrap_err().message,
                "aot-sandbox-requires-only-three-pipes"
            );
            drop(extra);
            println!("sandbox probe passed");
            return;
        }
        if case == "extra-thread" {
            let (sender, receiver) = std::sync::mpsc::sync_channel::<()>(0);
            let thread = std::thread::spawn(move || receiver.recv().unwrap());
            let result = prepared.enter();
            sender.send(()).unwrap();
            thread.join().unwrap();
            assert_eq!(
                result.unwrap_err().message,
                "aot-sandbox-requires-one-thread"
            );
            println!("sandbox probe passed");
            return;
        }
        // Initialize the wrapper's page-size cache before filesystem denial.
        let mapping = memmap2::MmapMut::map_anon(4096).unwrap();
        let enforced = prepared.enter().unwrap();
        assert_eq!(enforced.profile_id(), sandbox::PROFILE_ID);
        match case {
            "entry" | "inherited-fd" => {}
            "dump-protection" => {
                // Entry already verified PR_GET_DUMPABLE before installing the
                // final filter. The filter must forbid undoing that state; no
                // post-filter /proc read or PR_GET permission is needed.
                assert_eq!(
                    rustix::process::set_dumpable_behavior(
                        rustix::process::DumpableBehavior::Dumpable
                    ),
                    Err(rustix::io::Errno::PERM)
                );
            }
            "filesystem" => {
                assert_denied(File::open("/proc/self/status"));
                assert_denied(OpenOptions::new().write(true).open("/dev/null"));
            }
            "network" => assert_denied(std::net::UdpSocket::bind("127.0.0.1:0")),
            "descendants" => {
                // This asserts no process can be launched through the real std
                // path; the raw clone/fork syscalls are separately probed below.
                assert_denied(Command::new("/bin/true").spawn());
            }
            "memory" => {
                let mut bytes = Vec::<u8>::new();
                let requested = usize::try_from(limits.address_space_bytes + 1).unwrap();
                assert!(bytes.try_reserve_exact(requested).is_err());
            }
            "executable" => {
                // A normal anonymous RW mapping remains possible after entry.
                let mut normal = memmap2::MmapMut::map_anon(4096).unwrap();
                normal[0] = 7;
                assert_eq!(normal[0], 7);
                assert_denied(mapping.make_exec());
            }
            _ => panic!("unknown fixed probe"),
        }
        println!("sandbox probe passed");
    }

    fn assert_denied<T>(result: std::io::Result<T>) {
        match result {
            Err(error) => assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied),
            Ok(_) => panic!("sandbox unexpectedly allowed operation"),
        }
    }

    struct ResultBytes {
        status: ExitStatus,
        output: Vec<u8>,
        diagnostics: Vec<u8>,
    }
    struct ChildOwner(Child);
    impl Drop for ChildOwner {
        fn drop(&mut self) {
            let _ = self.0.kill();
            loop {
                match self.0.wait() {
                    Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
                    _ => break,
                }
            }
        }
    }

    fn bounded(mut command: Command, payload: &[u8], bad_input: bool) -> ResultBytes {
        command
            .stdin(if bad_input {
                Stdio::null()
            } else {
                Stdio::piped()
            })
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut owner = ChildOwner(command.spawn().unwrap());
        let mut input = owner.0.stdin.take();
        let mut stdout = owner.0.stdout.take().unwrap();
        let mut stderr = owner.0.stderr.take().unwrap();
        if let Some(input) = &input {
            nonblocking(input);
        }
        nonblocking(&stdout);
        nonblocking(&stderr);
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut sent = 0;
        let mut output = Vec::with_capacity(2048);
        let mut diagnostics = Vec::with_capacity(2048);
        let mut output_eof = false;
        let mut diagnostic_eof = false;
        let mut status = None;
        loop {
            assert!(
                Instant::now() < deadline,
                "bounded sandbox probe exceeded deadline"
            );
            if sent == payload.len() {
                drop(input.take());
            } else if let Some(input) = &mut input {
                match input.write(&payload[sent..payload.len().min(sent + 1024)]) {
                    Ok(0) => panic!("probe input closed early"),
                    Ok(size) => sent += size,
                    Err(error) if temporary(&error) => {}
                    Err(error) => panic!("probe input failed: {error}"),
                }
            }
            if !output_eof {
                output_eof = capture(&mut stdout, &mut output);
            }
            if !diagnostic_eof {
                diagnostic_eof = capture(&mut stderr, &mut diagnostics);
            }
            if status.is_none() {
                status = owner.0.try_wait().unwrap();
            }
            if output_eof && diagnostic_eof {
                if let Some(status) = status {
                    return ResultBytes {
                        status,
                        output,
                        diagnostics,
                    };
                }
            }
            std::thread::sleep(Duration::from_millis(1));
        }
    }

    fn capture(reader: &mut impl Read, output: &mut Vec<u8>) -> bool {
        let mut bytes = [0_u8; 512];
        match reader.read(&mut bytes) {
            Ok(0) => true,
            Ok(size) => {
                assert!(output.len() + size <= 2048, "probe diagnostic/output limit");
                output.extend_from_slice(&bytes[..size]);
                false
            }
            Err(error) if temporary(&error) => false,
            Err(error) => panic!("probe output failed: {error}"),
        }
    }
    fn temporary(error: &std::io::Error) -> bool {
        matches!(
            error.kind(),
            std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
        )
    }
    fn nonblocking(fd: impl AsFd) {
        let flags = fcntl_getfl(&fd).unwrap();
        fcntl_setfl(fd, flags | OFlags::NONBLOCK).unwrap();
    }
}
