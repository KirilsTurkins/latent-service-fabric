#include "internal.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static bool bounded(latent_string value, size_t maximum) {
    return value.length <= maximum && (value.length == 0 || value.data != NULL);
}

static bool identifier(latent_string value) {
    if (!bounded(value, LSF_MAX_ID) || value.length == 0) return false;
    for (size_t index = 0; index < value.length; ++index) {
        if ((unsigned char)value.data[index] <= 0x20 || (unsigned char)value.data[index] == 0x7f) return false;
    }
    return true;
}

static bool record_kind(int32_t value) {
    return value == LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY
        || value == LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_PROVIDER_BINDING;
}

static bool page_request(const latent_profile_page_request *page, uint32_t maximum, size_t cursor) {
    return page->page_size <= maximum && (!page->has_page_token || bounded(page->page_token, cursor));
}

bool lsf_request_valid(latent_profile_call *call, const void *request) {
    latent_string tenant = call->owner->config.tenant;
    switch (call->operation) {
        case LSF_INVOKE: {
            const latent_profile_invoke_request *value = request;
            return value->has_target && value->has_budget && lsf_text_equal(value->target.tenant, tenant)
                && bounded(value->target.service, 256) && bounded(value->target.contract, 256)
                && bounded(value->target.function, 256) && (!value->target.has_route || bounded(value->target.route, 256))
                && bounded(value->media_type, 128) && (!value->has_idempotency_key || bounded(value->idempotency_key, 256))
                && (!value->has_root_activation_id || bounded(value->root_activation_id, 256))
                && (!value->has_parent_activation_id || bounded(value->parent_activation_id, 256));
        }
        case LSF_CANCEL: return bounded(((const latent_profile_cancel_request *)request)->reason, 1024);
        case LSF_GET_ACTIVATION: return true;
        case LSF_GET_POLICY: {
            const latent_profile_get_policy_request *value = request;
            if (!identifier(value->id) || !record_kind(value->record_kind)) return false;
            memcpy(call->policy_id, value->id.data, value->id.length);
            call->policy_id_length = value->id.length;
            call->record_kind = value->record_kind;
            return true;
        }
        case LSF_LIST_POLICIES: {
            const latent_profile_list_policies_request *value = request;
            call->page_size = value->page.page_size;
            call->record_kind = value->record_kind;
            return record_kind(value->record_kind) && value->has_page && value->page.page_size != 0
                && page_request(&value->page, 32, 117);
        }
        case LSF_LIST_CAPABILITIES: {
            const latent_profile_list_capabilities_request *value = request;
            call->page_size = !value->has_page || value->page.page_size == 0 ? 128 : value->page.page_size;
            return bounded(value->deployment_id, 256) && (!value->has_contract_prefix || bounded(value->contract_prefix, 256))
                && (!value->has_provider || bounded(value->provider, 256))
                && (!value->has_page || page_request(&value->page, 128, 160));
        }
        case LSF_APPLY_POLICY: {
            const latent_profile_apply_policy_request *value = request;
            const latent_profile_policy *policy = &value->policy;
            if (!value->has_policy || !value->has_expected_generation || !identifier(value->operation_id)
                || !identifier(policy->id) || !record_kind(policy->record_kind) || policy->generation != 0
                || policy->content_digest.length != 0 || policy->revoked || !policy->has_metadata
                || !lsf_text_equal(policy->metadata.name, policy->id) || !policy->metadata.has_tenant
                || !lsf_text_equal(policy->metadata.tenant, tenant) || policy->metadata.has_namespace
                || policy->metadata.labels_count != 0 || policy->metadata.annotations_count != 0
                || !bounded(policy->language, 128)) return false;
            memcpy(call->policy_id, policy->id.data, policy->id.length);
            call->policy_id_length = policy->id.length;
            call->record_kind = policy->record_kind;
            return true;
        }
        case LSF_GET_POLICY_OPERATION:
            return identifier(((const latent_profile_get_policy_operation_request *)request)->operation_id);
    }
    return false;
}

void lsf_unsupported(latent_profile_call *call, const char *field, latent_string value) {
    size_t length = value.length > 256 ? 256 : value.length;
    if (length != 0) memcpy(call->unsupported, value.data, length);
    call->failure.has_unsupported_wire_value = true;
    call->failure.unsupported_wire_value.field = (latent_string){field, strlen(field)};
    call->failure.unsupported_wire_value.value = (latent_string){call->unsupported, length};
}

