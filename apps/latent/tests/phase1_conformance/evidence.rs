#[path = "evidence/identity.rs"]
mod identity;

use std::io::Write;
use std::path::{Path, PathBuf};

use latent_testkit::conformance::{
    ArtifactReference, CaseEvidence, ConformanceReport, DriverEvidence, EvidenceStatus,
    ReportLimits, WorkCounter, WorkCounts, CASE_MANIFEST,
};
use serde_json::Value;

use super::fixtures::{bounded_file, required_path, Fixtures};
use super::harness::Harness;

pub struct Evidence {
    pub report: ConformanceReport,
    pub output: PathBuf,
    work: WorkCounter,
    current: Option<(String, WorkCounts)>,
}

impl Evidence {
    pub fn new(
        output: PathBuf,
        work: WorkCounter,
        public_config: &Value,
        fixtures: &Fixtures,
    ) -> Self {
        let identity = identity::load(public_config, fixtures);
        let mut report = ConformanceReport::new(
            identity,
            identity::environment(),
            public_config.clone(),
            sha256(CASE_MANIFEST.as_bytes()),
        );
        for (name, package) in ["generic", "echo", "capabilities", "dormant"]
            .into_iter()
            .zip(fixtures.packages())
        {
            for (kind, source) in [
                ("manifest", &package.manifest),
                ("contracts", &package.contracts),
            ] {
                let bytes = bounded_file(source, 1024 * 1024);
                report.artifacts.push(write_artifact(
                    &output,
                    &format!("fixture-{name}-{kind}.json"),
                    &bytes,
                ));
            }
        }
        Self {
            report,
            output,
            work,
            current: None,
        }
    }

    pub fn begin(&mut self, id: &str) {
        assert!(self.current.is_none(), "case evidence must partition work");
        self.current = Some((id.to_owned(), self.work.snapshot()));
    }

    pub fn passed(&mut self, harness: &mut Harness, observations: Value) {
        let (id, start) = self.current.take().expect("active evidence case");
        let work = delta(start, self.work.snapshot());
        let bytes = serde_json::to_vec(&observations).expect("bounded case observations");
        assert!(bytes.len() <= 256 * 1024, "case observation ceiling");
        let artifact = write_artifact(&self.output, &format!("case-{id}.json"), &bytes);
        let mut case = CaseEvidence::passed(id, work, observations);
        case.diagnostics.push(artifact.path.clone());
        self.report.artifacts.push(artifact);
        self.report.artifacts.extend(harness.take_artifacts());
        self.report
            .record_case(case)
            .expect("fixed unique case manifest");
        self.save();
    }

    pub fn finish(&mut self) {
        assert!(self.current.is_none());
        let path = required_path("LSF_PHASE1_PARITY_REPORT");
        let bytes = bounded_file(&path, 1024 * 1024);
        let fragment: DriverEvidence =
            serde_json::from_slice(&bytes).expect("required adapter parity evidence");
        self.report
            .merge_driver(fragment)
            .expect("exact adapter fragment");
        self.report.artifacts.push(write_artifact(
            &self.output,
            "adapter-fragment.json",
            &bytes,
        ));
        self.report
            .finish_process(self.work.snapshot())
            .expect("process work within hard ceiling");
        self.report
            .validate_deterministic()
            .expect("all selected bounded cases passed");
        self.save();
    }

    fn save(&self) {
        let bytes = self
            .report
            .encode_bounded(ReportLimits::default())
            .expect("bounded conformance report");
        std::fs::write(self.output.join("conformance.json"), bytes)
            .expect("conformance evidence file");
    }
}

impl Drop for Evidence {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.report.deterministic_status = EvidenceStatus::Failed;
            if let Some((id, start)) = self.current.take() {
                let _ = self.report.record_case(CaseEvidence {
                    id,
                    status: EvidenceStatus::Failed,
                    reason: Some("driver-assertion-failed".to_owned()),
                    work: delta(start, self.work.snapshot()),
                    observations: Value::Null,
                    diagnostics: Vec::new(),
                });
            }
            if !self
                .report
                .drivers
                .iter()
                .any(|driver| driver.driver == "process")
            {
                let _ = self.report.finish_process(self.work.snapshot());
            }
            if let Ok(bytes) = self.report.encode_bounded(ReportLimits::default()) {
                let _ = std::fs::write(self.output.join("conformance.json"), bytes);
            }
        }
    }
}

fn delta(before: WorkCounts, after: WorkCounts) -> WorkCounts {
    WorkCounts {
        commands: after
            .commands
            .checked_sub(before.commands)
            .expect("monotonic command count"),
        invoke_attempts: after
            .invoke_attempts
            .checked_sub(before.invoke_attempts)
            .expect("monotonic Invoke count"),
        budget_exhausted: after.budget_exhausted,
    }
}

pub fn sha256(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("sha256:{:x}", Sha256::digest(bytes))
}

pub fn write_artifact(root: &Path, name: &str, bytes: &[u8]) -> ArtifactReference {
    assert!(
        name.len() <= 128 && !name.contains(['/', '\\']),
        "flat portable artifact name"
    );
    assert!(bytes.len() <= 4 * 1024 * 1024, "raw artifact bound");
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))
        .expect("unique raw artifact");
    file.write_all(bytes).expect("raw artifact bytes");
    ArtifactReference {
        path: name.to_owned(),
        sha256: sha256(bytes),
        bytes: u64::try_from(bytes.len()).expect("bounded artifact size"),
    }
}
