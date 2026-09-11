use std::fs::File;
use std::io::Write;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::sync::mpsc;

use super::command::{App, CHILD_LISTEN};

pub(super) const MAX_BYTES: usize = 256 * 1024;
const MAX_LINE: usize = 16 * 1024;

pub(super) enum Notice {
    Ready(Value),
    Stopped,
    Failed(&'static str),
}

pub(super) struct Receipt {
    pub bytes: usize,
    pub lines: u64,
    pub sha256: String,
    pub eof: bool,
    pub error: Option<&'static str>,
    pub ready: Option<Value>,
    pub stopped: Option<Value>,
}

impl Receipt {
    pub fn value(&self, path: &str) -> Value {
        json!({"path":path,"bytes":self.bytes.to_string(),"lines_processed":self.lines.to_string(),
            "sha256":self.sha256,"eof":self.eof,"error":self.error,
            "ready":self.ready,"stopped":self.stopped,"maximum_bytes":MAX_BYTES,"maximum_line_bytes":MAX_LINE})
    }
}

pub(super) async fn drain<R: AsyncRead + Unpin>(
    mut source: R,
    mut file: File,
    app: App,
    stdout: bool,
    notices: mpsc::Sender<Notice>,
) -> Receipt {
    let mut receipt = Receipt {
        bytes: 0,
        lines: 0,
        sha256: String::new(),
        eof: false,
        error: None,
        ready: None,
        stopped: None,
    };
    let mut hash = Sha256::new();
    let mut pending = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        let count = match source.read(&mut chunk).await {
            Ok(0) => {
                receipt.eof = true;
                break;
            }
            Ok(count) => count,
            Err(_) => {
                receipt.error = Some("child-output-read");
                break;
            }
        };
        let retained = count.min(MAX_BYTES - receipt.bytes);
        if write(&mut file, &chunk[..retained], &mut receipt, &mut hash).is_err() {
            receipt.error = Some("child-output-write");
            break;
        }
        if retained != count {
            receipt.error = Some("child-output-byte-limit");
            break;
        }
        for &byte in &chunk[..count] {
            if pending.len() >= MAX_LINE {
                receipt.error = Some("child-output-line-limit");
                break;
            }
            pending.push(byte);
            if byte == b'\n' {
                receipt.lines += 1;
                if stdout {
                    if let Err(error) = line(&pending, app, &mut receipt, &notices) {
                        receipt.error = Some(error);
                        break;
                    }
                }
                pending.clear();
            }
        }
        if receipt.error.is_some() {
            break;
        }
    }
    if receipt.eof && !pending.is_empty() {
        receipt.lines += 1;
        if stdout {
            receipt.error = line(&pending, app, &mut receipt, &notices).err();
        }
    }
    if file.flush().is_err() {
        receipt.error = Some("child-output-flush");
    }
    receipt.sha256 = format!("sha256:{:x}", hash.finalize());
    if let Some(error) = receipt.error {
        let _ = notices.try_send(Notice::Failed(error));
    }
    receipt
}

fn write(
    file: &mut File,
    mut bytes: &[u8],
    receipt: &mut Receipt,
    hash: &mut Sha256,
) -> std::io::Result<()> {
    while !bytes.is_empty() {
        let count = file.write(bytes)?;
        if count == 0 {
            return Err(std::io::Error::from(std::io::ErrorKind::WriteZero));
        }
        receipt.bytes += count;
        hash.update(&bytes[..count]);
        bytes = &bytes[count..];
    }
    Ok(())
}

fn line(
    bytes: &[u8],
    app: App,
    receipt: &mut Receipt,
    notices: &mpsc::Sender<Notice>,
) -> Result<(), &'static str> {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return Ok(());
    };
    match value.get("event").and_then(Value::as_str) {
        Some("ready") => {
            if receipt.ready.is_some() || receipt.stopped.is_some() || !valid_ready(&value, app) {
                return Err("child-ready-record");
            }
            notices
                .try_send(Notice::Ready(value.clone()))
                .map_err(|_| "child-notice-capacity")?;
            receipt.ready = Some(value);
        }
        Some("stopped") => {
            let expected = match app {
                App::Native => {
                    value.get("implementation").and_then(Value::as_str) == Some("native-reference")
                }
                App::Lsf => {
                    value.get("schemaVersion").and_then(Value::as_str)
                        == Some("latent.standalone.status.v1")
                }
            };
            if !expected
                || value.get("clean") != Some(&Value::Bool(true))
                || receipt.stopped.is_some()
            {
                return Err("child-stopped-record");
            }
            notices
                .try_send(Notice::Stopped)
                .map_err(|_| "child-notice-capacity")?;
            receipt.stopped = Some(value);
        }
        _ => {}
    }
    Ok(())
}

fn valid_ready(value: &Value, app: App) -> bool {
    match app {
        App::Native => {
            value.get("implementation").and_then(Value::as_str) == Some("native-reference")
                && value.get("address").and_then(Value::as_str) == Some("http://127.0.0.1:7071")
        }
        App::Lsf => {
            value.get("schemaVersion").and_then(Value::as_str)
                == Some("latent.standalone.status.v1")
                && value.get("ready") == Some(&Value::Bool(true))
                && value.get("endpoint").and_then(Value::as_str) == Some(CHILD_LISTEN)
                && value
                    .get("nodeId")
                    .and_then(Value::as_str)
                    .is_some_and(|id| !id.is_empty() && id.len() <= 512)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn readiness_requires_actual_expected_app_and_loopback_endpoint() {
        let native = json!({"event":"ready","implementation":"native-reference","address":"http://127.0.0.1:7071"});
        assert!(valid_ready(&native, App::Native));
        assert!(!valid_ready(&native, App::Lsf));
        let mut wrong = native;
        wrong["address"] = json!("http://0.0.0.0:7071");
        assert!(!valid_ready(&wrong, App::Native));
        let lsf = json!({"schemaVersion":"latent.standalone.status.v1","event":"ready","ready":true,"endpoint":"127.0.0.1:7071","nodeId":"node"});
        assert!(valid_ready(&lsf, App::Lsf));
    }

    #[tokio::test]
    async fn exact_stream_receipt_hashes_retained_bytes_and_marks_limit_failure() {
        for (index,data,expected) in [
            (0,b"{\"event\":\"ready\",\"implementation\":\"native-reference\",\"address\":\"http://127.0.0.1:7071\"}\n{\"event\":\"stopped\",\"implementation\":\"native-reference\",\"clean\":true}\n".to_vec(),None),
            (1,vec![b'\n';MAX_BYTES+1],Some("child-output-byte-limit")),
            (2,vec![b'x';MAX_LINE+1],Some("child-output-line-limit")),
        ] {
            let stamp=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
            let path=std::env::temp_dir().join(format!("lsf-container-stream-{}-{stamp}-{index}.bin",std::process::id()));
            let file=super::super::output::fresh(&path).unwrap();
            let (sender,_receiver)=mpsc::channel(8);
            let receipt=drain(data.as_slice(),file,App::Native,true,sender).await;
            let bytes=std::fs::read(&path).unwrap();
            std::fs::remove_file(&path).unwrap();
            assert_eq!(receipt.bytes,bytes.len());
            assert_eq!(receipt.sha256,format!("sha256:{:x}",Sha256::digest(&bytes)));
            assert_eq!(receipt.error,expected);
            assert!(bytes.len()<=MAX_BYTES);
            if expected.is_none() {assert!(receipt.eof && receipt.ready.is_some() && receipt.stopped.is_some());}
            else {assert!(!receipt.eof);}
        }
    }
}