static int platform_code(latent_string code) {
    static const struct { const char *code; int status; } codes[] = {
        {"unavailable", 14}, {"route-unavailable", 14}, {"deadline-exceeded", 4}, {"cancelled", 1},
        {"resource-exhausted", 8}, {"admission-rejected", 8}, {"permission-denied", 7}, {"unauthenticated", 16},
        {"invalid-argument", 3}, {"not-found", 5}, {"already-exists", 6}, {"incompatible-contract", 9},
        {"dependency-failed", 9}, {"state-conflict", 10}, {"corrupt-artifact", 15}, {"internal", 13}, {"guest-trap", 13}
    };
    for (size_t index = 0; index < sizeof(codes) / sizeof(codes[0]); ++index) {
        if (lsf_text_equal(code, (latent_string){codes[index].code, strlen(codes[index].code)})) return codes[index].status;
    }
    return -1;
}

static bool platform_valid(latent_profile_call *call, const latent_profile_platform_error *value) {
    if (platform_code(value->code) < 0) { lsf_unsupported(call, "platform_error.code", value->code); return false; }
    return bounded(value->message, 4096) && value->detail_items_count <= 16;
}

static bool digest(latent_string value, const char *prefix) {
    size_t length = strlen(prefix);
    if (value.length != length + 64 || value.data == NULL || memcmp(value.data, prefix, length) != 0) return false;
    for (size_t index = length; index < value.length; ++index) {
        char digit = value.data[index];
        if (!((digit >= '0' && digit <= '9') || (digit >= 'a' && digit <= 'f'))) return false;
    }
    return true;
}

static bool supported(latent_profile_call *call, const char *field, latent_string value,
                       const char *const *allowed, size_t count) {
    for (size_t index = 0; index < count; ++index) {
        if (lsf_text_equal(value, (latent_string){allowed[index], strlen(allowed[index])})) return true;
    }
    lsf_unsupported(call, field, value);
    return false;
}

static bool terminal_valid(latent_profile_call *call, latent_string value) {
    static const char *const terminals[] = {"completed", "rejected", "cancelled", "deadline_exceeded",
        "resource_exhausted", "guest_trap", "state_conflict", "dependency_failed", "platform_failed"};
    return supported(call, "activation.terminal_state", value, terminals, sizeof(terminals) / sizeof(terminals[0]));
}

static const char *terminal_for(latent_string code) {
    static const struct { const char *code; const char *terminal; } states[] = {
        {"deadline-exceeded", "deadline_exceeded"}, {"cancelled", "cancelled"},
        {"resource-exhausted", "resource_exhausted"}, {"guest-trap", "guest_trap"},
        {"state-conflict", "state_conflict"}, {"dependency-failed", "dependency_failed"},
        {"unavailable", "dependency_failed"}, {"route-unavailable", "dependency_failed"},
        {"admission-rejected", "rejected"}, {"permission-denied", "rejected"}, {"unauthenticated", "rejected"},
        {"invalid-argument", "rejected"}, {"not-found", "rejected"}, {"already-exists", "rejected"},
        {"incompatible-contract", "rejected"}, {"corrupt-artifact", "rejected"}
    };
    for (size_t index = 0; index < sizeof(states) / sizeof(states[0]); ++index) {
        if (lsf_text_equal(code, (latent_string){states[index].code, strlen(states[index].code)})) return states[index].terminal;
    }
    return "platform_failed";
}

static bool activation_identity(latent_profile_call *call, latent_string value) {
    if (!identifier(value)) return false;
    latent_profile_request_identity *identity = &call->metadata.identity;
    if (identity->has_activation_id && !lsf_text_equal(identity->activation_id, value)) return false;
    identity->has_activation_id = true;
    identity->activation_id = value;
    return true;
}

static bool page_response(const latent_profile_page_response *page, size_t maximum) {
    return !page->has_next_page_token || (page->next_page_token.length != 0 && bounded(page->next_page_token, maximum));
}

static bool receipt_valid(latent_profile_call *call, const latent_profile_capability_policy_operation *receipt) {
    return lsf_text_equal(receipt->operation_id, call->metadata.identity.operation_id)
        && lsf_text_equal(receipt->tenant, call->owner->config.tenant) && identifier(receipt->id)
        && bounded(receipt->content_digest, 256);
}

