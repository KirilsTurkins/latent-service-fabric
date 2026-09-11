use std::fs::File;
use std::process::ExitStatus;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio::process::Child;
use tokio::sync::mpsc;
use tokio::task::{JoinHandle, JoinSet};

use super::{
    child,
    command::{self, Args},
    forward, observe, output, streams, Result,
};

pub(super) async fn run(args: &Args, origin: Instant) -> Result<()> {
    let signals = Signals::new()?;
    let (events, stdout, stderr) = files(args)?;
    let mut child = child::spawn(args)?;
    let pid = child.id().expect("newly spawned child has an ID");
    let (notices, received) = mpsc::channel(8);
    let stdout = tokio::spawn(streams::drain(
        child.stdout.take().expect("configured stdout"),
        stdout,
        args.app,
        true,
        notices.clone(),
    ));
    let stderr = tokio::spawn(streams::drain(
        child.stderr.take().expect("configured stderr"),
        stderr,
        args.app,
        false,
        notices,
    ));
    let mut owner = Owner {
        child,
        pid,
        stdout,
        stderr,
        received,
        signals,
        origin,
        events: output::Events::new(events, origin, args.app, pid),
        forward: JoinSet::new(),
        counts: forward::Counts::default(),
        snapshots: 0,
        early_exit: None,
        stop_requested: false,
    };
    let result = owner.serve().await;
    owner.cleanup(result).await
}

fn files(args: &Args) -> Result<(File, File, File)> {
    if !args.output.exists() {
        std::fs::create_dir(&args.output).map_err(|_| "wrapper-output-directory")?;
    }
    if args.output.is_symlink()
        || !args.output.is_dir()
        || std::fs::read_dir(&args.output)
            .map_err(|_| "wrapper-output-directory")?
            .next()
            .is_some()
    {
        return Err("wrapper-output-not-fresh");
    }
    Ok((
        output::fresh(&args.output.join("events.ndjson"))?,
        output::fresh(&args.output.join("child-stdout.bin"))?,
        output::fresh(&args.output.join("child-stderr.bin"))?,
    ))
}

struct Owner {
    child: Child,
    pid: u32,
    stdout: JoinHandle<streams::Receipt>,
    stderr: JoinHandle<streams::Receipt>,
    received: mpsc::Receiver<streams::Notice>,
    signals: Signals,
    origin: Instant,
    events: output::Events,
    forward: JoinSet<Result<(u64, u64)>>,
    counts: forward::Counts,
    snapshots: u32,
    early_exit: Option<std::io::Result<ExitStatus>>,
    stop_requested: bool,
}

impl Owner {
    async fn serve(&mut self) -> Result<()> {
        self.events.emit("started",json!({"pid1":std::process::id()==1,"listen":command::LISTEN,
            "child_listen":command::CHILD_LISTEN,"runtime_workers":2,"maximum_connections":forward::CAPACITY,
            "buffer_bytes_per_direction":forward::BUFFER_BYTES,"connect_timeout_millis":5000,"ready_timeout_millis":30000,
            "child_term_grace_millis":10000,"child_kill_wait_millis":5000,"forward_drain_millis":5000,
            "maximum_lifetime_millis":300000,"maximum_snapshots":6}))?;
        let ready = tokio::time::timeout(Duration::from_secs(30), self.ready())
            .await
            .map_err(|_| "child-ready-timeout")??;
        let listener = TcpListener::bind(command::LISTEN)
            .await
            .map_err(|_| "wrapper-listener-bind")?;
        self.events.emit("ready",json!({"listen":command::LISTEN,"child_listen":command::CHILD_LISTEN,"child_status":ready}))?;
        let lifetime = tokio::time::sleep_until(tokio::time::Instant::from_std(
            self.origin + Duration::from_secs(300),
        ));
        tokio::pin!(lifetime);
        loop {
            tokio::select! {
                biased;
                ()=self.signals.stop.wait()=> {self.stop_requested=true;return Ok(());}
                result=self.child.wait()=> {self.early_exit=Some(result);return Err("child-exited-before-wrapper-stop");}
                notice=self.received.recv()=> {match notice {
                    Some(streams::Notice::Failed(reason))=>return Err(reason),
                    _=>return Err("unexpected-child-status"),
                }}
                result=self.forward.join_next(),if !self.forward.is_empty()=> {
                    self.counts.joined(result.expect("nonempty forward set"))?;
                }
                ()=self.signals.snapshot.wait()=> {
                    self.snapshots+=1;
                    if self.snapshots>6 {return Err("wrapper-snapshot-limit");}
                    let mut sample=observe::snapshot(self.pid,self.snapshots,self.origin);
                    sample["forward"]=self.counts.value();
                    self.events.emit("snapshot",sample)?;
                }
                accepted=listener.accept()=> {
                    let (stream,_)=accepted.map_err(|_|"wrapper-listener-accept")?;
                    if self.forward.len()>=forward::CAPACITY {self.counts.rejected()?;drop(stream);}
                    else {self.counts.accepted()?;self.forward.spawn(forward::connection(stream));}
                }
                ()=&mut lifetime=>return Err("wrapper-lifetime-limit"),
            }
        }
    }

