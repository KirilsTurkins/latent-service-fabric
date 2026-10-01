// Generated bounded visitors. Do not edit.
use super::codec::Budget;
use crate::transaction as model;
use latent_rpc::phase4::ValidationError;

fn transaction_profile(
    value: &model::TransactionProfile,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::TransactionProfile>(), depth)?;
    {
        let member = &value.profile;
        budget.data(member.len())?;
    }
    {
        let member = &value.host_abi_digest;
        budget.data(member.len())?;
    }
    {
        let member = &value.preparation_profile_digest;
        budget.data(member.len())?;
    }
    Ok(())
}

fn legacy_invocation_target(
    value: &crate::management::InvocationTarget,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<crate::management::InvocationTarget>(),
        depth,
    )?;
    {
        let member = &value.tenant;
        budget.data(member.len())?;
    }
    {
        let member = &value.service;
        budget.data(member.len())?;
    }
    {
        let member = &value.contract;
        budget.data(member.len())?;
    }
    {
        let member = &value.function;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.route {
        budget.data(member.len())?;
    }
    Ok(())
}

fn legacy_resource_budget(
    value: &crate::management::ResourceBudget,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<crate::management::ResourceBudget>(),
        depth,
    )?;
    Ok(())
}

fn legacy_invoke_request(
    value: &crate::management::InvokeRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<crate::management::InvokeRequest>(),
        depth,
    )?;
    if let Some(member) = &value.activation_id {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.parent_activation_id {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.root_activation_id {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.target {
        legacy_invocation_target(member, depth + 1, budget)?;
    }
    {
        let member = &value.payload;
        budget.data(member.len())?;
    }
    {
        let member = &value.media_type;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.idempotency_key {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.budget {
        legacy_resource_budget(member, depth + 1, budget)?;
    }
    if value.metadata.len() > 32 {
        return Err(ValidationError::Capacity);
    }
    for (key, member) in &value.metadata {
        budget.data(key.len())?;
        budget.data(member.len())?;
    }
    Ok(())
}

fn namespace_selector(
    value: &model::NamespaceSelector,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::NamespaceSelector>(), depth)?;
    {
        let member = &value.tenant;
        budget.data(member.len())?;
    }
    {
        let member = &value.namespace;
        budget.data(member.len())?;
    }
    {
        let member = &value.incarnation;
        budget.data(member.len())?;
    }
    Ok(())
}

fn command_selector(
    value: &model::CommandSelector,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::CommandSelector>(), depth)?;
    if let Some(member) = &value.namespace {
        namespace_selector(member, depth + 1, budget)?;
    }
    {
        let member = &value.operation;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.entity {
        budget.data(member.len())?;
    }
    {
        let member = &value.client_key;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.shared_recovery_scope {
        budget.data(member.len())?;
    }
    Ok(())
}

fn expected_version(
    value: &model::ExpectedVersion,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::ExpectedVersion>(), depth)?;
    {
        let member = &value.key;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.version {
        budget.data(member.len())?;
    }
    Ok(())
}

fn abort_fence(
    value: &model::AbortFence,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::AbortFence>(), depth)?;
    {
        let member = &value.command_id;
        budget.data(member.len())?;
    }
    {
        let member = &value.attempt_id;
        budget.data(member.len())?;
    }
    {
        let member = &value.transaction_id;
        budget.data(member.len())?;
    }
    {
        let member = &value.owner_fence;
        budget.data(member.len())?;
    }
    Ok(())
}

fn retry_attempt(
    value: &model::RetryAttempt,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::RetryAttempt>(), depth)?;
    {
        let member = &value.request_id;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.expected_abort {
        abort_fence(member, depth + 1, budget)?;
    }
    Ok(())
}

fn invoke_command_request(
    value: &model::InvokeCommandRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::InvokeCommandRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.invocation {
        legacy_invoke_request(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.command {
        command_selector(member, depth + 1, budget)?;
    }
    {
        let member = &value.input_format;
        budget.data(member.len())?;
    }
    if value.expected_versions.len() > 128 {
        return Err(ValidationError::Capacity);
    }
    for member in &value.expected_versions {
        expected_version(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.retry_attempt {
        retry_attempt(member, depth + 1, budget)?;
    }
    Ok(())
}

fn query_request(
    value: &model::QueryRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::QueryRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.invocation {
        legacy_invoke_request(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.namespace {
        namespace_selector(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.entity {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.minimum_view_version {
        budget.data(member.len())?;
    }
    Ok(())
}

fn legacy_publication_ref(
    value: &crate::management::PublicationRef,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<crate::management::PublicationRef>(),
        depth,
    )?;
    {
        let member = &value.id;
        budget.data(member.len())?;
    }
    {
        let member = &value.tenant;
        budget.data(member.len())?;
    }
    Ok(())
}

fn lookup_command_request(
    value: &model::LookupCommandRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::LookupCommandRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.command {
        command_selector(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.attempt_id {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.authorization_publication {
        legacy_publication_ref(member, depth + 1, budget)?;
    }
    Ok(())
}

fn lookup_commit_request(
    value: &model::LookupCommitRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::LookupCommitRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.command {
        command_selector(member, depth + 1, budget)?;
    }
    {
        let member = &value.receipt_id;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.authorization_publication {
        legacy_publication_ref(member, depth + 1, budget)?;
    }
    Ok(())
}

fn get_effect_request(
    value: &model::GetEffectRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::GetEffectRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.command {
        command_selector(member, depth + 1, budget)?;
    }
    {
        let member = &value.effect_id;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.authorization_publication {
        legacy_publication_ref(member, depth + 1, budget)?;
    }
    Ok(())
}

fn page_request(
    value: &model::PageRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::PageRequest>(), depth)?;
    if let Some(member) = &value.cursor {
        budget.data(member.len())?;
    }
    Ok(())
}

fn list_effect_history_request(
    value: &model::ListEffectHistoryRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<model::ListEffectHistoryRequest>(),
        depth,
    )?;
    if let Some(member) = &value.effect {
        get_effect_request(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.page {
        page_request(member, depth + 1, budget)?;
    }
    Ok(())
}

fn cancel_command_request(
    value: &model::CancelCommandRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::CancelCommandRequest>(), depth)?;
    if let Some(member) = &value.command {
        lookup_command_request(member, depth + 1, budget)?;
    }
    {
        let member = &value.reason;
        budget.data(member.len())?;
    }
    Ok(())
}

fn inspect_namespace_request(
    value: &model::InspectNamespaceRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::InspectNamespaceRequest>(), depth)?;
    if let Some(member) = &value.profile {
        transaction_profile(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.namespace {
        namespace_selector(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.authorization_publication {
        legacy_publication_ref(member, depth + 1, budget)?;
    }
    Ok(())
}

fn namespace_quota(
    value: &model::NamespaceQuota,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::NamespaceQuota>(), depth)?;
    Ok(())
}

fn namespace_configuration(
    value: &model::NamespaceConfiguration,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::NamespaceConfiguration>(), depth)?;
    {
        let member = &value.state_schema;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.quota {
        namespace_quota(member, depth + 1, budget)?;
    }
    Ok(())
}

fn mutate_namespace_request(
    value: &model::MutateNamespaceRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::MutateNamespaceRequest>(), depth)?;
    if let Some(member) = &value.namespace {
        inspect_namespace_request(member, depth + 1, budget)?;
    }
    {
        let member = &value.operation_id;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.configuration {
        namespace_configuration(member, depth + 1, budget)?;
    }
    Ok(())
}

fn select_entity_request(
    value: &model::SelectEntityRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::SelectEntityRequest>(), depth)?;
    if let Some(member) = &value.namespace {
        inspect_namespace_request(member, depth + 1, budget)?;
    }
    if let Some(member) = &value.prefix {
        budget.data(member.len())?;
    }
    if let Some(member) = &value.page {
        page_request(member, depth + 1, budget)?;
    }
    Ok(())
}

fn mutate_state_request(
    value: &model::MutateStateRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(std::mem::size_of::<model::MutateStateRequest>(), depth)?;
    if let Some(member) = &value.namespace {
        inspect_namespace_request(member, depth + 1, budget)?;
    }
    {
        let member = &value.operation_id;
        budget.data(member.len())?;
    }
    if let Some(member) = &value.record_id {
        budget.data(member.len())?;
    }
    {
        let member = &value.expected_version;
        budget.data(member.len())?;
    }
    {
        let member = &value.expected_policy_digest;
        budget.data(member.len())?;
    }
    {
        let member = &value.reason;
        budget.data(member.len())?;
    }
    Ok(())
}

fn get_state_operation_receipt_request(
    value: &model::GetStateOperationReceiptRequest,
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    let _ = value;
    budget.node(
        std::mem::size_of::<model::GetStateOperationReceiptRequest>(),
        depth,
    )?;
    if let Some(member) = &value.namespace {
        inspect_namespace_request(member, depth + 1, budget)?;
    }
    {
        let member = &value.operation_id;
        budget.data(member.len())?;
    }
    Ok(())
}

pub(super) trait ModelShape {
    fn validate_shape(&self) -> Result<(), ValidationError>;
}

impl ModelShape for model::InvokeCommandRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        invoke_command_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::QueryRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        query_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::LookupCommandRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        lookup_command_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::LookupCommitRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        lookup_commit_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::GetEffectRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        get_effect_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::ListEffectHistoryRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        list_effect_history_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::CancelCommandRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        cancel_command_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::MutateNamespaceRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        mutate_namespace_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::InspectNamespaceRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        inspect_namespace_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::SelectEntityRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        select_entity_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::MutateStateRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        mutate_state_request(self, 0, &mut Budget::new())
    }
}
impl ModelShape for model::GetStateOperationReceiptRequest {
    fn validate_shape(&self) -> Result<(), ValidationError> {
        get_state_operation_receipt_request(self, 0, &mut Budget::new())
    }
}