bool lsf_response_valid(latent_profile_call *call) {
    switch (call->operation) {
        case LSF_INVOKE: {
            const latent_profile_invoke_response *value = &call->result.invoke.value;
            if (!activation_identity(call, value->activation_id)) return false;
            if ((unsigned)value->has_success + (unsigned)value->has_declared_error + (unsigned)value->has_platform_failure != 1
                || !value->has_consumption || (value->has_publication_id && !digest(value->publication_id, "publication:sha256:"))) return false;
            bool unresolved = value->has_platform_failure && value->revision_id.length == 0 && value->release_digest.length == 0
                && value->route_generation == 0 && !value->has_publication_id;
            if (!unresolved && (!identifier(value->revision_id) || !digest(value->release_digest, "sha256:"))) return false;
            return !value->has_platform_failure || platform_valid(call, &value->platform_failure);
        }
        case LSF_CANCEL: {
            const latent_profile_cancel_response *value = &call->result.cancel.value;
            if (value->disposition < 1 || value->disposition > 3) {
                char text[32];
                int length = snprintf(text, sizeof(text), "%" PRId32, value->disposition);
                lsf_unsupported(call, "cancel.disposition", (latent_string){text, (size_t)length});
                return false;
            }
            return value->disposition == LATENT_PROFILE_CANCEL_DISPOSITION_ALREADY_TERMINAL
                ? value->has_terminal_state && terminal_valid(call, value->terminal_state) : !value->has_terminal_state;
        }
        case LSF_GET_ACTIVATION: {
            const latent_profile_activation_status *value = &call->result.get_activation.value;
            static const char *const phases[] = {"received", "resolved", "admitted", "queued", "materializing",
                "running", "suspended", "preparing_commit", "committed", "effects_pending"};
            if (!activation_identity(call, value->activation_id)
                || !supported(call, "activation.phase", value->phase, phases, sizeof(phases) / sizeof(phases[0]))) return false;
            unsigned outcomes = (unsigned)value->has_succeeded + (unsigned)value->has_declared_error + (unsigned)value->has_platform_failure;
            if (value->has_terminal_state != value->has_final_consumption || value->has_terminal_state != value->has_terminal_at_unix_millis
                || outcomes != (value->has_terminal_state ? 1u : 0u)) return false;
            if (!value->has_terminal_state) return true;
            if (!terminal_valid(call, value->terminal_state)) return false;
            if (value->has_succeeded || value->has_declared_error) return lsf_text_equal(value->terminal_state, LSF_TEXT("completed"));
            const char *expected = terminal_for(value->platform_failure.code);
            return platform_valid(call, &value->platform_failure)
                && lsf_text_equal(value->terminal_state, (latent_string){expected, strlen(expected)});
        }
        case LSF_GET_POLICY: {
            const latent_profile_get_policy_response *value = &call->result.get_policy.value;
            return !value->has_policy || (value->policy.record_kind == call->record_kind
                && lsf_text_equal(value->policy.id, (latent_string){call->policy_id, call->policy_id_length}));
        }
        case LSF_LIST_POLICIES: {
            const latent_profile_list_policies_response *value = &call->result.list_policies.value;
            if (value->policies_count > call->page_size || !value->has_page || !page_response(&value->page, 117)) return false;
            for (size_t index = 0; index < value->policies_count; ++index) {
                if (value->policies[index].record_kind != call->record_kind || !identifier(value->policies[index].id)) return false;
            }
            return true;
        }
        case LSF_LIST_CAPABILITIES: {
            const latent_profile_list_capabilities_response *value = &call->result.list_capabilities.value;
            return value->capabilities_count <= call->page_size && value->has_page && page_response(&value->page, 160)
                && (!value->has_revision || !value->revision.has_publication_id || digest(value->revision.publication_id, "publication:sha256:"));
        }
        case LSF_APPLY_POLICY: {
            const latent_profile_apply_policy_response *value = &call->result.apply_policy.value;
            const latent_profile_capability_policy_operation *receipt = &value->receipt;
            const latent_profile_policy *policy = &value->policy;
            return value->has_receipt && value->has_policy && receipt_valid(call, receipt)
                && lsf_text_equal(receipt->id, (latent_string){call->policy_id, call->policy_id_length})
                && receipt->record_kind == call->record_kind && receipt->record_kind == policy->record_kind
                && lsf_text_equal(receipt->id, policy->id) && receipt->generation == policy->generation
                && lsf_text_equal(receipt->content_digest, policy->content_digest) && receipt->revoked == policy->revoked;
        }
        case LSF_GET_POLICY_OPERATION: {
            const latent_profile_get_policy_operation_response *value = &call->result.get_policy_operation.value;
            return !value->has_receipt || receipt_valid(call, &value->receipt);
        }
    }
    return false;
}

static int base64_digit(unsigned char value) {
    if (value >= 'A' && value <= 'Z') return value - 'A';
    if (value >= 'a' && value <= 'z') return value - 'a' + 26;
    if (value >= '0' && value <= '9') return value - '0' + 52;
    if (value == '+') return 62;
    if (value == '/') return 63;
    return -1;
}