    async fn ready(&mut self) -> Result<Value> {
        tokio::select! {
            biased;
            ()=self.signals.stop.wait()=> {self.stop_requested=true;Err("wrapper-stopped-before-ready")}
            result=self.child.wait()=> {self.early_exit=Some(result);Err("child-exited-before-ready")}
            notice=self.received.recv()=>match notice {
                Some(streams::Notice::Ready(value))=>Ok(value),
                Some(streams::Notice::Failed(reason))=>Err(reason),
                _=>Err("child-output-ended-before-ready"),
            },
            ()=self.signals.snapshot.wait()=>Err("wrapper-snapshot-before-ready"),
        }
    }

    async fn cleanup(&mut self, result: Result<()>) -> Result<()> {
        // serve's listener has dropped. The same child and copy tasks remain
        // owned through TERM, native EOF, every join, and the final reap.
        let exit = child::stop(&mut self.child, self.early_exit.take()).await;
        let copies = self.drain_copies().await;
        let (stdout, stderr) =
            tokio::join!(join_output(&mut self.stdout), join_output(&mut self.stderr));
        let outputs_joined = stdout.0 && stderr.0;
        let stdout = stdout.1;
        let stderr = stderr.1;
        let clean = result.is_ok()
            && exit.success()
            && copies
            && outputs_joined
            && stdout.as_ref().is_some_and(|r| {
                r.eof && r.error.is_none() && r.ready.is_some() && r.stopped.is_some()
            })
            && stderr.as_ref().is_some_and(|r| r.eof && r.error.is_none())
            && self.counts.live == 0
            && self.counts.failed == 0
            && self.counts.aborted == 0
            && self.counts.rejected == 0;
        self.events.emit("stopped",json!({"clean":clean,"failure":result.err(),"stop_requested":self.stop_requested,
            "child":exit.value(),"forward":self.counts.value(),"copy_tasks_joined":copies,"output_tasks_joined":outputs_joined,
            "stdout":stdout.as_ref().map(|r|r.value("child-stdout.bin")),"stderr":stderr.as_ref().map(|r|r.value("child-stderr.bin")),
            "snapshots":self.snapshots}))?;
        if clean {
            Ok(())
        } else {
            Err("wrapper-cleanup-incomplete")
        }
    }

    async fn drain_copies(&mut self) -> bool {
        let drained = tokio::time::timeout(Duration::from_secs(5), async {
            while let Some(result) = self.forward.join_next().await {
                let _ = self.counts.joined(result);
            }
        })
        .await
        .is_ok();
        if !drained {
            self.forward.abort_all();
            let _ = tokio::time::timeout(Duration::from_secs(1), async {
                while let Some(result) = self.forward.join_next().await {
                    let _ = self.counts.joined(result);
                }
            })
            .await;
        }
        self.forward.is_empty()
    }
}

async fn join_output(task: &mut JoinHandle<streams::Receipt>) -> (bool, Option<streams::Receipt>) {
    if let Ok(result) = tokio::time::timeout(Duration::from_secs(5), &mut *task).await {
        return (true, result.ok());
    }
    task.abort();
    (
        tokio::time::timeout(Duration::from_secs(1), task)
            .await
            .is_ok(),
        None,
    )
}

struct Signals {
    stop: StopSignals,
    snapshot: SnapshotSignal,
}

struct StopSignals {
    #[cfg(unix)]
    terminate: tokio::signal::unix::Signal,
    #[cfg(unix)]
    interrupt: tokio::signal::unix::Signal,
}

struct SnapshotSignal {
    #[cfg(unix)]
    signal: tokio::signal::unix::Signal,
}

impl Signals {
    fn new() -> Result<Self> {
        #[cfg(unix)]
        {
            use tokio::signal::unix::{signal, SignalKind};
            Ok(Self {
                stop: StopSignals {
                    terminate: signal(SignalKind::terminate())
                        .map_err(|_| "wrapper-term-signal")?,
                    interrupt: signal(SignalKind::interrupt()).map_err(|_| "wrapper-int-signal")?,
                },
                snapshot: SnapshotSignal {
                    signal: signal(SignalKind::user_defined1())
                        .map_err(|_| "wrapper-snapshot-signal")?,
                },
            })
        }
        #[cfg(not(unix))]
        {
            Err("wrapper-requires-unix-signals")
        }
    }
}

impl StopSignals {
    async fn wait(&mut self) {
        #[cfg(unix)]
        {
            tokio::select! {_=self.terminate.recv()=>{},_=self.interrupt.recv()=>{}}
        }
        #[cfg(not(unix))]
        {
            std::future::pending::<()>().await;
        }
    }
}

impl SnapshotSignal {
    async fn wait(&mut self) {
        #[cfg(unix)]
        {
            let _ = self.signal.recv().await;
        }
        #[cfg(not(unix))]
        {
            std::future::pending::<()>().await;
        }
    }
}
