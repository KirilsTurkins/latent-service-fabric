use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::resources::ChildProcessResources;

use super::{
    decimal, EvidenceError, ReportLimits, WorkCounts, CASE_MANIFEST, PROFILE, REPORT_SCHEMA,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceStatus {
    Passed,
    Failed,
    NotRun,
    NotApplicable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileIdentity {
    pub name: String,
    pub sha256: String,
    #[serde(with = "decimal")]
    pub bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReportIdentity {
    pub source_commit: String,
    pub source_tree: String,
    pub source_dirty: bool,
    pub cargo_lock_sha256: String,
    /// SHA-256 of canonical sanitized `public_config` JSON, without credentials.
    pub config_sha256: String,
    pub binaries: Vec<FileIdentity>,
    pub fixtures: Vec<FileIdentity>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactReference {
    pub path: String,
    pub sha256: String,
    #[serde(with = "decimal")]
    pub bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CaseEvidence {
    pub id: String,
    pub status: EvidenceStatus,
    pub reason: Option<String>,
    pub work: WorkCounts,
    pub observations: Value,
    pub diagnostics: Vec<String>,
}

impl CaseEvidence {
    pub fn passed(id: impl Into<String>, work: WorkCounts, observations: Value) -> Self {
        Self {
            id: id.into(),
            status: EvidenceStatus::Passed,
            reason: None,
            work,
            observations,
            diagnostics: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeferredEvidence {
    pub id: String,
    pub status: EvidenceStatus,
    pub reason: String,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessSample {
    #[serde(with = "decimal")]
    pub sequence: u64,
    #[serde(with = "decimal")]
    pub sample_started_micros: u64,
    #[serde(with = "decimal")]
    pub sample_finished_micros: u64,
    pub node_instance: u32,
    pub phase: String,
    pub process: ChildProcessResources,
    pub inventory: Value,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ShutdownEvidence {
    pub node_instance: u32,
    pub process_id: u32,
    #[serde(with = "decimal")]
    pub start_time_ticks: u64,
    pub exit_success: bool,
    pub reaped: bool,
    pub readers_joined: bool,
    /// Exact product shutdown record: its existing numeric wire fields are retained.
    pub report: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DriverEvidence {
    pub driver: String,
    pub cases: Vec<CaseEvidence>,
    pub work: WorkCounts,
    pub artifacts: Vec<ArtifactReference>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ConformanceReport {
    pub schema: String,
    pub profile: String,
    pub case_manifest_sha256: String,
    pub identity: ReportIdentity,
    pub environment: Value,
    pub public_config: Value,
    pub work: WorkCounts,
    pub drivers: Vec<DriverWork>,
    pub cases: Vec<CaseEvidence>,
    pub samples: Vec<ProcessSample>,
    pub shutdowns: Vec<ShutdownEvidence>,
    pub artifacts: Vec<ArtifactReference>,
    pub deferred_evidence: Vec<DeferredEvidence>,
    pub deterministic_status: EvidenceStatus,
    pub phase1_completion: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DriverWork {
    pub driver: String,
    pub work: WorkCounts,
}

impl ConformanceReport {
    #[must_use]
    pub fn new(
        identity: ReportIdentity,
        environment: Value,
        public_config: Value,
        case_manifest_sha256: String,
    ) -> Self {
        let manifest: Value =
            serde_json::from_str(CASE_MANIFEST).expect("checked-in case manifest");
        let strings = |key: &str| -> Vec<String> {
            manifest[key]
                .as_array()
                .expect("manifest array")
                .iter()
                .map(|id| id.as_str().expect("manifest id").to_owned())
                .collect()
        };
        Self {
            schema: REPORT_SCHEMA.to_owned(),
            profile: PROFILE.to_owned(),
            case_manifest_sha256,
            identity,
            environment,
            public_config,
            work: WorkCounts::default(),
            drivers: Vec::new(),
            cases: strings("required_cases")
                .into_iter()
                .map(|id| CaseEvidence {
                    id,
                    status: EvidenceStatus::NotRun,
                    reason: Some("not-started".to_owned()),
                    work: WorkCounts::default(),
                    observations: Value::Null,
                    diagnostics: Vec::new(),
                })
                .collect(),
            samples: Vec::new(),
            shutdowns: Vec::new(),
            artifacts: Vec::new(),
            deferred_evidence: strings("deferred_evidence")
                .into_iter()
                .map(|id| DeferredEvidence {
                    id,
                    status: EvidenceStatus::NotRun,
                    reason: "outside-bounded-profile".to_owned(),
                })
                .collect(),
            deterministic_status: EvidenceStatus::Failed,
            phase1_completion: "incomplete".to_owned(),
        }
    }

    pub fn record_case(&mut self, case: CaseEvidence) -> Result<(), EvidenceError> {
        let slot = self
            .cases
            .iter_mut()
            .find(|entry| entry.id == case.id)
            .ok_or(EvidenceError("unknown-conformance-case"))?;
        if slot.status != EvidenceStatus::NotRun || slot.reason.as_deref() != Some("not-started") {
            return Err(EvidenceError("duplicate-conformance-case"));
        }
        *slot = case;
        self.deterministic_status = EvidenceStatus::Failed;
        Ok(())
    }

    pub fn merge_driver(&mut self, fragment: DriverEvidence) -> Result<(), EvidenceError> {
        self.add_driver(&fragment.driver, fragment.work)?;
        for case in fragment.cases {
            self.record_case(case)?;
        }
        self.artifacts.extend(fragment.artifacts);
        Ok(())
    }

    pub fn finish_process(&mut self, work: WorkCounts) -> Result<(), EvidenceError> {
        self.add_driver("process", work)
    }

    fn add_driver(&mut self, driver: &str, work: WorkCounts) -> Result<(), EvidenceError> {
        let (invokes, commands) = match driver {
            "process" => (
                super::PROCESS_MAXIMUM_INVOKE_ATTEMPTS,
                super::PROCESS_MAXIMUM_COMMANDS,
            ),
            "adapter" => (
                super::ADAPTER_MAXIMUM_INVOKE_ATTEMPTS,
                super::ADAPTER_MAXIMUM_COMMANDS,
            ),
            _ => return Err(EvidenceError("unknown-conformance-driver")),
        };
        if self.drivers.iter().any(|entry| entry.driver == driver)
            || work.invoke_attempts > invokes
            || work.commands > commands
            || work.invoke_attempts > work.commands
        {
            return Err(EvidenceError("invalid-conformance-driver-work"));
        }
        self.work = self
            .work
            .checked_add(work)
            .ok_or(EvidenceError("conformance-work-overflow"))?;
        self.drivers.push(DriverWork {
            driver: driver.to_owned(),
            work,
        });
        Ok(())
    }

    /// Recomputes the verdict from all required cases. The standalone Python
    /// validator additionally verifies identities, measurements and raw files.
    pub fn validate_deterministic(&mut self) -> Result<(), EvidenceError> {
        self.deterministic_status = EvidenceStatus::Failed;
        let manifest: Value =
            serde_json::from_str(CASE_MANIFEST).expect("checked-in case manifest");
        let required = manifest["required_cases"]
            .as_array()
            .expect("manifest cases");
        if self.cases.len() != required.len()
            || !self
                .work
                .within(super::MAXIMUM_INVOKE_ATTEMPTS, super::MAXIMUM_COMMANDS)
            || self.drivers.len() != 2
            || self.work.commands > super::MAXIMUM_COMMANDS
            || self.work.invoke_attempts > super::MAXIMUM_INVOKE_ATTEMPTS
            || self.samples.is_empty()
            || self.shutdowns.is_empty()
            || self.phase1_completion != "incomplete"
            || self.schema != REPORT_SCHEMA
            || self.profile != PROFILE
            || !self.valid_driver_counts()
            || !self.valid_deferred(&manifest)
            || required.iter().any(|id| {
                self.cases
                    .iter()
                    .filter(|case| {
                        Some(case.id.as_str()) == id.as_str()
                            && case.status == EvidenceStatus::Passed
                            && case.reason.is_none()
                            && case
                                .observations
                                .as_object()
                                .is_some_and(|value| !value.is_empty())
                            && case
                                .work
                                .within(super::MAXIMUM_INVOKE_ATTEMPTS, super::MAXIMUM_COMMANDS)
                    })
                    .count()
                    != 1
            })
        {
            return Err(EvidenceError("incomplete-deterministic-evidence"));
        }
        self.deterministic_status = EvidenceStatus::Passed;
        Ok(())
    }

    fn valid_driver_counts(&self) -> bool {
        let cases = self
            .cases
            .iter()
            .try_fold(WorkCounts::default(), |total, case| {
                total.checked_add(case.work)
            });
        let drivers = self
            .drivers
            .iter()
            .try_fold(WorkCounts::default(), |total, driver| {
                total.checked_add(driver.work)
            });
        cases == Some(self.work)
            && drivers == Some(self.work)
            && self
                .drivers
                .iter()
                .filter(|driver| {
                    driver.driver == "process"
                        && driver.work.within(
                            super::PROCESS_MAXIMUM_INVOKE_ATTEMPTS,
                            super::PROCESS_MAXIMUM_COMMANDS,
                        )
                })
                .count()
                == 1
            && self
                .drivers
                .iter()
                .filter(|driver| {
                    driver.driver == "adapter"
                        && driver.work.within(
                            super::ADAPTER_MAXIMUM_INVOKE_ATTEMPTS,
                            super::ADAPTER_MAXIMUM_COMMANDS,
                        )
                        && driver.work.invoke_attempts == super::REQUIRED_ADAPTER_INVOKE_ATTEMPTS
                        && self
                            .cases
                            .iter()
                            .any(|case| case.id == "adapter-rpc-parity" && case.work == driver.work)
                })
                .count()
                == 1
    }

    fn valid_deferred(&self, manifest: &Value) -> bool {
        let required = manifest["deferred_evidence"]
            .as_array()
            .expect("manifest deferred evidence");
        self.deferred_evidence.len() == required.len()
            && required.iter().all(|id| {
                self.deferred_evidence
                    .iter()
                    .filter(|entry| {
                        Some(entry.id.as_str()) == id.as_str()
                            && entry.status == EvidenceStatus::NotRun
                            && entry.reason == "outside-bounded-profile"
                    })
                    .count()
                    == 1
            })
    }

    /// Can serialize failed/partial evidence as well as successful reports.
    pub fn encode_bounded(&self, limits: ReportLimits) -> Result<Vec<u8>, EvidenceError> {
        super::writer::encode_bounded(self, limits)
    }
}