static bool platform_details(latent_profile_call *call, bool *limit) {
    if (call->platform_details_length == 0) return true;
    uint8_t decoded[8192];
    size_t length = call->platform_details_length;
    size_t padding = 0;
    while (length != 0 && call->platform_details[length - 1] == '=') { --length; ++padding; }
    if (padding > 2 || (padding != 0 && call->platform_details_length % 4 != 0) || length % 4 == 1) return false;
    uint32_t bits = 0;
    unsigned count = 0;
    size_t used = 0;
    for (size_t index = 0; index < length; ++index) {
        int digit = base64_digit((unsigned char)call->platform_details[index]);
        if (digit < 0) return false;
        bits = (bits << 6) | (unsigned)digit;
        count += 6;
        if (count >= 8) {
            count -= 8;
            if (used >= sizeof(decoded)) return false;
            decoded[used++] = (uint8_t)(bits >> count);
        }
    }
    if (count != 0 && (bits & ((1u << count) - 1u)) != 0) return false;
    if (!lsf_decode(&lsf_latent_control_v1_PlatformError, decoded, used, &call->failure.platform_error,
                    &call->arena, call->deadline, limit)) return false;
    call->failure.has_platform_error = true;
    return platform_valid(call, &call->failure.platform_error)
        && platform_code(call->failure.platform_error.code) == call->grpc_status;
}

static void metadata_result(latent_profile_call *call) {
    switch (call->operation) {
        case LSF_INVOKE: call->result.invoke.metadata = call->metadata; break;
        case LSF_CANCEL: call->result.cancel.metadata = call->metadata; break;
        case LSF_GET_ACTIVATION: call->result.get_activation.metadata = call->metadata; break;
        case LSF_GET_POLICY: call->result.get_policy.metadata = call->metadata; break;
        case LSF_LIST_POLICIES: call->result.list_policies.metadata = call->metadata; break;
        case LSF_LIST_CAPABILITIES: call->result.list_capabilities.metadata = call->metadata; break;
        case LSF_APPLY_POLICY: call->result.apply_policy.metadata = call->metadata; break;
        case LSF_GET_POLICY_OPERATION: call->result.get_policy_operation.metadata = call->metadata; break;
    }
}

void lsf_finish_response(latent_profile_call *call) {
    if (lsf_now() >= call->deadline) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE); return; }
    if (!call->status_ok || !call->content_type_ok || !call->has_grpc_status
        || (call->metadata.has_audit_ack && (call->metadata.audit_ack.status == LATENT_PROFILE_AUDIT_ACK_STATUS_DURABLE
             || call->metadata.audit_ack.status == LATENT_PROFILE_AUDIT_ACK_STATUS_OUTCOME_UNKNOWN)
             && (!call->metadata.has_audit_attempt_sequence || call->metadata.audit_attempt_sequence == 0))) {
        lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE); return;
    }
    if (call->grpc_status != 0) {
        bool limit = false;
        bool valid = platform_details(call, &limit);
        if (lsf_now() >= call->deadline) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE); return; }
        if (!valid) { lsf_fail(call, limit ? LATENT_PROFILE_FAILURE_CATEGORY_LIMIT : LATENT_PROFILE_FAILURE_CATEGORY_DECODE); return; }
        lsf_fail(call, call->grpc_status == 4 ? LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE : LATENT_PROFILE_FAILURE_CATEGORY_RPC);
        bool recovery = call->operation == LSF_GET_ACTIVATION || call->operation == LSF_GET_POLICY_OPERATION;
        bool observed = call->grpc_status == 3 || (call->grpc_status == 5 && !recovery) || call->grpc_status == 6
            || call->grpc_status == 7 || call->grpc_status == 9 || call->grpc_status == 10 || call->grpc_status == 12 || call->grpc_status == 16;
        if (observed && !lsf_text_equal(call->metadata.audit_status, LSF_TEXT("outcome-unknown"))
            && !lsf_text_equal(call->metadata.audit_status, LSF_TEXT("audit-unavailable")))
            call->failure.outcome = LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED;
        return;
    }
    if (call->response_length < 5) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE); return; }
    uint32_t length = 0;
    for (unsigned index = 1; index < 5; ++index) length = (length << 8) | call->response[index];
    if (length != call->response_length - 5) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE); return; }
    bool limit = false;
    bool decoded = lsf_decode(lsf_rpcs[call->operation].response, call->response + 5, length,
                              &call->result, &call->arena, call->deadline, &limit);
    if (call->operation == LSF_INVOKE && !call->metadata.identity.has_activation_id
        && identifier(call->result.invoke.value.activation_id)) {
        call->metadata.identity.has_activation_id = true;
        call->metadata.identity.activation_id = call->result.invoke.value.activation_id;
    }
    if (lsf_now() >= call->deadline) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE); return; }
    if (!decoded || !lsf_response_valid(call)) {
        lsf_fail(call, limit ? LATENT_PROFILE_FAILURE_CATEGORY_LIMIT : LATENT_PROFILE_FAILURE_CATEGORY_DECODE); return;
    }
    call->metadata.outcome = call->operation == LSF_GET_POLICY_OPERATION && !call->result.get_policy_operation.value.has_receipt
        ? LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN : LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED;
    metadata_result(call);
    lsf_complete(call);
}
