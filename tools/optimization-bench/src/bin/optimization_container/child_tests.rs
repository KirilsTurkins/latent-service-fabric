use super::*;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

#[tokio::test]
async fn owned_child_receives_term_and_has_eof_after_actual_reap() {
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "container::child::tests::child_waits_for_term",
            "--ignored",
            "--nocapture",
        ])
        .env("LSF_CONTAINER_TEST_CHILD", "term")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut stdout = BufReader::new(child.stdout.take().unwrap());
    let mut stderr = child.stderr.take().unwrap();
    let ready = tokio::time::timeout(Duration::from_secs(2), async {
        for _ in 0..8 {
            let mut line = String::new();
            if stdout.read_line(&mut line).await.unwrap() == 0 {
                break;
            }
            if line.trim() == "container-child-ready" {
                return true;
            }
        }
        false
    })
    .await
    .unwrap_or(false);
    // Always stop/join even when the readiness assertion will fail.
    let exit = stop(&mut child, None).await;
    let mut remaining = String::new();
    tokio::time::timeout(
        Duration::from_secs(2),
        stdout.read_to_string(&mut remaining),
    )
    .await
    .unwrap()
    .unwrap();
    let mut errors = Vec::new();
    tokio::time::timeout(Duration::from_secs(2), stderr.read_to_end(&mut errors))
        .await
        .unwrap()
        .unwrap();
    assert!(ready);
    assert!(exit.success());
    assert!(exit.term_sent);
    assert!(exit.reaped && child.id().is_none());
    assert!(remaining.contains("container-child-stopped"));
    assert!(errors.is_empty());
}

#[test]
#[ignore = "bounded subprocess fixture, invoked only by the owned-child test"]
fn child_waits_for_term() {
    if std::env::var_os("LSF_CONTAINER_TEST_CHILD").is_none() {
        return;
    }
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        use std::io::Write;
        let mut term =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).unwrap();
        println!("\ncontainer-child-ready");
        std::io::stdout().flush().unwrap();
        tokio::time::timeout(Duration::from_secs(10), term.recv())
            .await
            .unwrap()
            .unwrap();
        println!("container-child-stopped");
        std::io::stdout().flush().unwrap();
    });
}
