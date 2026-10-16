use super::*;
use latent_core::{transaction_contract::Value, BudgetProfile};
use latent_executor::transaction::{
    CommandInfo, Intent, IntentFailure, Mode, Page, RetainedTransfer, StateFailure,
    TransactionHost, VersionedValue, ViewIdentity,
};
use latent_executor::{ExecutionCancellation, ExecutionCancellationProbe};

struct Host {
    id: latent_core::ActivationId,
    budget: latent_core::ActivationBudget,
}
impl TransactionHost for Host {
    fn observe_host_result(&self, _: latent_executor::HostResultDisposition) {}
    fn activation_id(&self) -> &latent_core::ActivationId {
        &self.id
    }
    fn mode(&self) -> Mode {
        Mode::Query
    }
    fn budget(&self) -> &latent_core::ActivationBudget {
        &self.budget
    }
    fn acquire(&self, _: Mode) -> Result<(), StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn release(&self, _: Mode) {
        panic!("matching imports never acquires a transaction")
    }
    fn view_identity(&self) -> Result<ViewIdentity, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn command_info(&self) -> Result<CommandInfo, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn authorize_read(&self) -> Result<(), StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn retain_transfer(&self, _: usize) -> Result<RetainedTransfer, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn read(
        &self,
        _: Vec<u8>,
    ) -> latent_core::BoxFuture<'_, Result<Option<VersionedValue>, StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn scan(
        &self,
        _: Vec<u8>,
        _: u32,
        _: Option<Vec<u8>>,
    ) -> latent_core::BoxFuture<'_, Result<Page, StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn put(&self, _: Vec<u8>, _: Value) -> latent_core::BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn delete(&self, _: Vec<u8>) -> latent_core::BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn stage(&self, _: Intent) -> latent_core::BoxFuture<'_, Result<u32, IntentFailure>> {
        Box::pin(async { Err(IntentFailure::PermissionDenied) })
    }
    fn finish_guest_access(&self) {
        panic!("session matching does not own Store retirement")
    }
}
struct TransactionControl {
    original: Control,
    host: Option<Arc<Host>>,
}
impl ExecutionCancellation for TransactionControl {
    fn activation_id(&self) -> &latent_core::ActivationId {
        &self.original.id
    }
    fn is_cancelled(&self) -> bool {
        self.original.is_cancelled()
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&latent_core::ActivationBudget> {
        Some(&self.original.budget)
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        self.original.probe()
    }
    fn transaction_host(&self) -> Option<Arc<dyn TransactionHost>> {
        self.host
            .as_ref()
            .map(|host| host.clone() as Arc<dyn TransactionHost>)
    }
}
fn scoped_import(contract: &str) -> latent_executor::BoundImport {
    latent_executor::BoundImport {
        capability: latent_core::CapabilityId(contract.into()),
        contract: contract.into(),
        opaque_handle: "descriptive-only".into(),
    }
}
fn selected(fixture: &Fixture) -> (latent_executor::ExecutionRequest, TransactionControl) {
    let (mut request, mut control) = fixture.request("scoped-transaction");
    let resources = request.budget.clone();
    let grant = latent_core::EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase4,
        &resources,
        &resources,
        &resources,
        None,
        latent_core::ClockSample::system_now(),
    )
    .unwrap();
    control.budget =
        latent_core::ActivationBudget::with_profile(grant, BudgetProfile::Phase4).unwrap();
    request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
    request.imports.extend([
        scoped_import(crate::namespace::STATE_CONTRACT),
        scoped_import(crate::namespace::INTENT_CONTRACT),
    ]);
    let host = Arc::new(Host {
        id: control.id.clone(),
        budget: control.budget.clone(),
    });
    (
        request,
        TransactionControl {
            original: control,
            host: Some(host),
        },
    )
}
fn opens(
    fixture: &Fixture,
    request: &latent_executor::ExecutionRequest,
    control: &TransactionControl,
) -> bool {
    fixture
        .broker
        .open_session(fixture.plan.clone(), request, control, &fixture.publication)
        .is_ok()
}
#[test]
fn original_transaction_imports_open_only_the_unchanged_provider_session() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = selected(&fixture);
    let session = fixture
        .broker
        .open_session(
            fixture.plan.clone(),
            &request,
            &control,
            &fixture.publication,
        )
        .unwrap();
    assert!(session
        .bind(
            crate::namespace::STATE_CONTRACT,
            "acquire-query",
            ResourceTarget::Clock
        )
        .is_err());
    assert!(session
        .bind(
            crate::namespace::INTENT_CONTRACT,
            "stage",
            ResourceTarget::Clock
        )
        .is_err());
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert!(call(&session, handle).is_ok());
    session.close_handle(handle).unwrap();
    session.close();
    drop(session);
    let mut state_only = request;
    state_only.imports.pop();
    assert!(opens(&fixture, &state_only, &control));
    let mut denied_http = state_only;
    denied_http
        .imports
        .push(scoped_import(crate::broker::http::HTTP_CAPABILITY));
    let session = fixture
        .broker
        .open_session(
            fixture.plan.clone(),
            &denied_http,
            &control,
            &fixture.publication,
        )
        .unwrap();
    assert!(session
        .bind(
            crate::broker::http::HTTP_CAPABILITY,
            "send",
            ResourceTarget::Clock
        )
        .is_err());
}
#[test]
fn descriptive_or_foreign_transaction_imports_cannot_open_a_session() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, mut control) = selected(&fixture);
    let original = control.host.take();
    assert!(!opens(&fixture, &request, &control));
    control.host = original;
    for index in [0, 1] {
        let mut missing = request.clone();
        missing.imports.remove(index);
        assert!(!opens(&fixture, &missing, &control));
    }
    for index in [1, 2] {
        let mut duplicate = request.clone();
        duplicate.imports.push(request.imports[index].clone());
        assert!(!opens(&fixture, &duplicate, &control));
        for replacement in ["unknown", "latent:streaming-http/client@0.3.0"] {
            let mut wrong = request.clone();
            wrong.imports[index] = scoped_import(replacement);
            assert!(!opens(&fixture, &wrong, &control));
        }
        let mut forged = request.clone();
        forged.imports[index].capability.0 = "forged".into();
        assert!(!opens(&fixture, &forged, &control));
        forged = request.clone();
        forged.imports[index].opaque_handle.clear();
        assert!(!opens(&fixture, &forged, &control));
    }
    let original = control.host.take().unwrap();
    control.host = Some(Arc::new(Host {
        id: latent_core::ActivationId("foreign".into()),
        budget: original.budget.clone(),
    }));
    assert!(!opens(&fixture, &request, &control));
    let (_, other) = selected(&fixture);
    control.host = Some(Arc::new(Host {
        id: original.id.clone(),
        budget: other.original.budget,
    }));
    assert!(!opens(&fixture, &request, &control));
    control.host = Some(original);
    let ordinary = fixture.request("scoped-transaction").1;
    let phase4 = std::mem::replace(&mut control.original, ordinary);
    assert!(!opens(&fixture, &request, &control));
    control.original = phase4;
    let mut nested = request.clone();
    nested.activation.parent_activation_id = Some(latent_core::ActivationId("parent".into()));
    assert!(!opens(&fixture, &nested, &control));
    let mut web = request;
    web.imports
        .push(scoped_import("latent:context/context@0.1.0"));
    assert!(!opens(&fixture, &web, &control));
}

#[test]
fn narrowed_runtime_deadline_retains_the_original_transaction_owner() {
    struct Plan(Arc<CompiledCapabilityPlan>);
    impl CapabilityPlanSource for Plan {
        fn plan(
            &self,
            _: &latent_routing::ResolvedRevision,
        ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
            Ok(self.0.clone())
        }
    }
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = selected(&fixture);
    let runtime = ActivationCapabilityRuntime::new(
        fixture.broker.clone(),
        Arc::new(Plan(fixture.plan.clone())),
    );
    let session = runtime
        .open_session(
            &request,
            &control,
            &fixture.publication,
            control.original.budget.deadline(),
        )
        .unwrap();
    assert!(session
        .core
        .budget
        .is_same_instance(&control.original.budget));
    assert!(session
        .bind(
            crate::namespace::STATE_CONTRACT,
            "acquire-query",
            ResourceTarget::Clock
        )
        .is_err());
    session.close();
    drop(session);
    let mut absent = control;
    absent.host = None;
    assert!(runtime
        .open_session(
            &request,
            &absent,
            &fixture.publication,
            absent.original.budget.deadline()
        )
        .is_err());
}
