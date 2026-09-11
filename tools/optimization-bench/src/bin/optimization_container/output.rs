use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::path::Path;
use std::time::Instant;

use serde_json::{json, Value};

use super::{command::App, Result};

pub(super) struct Events {
    file: File,
    origin: Instant,
    app: App,
    child: u32,
    sequence: u32,
}

pub(super) fn fresh(path: &Path) -> Result<File> {
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|_| "wrapper-output-open")
}

impl Events {
    pub fn new(file: File, origin: Instant, app: App, child: u32) -> Self {
        Self {
            file,
            origin,
            app,
            child,
            sequence: 0,
        }
    }
    pub fn emit(&mut self, event: &'static str, detail: &Value) -> Result<()> {
        if self.sequence >= 10 {
            return Err("wrapper-event-count");
        }
        let value = json!({"schema":"latent.optimization.container-event.v1", "sequence":self.sequence,
            "event":event,"app":self.app.name(),"wrapper_pid":std::process::id(),"child_pid":self.child,
            "elapsed_nanos":self.origin.elapsed().as_nanos().to_string(),"detail":detail});
        let mut bytes = serde_json::to_vec(&value).map_err(|_| "wrapper-event-encoding")?;
        if bytes.len() >= 512 * 1024 {
            return Err("wrapper-event-size");
        }
        bytes.push(b'\n');
        self.file
            .write_all(&bytes)
            .and_then(|()| self.file.flush())
            .map_err(|_| "wrapper-event-file")?;
        self.sequence += 1;
        let mut stdout = io::stdout().lock();
        stdout
            .write_all(&bytes)
            .and_then(|()| stdout.flush())
            .map_err(|_| "wrapper-event-stdout")
    }
}
