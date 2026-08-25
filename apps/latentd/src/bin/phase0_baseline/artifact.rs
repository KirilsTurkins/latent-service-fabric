fn load_artifact(capsule: &Path) -> Result<LoadedArtifact, BenchError> {
    let manifest_path = if capsule.is_dir() {
        capsule.join("capsule.json")
    } else {
        capsule.to_owned()
    };
    if !manifest_path.is_file() {
        return Err(BenchError::new(format!(
            "capsule manifest is not a readable file: {}",
            manifest_path.display()
        )));
    }
    let manifest_bytes = fs::read(&manifest_path)?;
    let document: CapsuleDocument = serde_json::from_slice(&manifest_bytes)?;
    let manifest = document.into_manifest()?;
    let base_directory = manifest_path.parent().unwrap_or_else(|| Path::new("."));
    let component_path = manifest
        .metadata
        .annotations
        .get("latent.dev/artifact")
        .map(|path| base_directory.join(path))
        .ok_or_else(|| BenchError::new("capsule lacks latent.dev/artifact annotation"))?;
    if !component_path.is_file() {
        return Err(BenchError::new(format!(
            "component is not a readable file: {}",
            component_path.display()
        )));
    }
    let bytes = fs::read(&component_path)?;
    if bytes.is_empty() || bytes.len() > COMPONENT_MAXIMUM_BYTES {
        return Err(BenchError::new(format!(
            "component size {} is outside 1..={COMPONENT_MAXIMUM_BYTES}",
            bytes.len()
        )));
    }
    if bytes.len() > PREPARED_CACHE_MAXIMUM_BYTES {
        return Err(BenchError::new(
            "component cannot fit in the configured prepared cache",
        ));
    }
    let actual_digest = component_digest(&bytes);
    if manifest.component_digest.0 != actual_digest {
        return Err(BenchError::new(format!(
            "component digest mismatch: expected {}, actual {actual_digest}",
            manifest.component_digest.0
        )));
    }
    let component_bytes = u64::try_from(bytes.len())
        .map_err(|_| BenchError::new("component size does not fit u64"))?;
    let descriptor = ArtifactDescriptor {
        reference: ArtifactReference(format!("file://{}", component_path.display())),
        release_digest: manifest.component_digest.clone(),
        media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
        size_bytes: component_bytes,
        publisher: None,
        layers: Vec::new(),
        annotations: manifest.metadata.annotations.clone(),
    };
    Ok(LoadedArtifact {
        artifact: CapsuleArtifact {
            descriptor,
            manifest,
            contracts: Vec::new(),
            component_bytes: bytes,
        },
        component_path,
        component_bytes,
    })
}

fn validate_requested_budgets(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
) -> Result<(), BenchError> {
    let declared = &manifest.execution.resource_budget_ceiling;
    if declared.memory_bytes == 0 || declared.cpu_fuel == 0 {
        return Err(BenchError::new(
            "capsule declares a zero memory or fuel ceiling",
        ));
    }
    if config.memory_bytes > declared.memory_bytes
        || config.memory_pressure_bytes > declared.memory_bytes
        || config.fuel > declared.cpu_fuel
    {
        return Err(BenchError::new(format!(
            "requested budgets exceed capsule ceiling: requested memory={} pressure_memory={} fuel={}, declared memory={} fuel={}",
            config.memory_bytes,
            config.memory_pressure_bytes,
            config.fuel,
            declared.memory_bytes,
            declared.cpu_fuel
        )));
    }
    Ok(())
}

fn activation_envelope(
    manifest: &CapsuleManifest,
    activation_id: ActivationId,
    input: &str,
    memory_bytes: u64,
    fuel: u64,
    deadline: u64,
) -> ActivationEnvelope {
    let tenant = manifest
        .metadata
        .tenant
        .clone()
        .unwrap_or_else(|| TenantId("phase0-baseline".to_owned()));
    let mut budget = manifest.execution.resource_budget_ceiling.clone();
    budget.cpu_fuel = fuel;
    budget.memory_bytes = memory_bytes;
    budget.wall_deadline_unix_millis = Some(deadline);

    ActivationEnvelope {
        activation_id: activation_id.clone(),
        parent_activation_id: None,
        root_activation_id: activation_id,
        principal: InvocationPrincipal {
            subject: "phase0-baseline-user".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(tenant.clone()),
            service: None,
            claims: Metadata::from([
                ("role".to_owned(), "phase0-baseline".to_owned()),
                ("surface".to_owned(), SURFACE.to_owned()),
            ]),
        },
        target: InvocationTarget {
            tenant,
            service: ServiceId("echo".to_owned()),
            contract: ContractId(ECHO_EXPORT.to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: Some(deadline),
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId(TRACE_ID.to_owned()),
            span_id: SpanId(SPAN_ID.to_owned()),
            trace_flags: 1,
            baggage: Metadata::from([("surface".to_owned(), SURFACE.to_owned())]),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget,
        metadata: Metadata::from([
            ("mode".to_owned(), "phase0-baseline".to_owned()),
            ("production-ready".to_owned(), "false".to_owned()),
        ]),
        input: input.as_bytes().to_vec(),
        input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
    }
}

fn bound_imports() -> Vec<BoundImport> {
    vec![
        BoundImport {
            capability: CapabilityId("context".to_owned()),
            contract: CONTEXT_IMPORT.to_owned(),
            opaque_handle: "phase0-baseline-activation-context".to_owned(),
        },
        BoundImport {
            capability: CapabilityId("log".to_owned()),
            contract: LOG_IMPORT.to_owned(),
            opaque_handle: "phase0-baseline-bounded-log".to_owned(),
        },
    ]
}

fn component_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CapsuleDocument {
    api_version: String,
    kind: String,
    metadata: MetadataDocument,
    component: ComponentDocument,
    exports: Vec<String>,
    imports: Vec<ImportDocument>,
    execution: ExecutionDocument,
    compatibility: CompatibilityDocument,
}

#[derive(Debug, Deserialize)]
struct MetadataDocument {
    name: String,
    #[serde(default)]
    tenant: Option<String>,
    #[serde(default)]
    namespace: Option<String>,
    #[serde(default)]
    labels: BTreeMap<String, String>,
    #[serde(default)]
    annotations: BTreeMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct ComponentDocument {
    digest: String,
    version: String,
    world: String,
}

#[derive(Debug, Deserialize)]
struct ImportDocument {
    contract: String,
    optional: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ExecutionDocument {
    backend: String,
    threading: String,
    state_model: String,
    limits: LimitsDocument,
    host_call_depth_maximum: u32,
    component_call_depth_maximum: u32,
    snapshot_eligible: bool,
    fusion_eligible: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LimitsDocument {
    cpu_fuel: u64,
    memory_bytes: u64,
    wall_deadline_unix_millis: Option<u64>,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CompatibilityDocument {
    minimum_fabric_version: String,
}

impl CapsuleDocument {
    fn into_manifest(self) -> Result<CapsuleManifest, BenchError> {
        if self.kind != "Capsule" {
            return Err(BenchError::new(format!(
                "capsule document kind must be Capsule, found {}",
                self.kind
            )));
        }
        if self.metadata.name.trim().is_empty()
            || self.component.digest.trim().is_empty()
            || self.component.version.trim().is_empty()
            || self.component.world.trim().is_empty()
        {
            return Err(BenchError::new(
                "capsule identity and component fields must be non-empty",
            ));
        }
        let backend = match self.execution.backend.as_str() {
            "wasm-component" => ExecutionBackendKind::WasmComponent,
            value => {
                return Err(BenchError::new(format!(
                    "unsupported execution backend {value}"
                )));
            }
        };
        let threading = match self.execution.threading.as_str() {
            "single-threaded" => ThreadingModel::SingleThreaded,
            "reentrant" => ThreadingModel::Reentrant,
            "cooperative" => ThreadingModel::Cooperative,
            value => {
                return Err(BenchError::new(format!(
                    "unknown threading model {value}"
                )));
            }
        };
        let state_model = match self.execution.state_model.as_str() {
            "stateless" => StateModel::Stateless,
            "transactional-keyed" => StateModel::TransactionalKeyed,
            "entity" => StateModel::Entity,
            "durable-workflow" => StateModel::DurableWorkflow,
            value => {
                return Err(BenchError::new(format!("unknown state model {value}")));
            }
        };
        let limits = self.execution.limits;
        Ok(CapsuleManifest {
            api_version: self.api_version,
            metadata: ObjectMetadata {
                name: self.metadata.name,
                tenant: self.metadata.tenant.map(TenantId),
                namespace: self.metadata.namespace,
                labels: self.metadata.labels,
                annotations: self.metadata.annotations,
            },
            semantic_version: self.component.version,
            component_digest: ReleaseDigest(self.component.digest),
            world: ContractId(self.component.world),
            exports: self
                .exports
                .into_iter()
                .map(|contract| ContractExport {
                    contract: ContractId(contract),
                })
                .collect(),
            imports: self
                .imports
                .into_iter()
                .map(|import| ContractImport {
                    contract: ContractId(import.contract),
                    optional: import.optional,
                })
                .collect(),
            execution: ExecutionRequirements {
                backend,
                threading,
                state_model,
                resource_budget_ceiling: ResourceBudget {
                    cpu_fuel: limits.cpu_fuel,
                    memory_bytes: limits.memory_bytes,
                    wall_deadline_unix_millis: limits.wall_deadline_unix_millis,
                    child_calls: limits.child_calls,
                    outbound_requests: limits.outbound_requests,
                    state_read_bytes: limits.state_read_bytes,
                    state_write_bytes: limits.state_write_bytes,
                    blob_read_bytes: limits.blob_read_bytes,
                    blob_write_bytes: limits.blob_write_bytes,
                    log_bytes: limits.log_bytes,
                    effect_count: limits.effect_count,
                },
                host_call_depth_maximum: self.execution.host_call_depth_maximum,
                component_call_depth_maximum: self.execution.component_call_depth_maximum,
                snapshot_eligible: self.execution.snapshot_eligible,
                fusion_eligible: self.execution.fusion_eligible,
            },
            minimum_fabric_version: self.compatibility.minimum_fabric_version,
        })
    }
}
