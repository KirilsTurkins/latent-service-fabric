#include "latent/profile.h"
#include <assert.h>
#include <string.h>

#define PROFILE_TEXT(value) ((latent_string){(value), sizeof(value) - 1u})

static void profile_vectors(void) {
    {
        latent_profile_invoke_request value = (latent_profile_invoke_request){.has_target = true, .target = (latent_profile_invocation_target){.tenant = PROFILE_TEXT("tenant-a"), .service = PROFILE_TEXT("echo"), .contract = PROFILE_TEXT("example:echo/api@1.0.0"), .function = PROFILE_TEXT("echo")}, .payload = (latent_bytes){.data = (const uint8_t[]){0, 1, 2, 255}, .length = 4}, .media_type = PROFILE_TEXT("application/octet-stream"), .priority = 0U, .has_budget = true, .budget = (latent_profile_resource_budget){.cpu_fuel = UINT64_C(18446744073709551615), .memory_bytes = UINT64_C(9223372036854775808), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(0), .effect_count = 0U}, .metadata = (const latent_key_value[]){{.key = PROFILE_TEXT("trace"), .value = PROFILE_TEXT("redacted")}}, .metadata_count = 1};
        assert((!(value.has_activation_id)) && "invoke-absent-identity-and-deadlines.activation_id.presence");
        assert((!(value.has_parent_activation_id)) && "invoke-absent-identity-and-deadlines.parent_activation_id.presence");
        assert((!(value.has_root_activation_id)) && "invoke-absent-identity-and-deadlines.root_activation_id.presence");
        assert((value.has_target) && "invoke-absent-identity-and-deadlines.target.presence");
        assert((value.target.tenant.length == 8) && "invoke-absent-identity-and-deadlines.target.tenant.length");
        assert((memcmp(value.target.tenant.data, "tenant-a", 8) == 0) && "invoke-absent-identity-and-deadlines.target.tenant");
        assert((value.target.service.length == 4) && "invoke-absent-identity-and-deadlines.target.service.length");
        assert((memcmp(value.target.service.data, "echo", 4) == 0) && "invoke-absent-identity-and-deadlines.target.service");
        assert((value.target.contract.length == 22) && "invoke-absent-identity-and-deadlines.target.contract.length");
        assert((memcmp(value.target.contract.data, "example:echo/api@1.0.0", 22) == 0) && "invoke-absent-identity-and-deadlines.target.contract");
        assert((value.target.function.length == 4) && "invoke-absent-identity-and-deadlines.target.function.length");
        assert((memcmp(value.target.function.data, "echo", 4) == 0) && "invoke-absent-identity-and-deadlines.target.function");
        assert((!(value.target.has_route)) && "invoke-absent-identity-and-deadlines.target.route.presence");
        assert((value.payload.length == 4) && "invoke-absent-identity-and-deadlines.payload.length");
        assert((value.payload.data[0] == 0) && "invoke-absent-identity-and-deadlines.payload.0");
        assert((value.payload.data[1] == 1) && "invoke-absent-identity-and-deadlines.payload.1");
        assert((value.payload.data[2] == 2) && "invoke-absent-identity-and-deadlines.payload.2");
        assert((value.payload.data[3] == 255) && "invoke-absent-identity-and-deadlines.payload.3");
        assert((value.media_type.length == 24) && "invoke-absent-identity-and-deadlines.media_type.length");
        assert((memcmp(value.media_type.data, "application/octet-stream", 24) == 0) && "invoke-absent-identity-and-deadlines.media_type");
        assert((!(value.has_deadline_unix_millis)) && "invoke-absent-identity-and-deadlines.deadline_unix_millis.presence");
        assert((value.priority == 0U) && "invoke-absent-identity-and-deadlines.priority");
        assert((!(value.has_idempotency_key)) && "invoke-absent-identity-and-deadlines.idempotency_key.presence");
        assert((value.has_budget) && "invoke-absent-identity-and-deadlines.budget.presence");
        assert((value.budget.cpu_fuel == UINT64_C(18446744073709551615)) && "invoke-absent-identity-and-deadlines.budget.cpu_fuel");
        assert((value.budget.memory_bytes == UINT64_C(9223372036854775808)) && "invoke-absent-identity-and-deadlines.budget.memory_bytes");
        assert((value.budget.child_calls == 0U) && "invoke-absent-identity-and-deadlines.budget.child_calls");
        assert((value.budget.outbound_requests == 0U) && "invoke-absent-identity-and-deadlines.budget.outbound_requests");
        assert((value.budget.state_read_bytes == UINT64_C(0)) && "invoke-absent-identity-and-deadlines.budget.state_read_bytes");
        assert((value.budget.state_write_bytes == UINT64_C(0)) && "invoke-absent-identity-and-deadlines.budget.state_write_bytes");
        assert((value.budget.blob_read_bytes == UINT64_C(0)) && "invoke-absent-identity-and-deadlines.budget.blob_read_bytes");
        assert((value.budget.blob_write_bytes == UINT64_C(0)) && "invoke-absent-identity-and-deadlines.budget.blob_write_bytes");
        assert((value.budget.log_bytes == UINT64_C(0)) && "invoke-absent-identity-and-deadlines.budget.log_bytes");
        assert((value.budget.effect_count == 0U) && "invoke-absent-identity-and-deadlines.budget.effect_count");
        assert((!(value.budget.has_wall_time_limit_millis)) && "invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence");
        assert((value.metadata_count == 1) && "invoke-absent-identity-and-deadlines.metadata.count");
        assert((value.metadata[0].key.length == 5) && "invoke-absent-identity-and-deadlines.metadata.key.length");
        assert((memcmp(value.metadata[0].key.data, "trace", 5) == 0) && "invoke-absent-identity-and-deadlines.metadata.key");
        assert((value.metadata[0].value.length == 8) && "invoke-absent-identity-and-deadlines.metadata.0.length");
        assert((memcmp(value.metadata[0].value.data, "redacted", 8) == 0) && "invoke-absent-identity-and-deadlines.metadata.0");
    }
    {
        latent_profile_invoke_request value = (latent_profile_invoke_request){.has_activation_id = true, .activation_id = PROFILE_TEXT(""), .has_parent_activation_id = true, .parent_activation_id = PROFILE_TEXT("parent-a"), .has_root_activation_id = true, .root_activation_id = PROFILE_TEXT(""), .has_target = true, .target = (latent_profile_invocation_target){.tenant = PROFILE_TEXT(""), .service = PROFILE_TEXT(""), .contract = PROFILE_TEXT(""), .function = PROFILE_TEXT(""), .has_route = true, .route = PROFILE_TEXT("")}, .payload = (latent_bytes){.data = NULL, .length = 0}, .media_type = PROFILE_TEXT(""), .has_deadline_unix_millis = true, .deadline_unix_millis = UINT64_C(0), .priority = 0U, .has_idempotency_key = true, .idempotency_key = PROFILE_TEXT(""), .has_budget = true, .budget = (latent_profile_resource_budget){.cpu_fuel = UINT64_C(0), .memory_bytes = UINT64_C(0), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(0), .effect_count = 0U, .has_wall_time_limit_millis = true, .wall_time_limit_millis = UINT64_C(0)}, .metadata = NULL, .metadata_count = 0};
        assert((value.has_activation_id) && "invoke-present-invalid-and-zero-not-absence.activation_id.presence");
        assert((value.activation_id.length == 0) && "invoke-present-invalid-and-zero-not-absence.activation_id.length");
        assert((value.has_parent_activation_id) && "invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence");
        assert((value.parent_activation_id.length == 8) && "invoke-present-invalid-and-zero-not-absence.parent_activation_id.length");
        assert((memcmp(value.parent_activation_id.data, "parent-a", 8) == 0) && "invoke-present-invalid-and-zero-not-absence.parent_activation_id");
        assert((value.has_root_activation_id) && "invoke-present-invalid-and-zero-not-absence.root_activation_id.presence");
        assert((value.root_activation_id.length == 0) && "invoke-present-invalid-and-zero-not-absence.root_activation_id.length");
        assert((value.has_target) && "invoke-present-invalid-and-zero-not-absence.target.presence");
        assert((value.target.tenant.length == 0) && "invoke-present-invalid-and-zero-not-absence.target.tenant.length");
        assert((value.target.service.length == 0) && "invoke-present-invalid-and-zero-not-absence.target.service.length");
        assert((value.target.contract.length == 0) && "invoke-present-invalid-and-zero-not-absence.target.contract.length");
        assert((value.target.function.length == 0) && "invoke-present-invalid-and-zero-not-absence.target.function.length");
        assert((value.target.has_route) && "invoke-present-invalid-and-zero-not-absence.target.route.presence");
        assert((value.target.route.length == 0) && "invoke-present-invalid-and-zero-not-absence.target.route.length");
        assert((value.payload.length == 0) && "invoke-present-invalid-and-zero-not-absence.payload.length");
        assert((value.media_type.length == 0) && "invoke-present-invalid-and-zero-not-absence.media_type.length");
        assert((value.has_deadline_unix_millis) && "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence");
        assert((value.deadline_unix_millis == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis");
        assert((value.priority == 0U) && "invoke-present-invalid-and-zero-not-absence.priority");
        assert((value.has_idempotency_key) && "invoke-present-invalid-and-zero-not-absence.idempotency_key.presence");
        assert((value.idempotency_key.length == 0) && "invoke-present-invalid-and-zero-not-absence.idempotency_key.length");
        assert((value.has_budget) && "invoke-present-invalid-and-zero-not-absence.budget.presence");
        assert((value.budget.cpu_fuel == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel");
        assert((value.budget.memory_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.memory_bytes");
        assert((value.budget.child_calls == 0U) && "invoke-present-invalid-and-zero-not-absence.budget.child_calls");
        assert((value.budget.outbound_requests == 0U) && "invoke-present-invalid-and-zero-not-absence.budget.outbound_requests");
        assert((value.budget.state_read_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes");
        assert((value.budget.state_write_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes");
        assert((value.budget.blob_read_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes");
        assert((value.budget.blob_write_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes");
        assert((value.budget.log_bytes == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.log_bytes");
        assert((value.budget.effect_count == 0U) && "invoke-present-invalid-and-zero-not-absence.budget.effect_count");
        assert((value.budget.has_wall_time_limit_millis) && "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence");
        assert((value.budget.wall_time_limit_millis == UINT64_C(0)) && "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis");
        assert((value.metadata_count == 0) && "invoke-present-invalid-and-zero-not-absence.metadata.count");
    }
    {
        latent_profile_invoke_request value = (latent_profile_invoke_request){.has_activation_id = true, .activation_id = PROFILE_TEXT("activation-a"), .has_parent_activation_id = true, .parent_activation_id = PROFILE_TEXT("parent-a"), .has_root_activation_id = true, .root_activation_id = PROFILE_TEXT("root-a"), .payload = (latent_bytes){.data = NULL, .length = 0}, .media_type = PROFILE_TEXT(""), .has_deadline_unix_millis = true, .deadline_unix_millis = UINT64_C(18446744073709551615), .priority = 4294967295U, .has_idempotency_key = true, .idempotency_key = PROFILE_TEXT("not-an-authority-or-retry-key"), .metadata = NULL, .metadata_count = 0};
        assert((value.has_activation_id) && "invoke-known-identity-full-width-deadline-and-priority.activation_id.presence");
        assert((value.activation_id.length == 12) && "invoke-known-identity-full-width-deadline-and-priority.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "invoke-known-identity-full-width-deadline-and-priority.activation_id");
        assert((value.has_parent_activation_id) && "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence");
        assert((value.parent_activation_id.length == 8) && "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.length");
        assert((memcmp(value.parent_activation_id.data, "parent-a", 8) == 0) && "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id");
        assert((value.has_root_activation_id) && "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence");
        assert((value.root_activation_id.length == 6) && "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.length");
        assert((memcmp(value.root_activation_id.data, "root-a", 6) == 0) && "invoke-known-identity-full-width-deadline-and-priority.root_activation_id");
        assert((!(value.has_target)) && "invoke-known-identity-full-width-deadline-and-priority.target.presence");
        assert((value.payload.length == 0) && "invoke-known-identity-full-width-deadline-and-priority.payload.length");
        assert((value.media_type.length == 0) && "invoke-known-identity-full-width-deadline-and-priority.media_type.length");
        assert((value.has_deadline_unix_millis) && "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence");
        assert((value.deadline_unix_millis == UINT64_C(18446744073709551615)) && "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis");
        assert((value.priority == 4294967295U) && "invoke-known-identity-full-width-deadline-and-priority.priority");
        assert((value.has_idempotency_key) && "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence");
        assert((value.idempotency_key.length == 29) && "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.length");
        assert((memcmp(value.idempotency_key.data, "not-an-authority-or-retry-key", 29) == 0) && "invoke-known-identity-full-width-deadline-and-priority.idempotency_key");
        assert((!(value.has_budget)) && "invoke-known-identity-full-width-deadline-and-priority.budget.presence");
        assert((value.metadata_count == 0) && "invoke-known-identity-full-width-deadline-and-priority.metadata.count");
    }
    {
        latent_profile_resource_budget value = (latent_profile_resource_budget){.cpu_fuel = UINT64_C(18446744073709551615), .memory_bytes = UINT64_C(18446744073709551615), .child_calls = 4294967295U, .outbound_requests = 4294967295U, .state_read_bytes = UINT64_C(18446744073709551615), .state_write_bytes = UINT64_C(18446744073709551615), .blob_read_bytes = UINT64_C(18446744073709551615), .blob_write_bytes = UINT64_C(18446744073709551615), .log_bytes = UINT64_C(18446744073709551615), .effect_count = 4294967295U, .has_wall_time_limit_millis = true, .wall_time_limit_millis = UINT64_C(18446744073709551615)};
        assert((value.cpu_fuel == UINT64_C(18446744073709551615)) && "full-resource-budget.cpu_fuel");
        assert((value.memory_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.memory_bytes");
        assert((value.child_calls == 4294967295U) && "full-resource-budget.child_calls");
        assert((value.outbound_requests == 4294967295U) && "full-resource-budget.outbound_requests");
        assert((value.state_read_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.state_read_bytes");
        assert((value.state_write_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.state_write_bytes");
        assert((value.blob_read_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.blob_read_bytes");
        assert((value.blob_write_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.blob_write_bytes");
        assert((value.log_bytes == UINT64_C(18446744073709551615)) && "full-resource-budget.log_bytes");
        assert((value.effect_count == 4294967295U) && "full-resource-budget.effect_count");
        assert((value.has_wall_time_limit_millis) && "full-resource-budget.wall_time_limit_millis.presence");
        assert((value.wall_time_limit_millis == UINT64_C(18446744073709551615)) && "full-resource-budget.wall_time_limit_millis");
    }
    {
        latent_profile_invoke_response value = (latent_profile_invoke_response){.activation_id = PROFILE_TEXT("activation-a"), .revision_id = PROFILE_TEXT("revision-a"), .release_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .route_generation = UINT64_C(18446744073709551615), .has_success = true, .success = (latent_profile_success){.payload = (latent_bytes){.data = (const uint8_t[]){0, 1, 2, 255}, .length = 4}, .media_type = PROFILE_TEXT("application/octet-stream"), .has_committed_state_version = true, .committed_state_version = PROFILE_TEXT(""), .effect_ids = (const latent_string[]){PROFILE_TEXT("effect-a"), PROFILE_TEXT("effect-b")}, .effect_ids_count = 2, .metadata = (const latent_key_value[]){{.key = PROFILE_TEXT("result"), .value = PROFILE_TEXT("redacted")}}, .metadata_count = 1}, .has_consumption = true, .consumption = (latent_profile_budget_consumption){.cpu_fuel = UINT64_C(18446744073709551615), .peak_memory_bytes = UINT64_C(0), .wall_time_micros = UINT64_C(9007199254740993), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(0), .effect_count = 0U}, .has_publication_id = true, .publication_id = PROFILE_TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111")};
        assert((value.activation_id.length == 12) && "invoke-success-retains-publication-and-component.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "invoke-success-retains-publication-and-component.activation_id");
        assert((value.revision_id.length == 10) && "invoke-success-retains-publication-and-component.revision_id.length");
        assert((memcmp(value.revision_id.data, "revision-a", 10) == 0) && "invoke-success-retains-publication-and-component.revision_id");
        assert((value.release_digest.length == 71) && "invoke-success-retains-publication-and-component.release_digest.length");
        assert((memcmp(value.release_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "invoke-success-retains-publication-and-component.release_digest");
        assert((value.route_generation == UINT64_C(18446744073709551615)) && "invoke-success-retains-publication-and-component.route_generation");
        assert((value.has_success) && "invoke-success-retains-publication-and-component.success.presence");
        assert((value.success.payload.length == 4) && "invoke-success-retains-publication-and-component.success.payload.length");
        assert((value.success.payload.data[0] == 0) && "invoke-success-retains-publication-and-component.success.payload.0");
        assert((value.success.payload.data[1] == 1) && "invoke-success-retains-publication-and-component.success.payload.1");
        assert((value.success.payload.data[2] == 2) && "invoke-success-retains-publication-and-component.success.payload.2");
        assert((value.success.payload.data[3] == 255) && "invoke-success-retains-publication-and-component.success.payload.3");
        assert((value.success.media_type.length == 24) && "invoke-success-retains-publication-and-component.success.media_type.length");
        assert((memcmp(value.success.media_type.data, "application/octet-stream", 24) == 0) && "invoke-success-retains-publication-and-component.success.media_type");
        assert((value.success.has_committed_state_version) && "invoke-success-retains-publication-and-component.success.committed_state_version.presence");
        assert((value.success.committed_state_version.length == 0) && "invoke-success-retains-publication-and-component.success.committed_state_version.length");
        assert((value.success.effect_ids_count == 2) && "invoke-success-retains-publication-and-component.success.effect_ids.count");
        assert((value.success.effect_ids[0].length == 8) && "invoke-success-retains-publication-and-component.success.effect_ids.0.length");
        assert((memcmp(value.success.effect_ids[0].data, "effect-a", 8) == 0) && "invoke-success-retains-publication-and-component.success.effect_ids.0");
        assert((value.success.effect_ids[1].length == 8) && "invoke-success-retains-publication-and-component.success.effect_ids.1.length");
        assert((memcmp(value.success.effect_ids[1].data, "effect-b", 8) == 0) && "invoke-success-retains-publication-and-component.success.effect_ids.1");
        assert((value.success.metadata_count == 1) && "invoke-success-retains-publication-and-component.success.metadata.count");
        assert((value.success.metadata[0].key.length == 6) && "invoke-success-retains-publication-and-component.success.metadata.key.length");
        assert((memcmp(value.success.metadata[0].key.data, "result", 6) == 0) && "invoke-success-retains-publication-and-component.success.metadata.key");
        assert((value.success.metadata[0].value.length == 8) && "invoke-success-retains-publication-and-component.success.metadata.0.length");
        assert((memcmp(value.success.metadata[0].value.data, "redacted", 8) == 0) && "invoke-success-retains-publication-and-component.success.metadata.0");
        assert((!(value.has_declared_error)) && "invoke-success-retains-publication-and-component.declared_error.presence");
        assert((!(value.has_platform_failure)) && "invoke-success-retains-publication-and-component.platform_failure.presence");
        assert((value.has_consumption) && "invoke-success-retains-publication-and-component.consumption.presence");
        assert((value.consumption.cpu_fuel == UINT64_C(18446744073709551615)) && "invoke-success-retains-publication-and-component.consumption.cpu_fuel");
        assert((value.consumption.peak_memory_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.peak_memory_bytes");
        assert((value.consumption.wall_time_micros == UINT64_C(9007199254740993)) && "invoke-success-retains-publication-and-component.consumption.wall_time_micros");
        assert((value.consumption.child_calls == 0U) && "invoke-success-retains-publication-and-component.consumption.child_calls");
        assert((value.consumption.outbound_requests == 0U) && "invoke-success-retains-publication-and-component.consumption.outbound_requests");
        assert((value.consumption.state_read_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.state_read_bytes");
        assert((value.consumption.state_write_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.state_write_bytes");
        assert((value.consumption.blob_read_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.blob_read_bytes");
        assert((value.consumption.blob_write_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.blob_write_bytes");
        assert((value.consumption.log_bytes == UINT64_C(0)) && "invoke-success-retains-publication-and-component.consumption.log_bytes");
        assert((value.consumption.effect_count == 0U) && "invoke-success-retains-publication-and-component.consumption.effect_count");
        assert((value.has_publication_id) && "invoke-success-retains-publication-and-component.publication_id.presence");
        assert((value.publication_id.length == 83) && "invoke-success-retains-publication-and-component.publication_id.length");
        assert((memcmp(value.publication_id.data, "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 83) == 0) && "invoke-success-retains-publication-and-component.publication_id");
    }
    {
        latent_profile_invoke_response value = (latent_profile_invoke_response){.activation_id = PROFILE_TEXT("activation-a"), .revision_id = PROFILE_TEXT("revision-a"), .release_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .route_generation = UINT64_C(9223372036854775808), .has_declared_error = true, .declared_error = (latent_profile_declared_error){.code = PROFILE_TEXT("uncertain"), .message = PROFILE_TEXT("provider outcome unknown"), .payload = (latent_bytes){.data = (const uint8_t[]){0, 1, 2, 255}, .length = 4}, .media_type = PROFILE_TEXT("application/octet-stream"), .metadata = (const latent_key_value[]){{.key = PROFILE_TEXT("contract"), .value = PROFILE_TEXT("latent:http/streaming@0.3.0")}}, .metadata_count = 1}, .has_consumption = true, .consumption = (latent_profile_budget_consumption){.cpu_fuel = UINT64_C(0), .peak_memory_bytes = UINT64_C(0), .wall_time_micros = UINT64_C(0), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(18446744073709551615), .log_bytes = UINT64_C(0), .effect_count = 0U}, .has_publication_id = true, .publication_id = PROFILE_TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111")};
        assert((value.activation_id.length == 12) && "typed-declared-provider-uncertainty-retains-receipt.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "typed-declared-provider-uncertainty-retains-receipt.activation_id");
        assert((value.revision_id.length == 10) && "typed-declared-provider-uncertainty-retains-receipt.revision_id.length");
        assert((memcmp(value.revision_id.data, "revision-a", 10) == 0) && "typed-declared-provider-uncertainty-retains-receipt.revision_id");
        assert((value.release_digest.length == 71) && "typed-declared-provider-uncertainty-retains-receipt.release_digest.length");
        assert((memcmp(value.release_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "typed-declared-provider-uncertainty-retains-receipt.release_digest");
        assert((value.route_generation == UINT64_C(9223372036854775808)) && "typed-declared-provider-uncertainty-retains-receipt.route_generation");
        assert((!(value.has_success)) && "typed-declared-provider-uncertainty-retains-receipt.success.presence");
        assert((value.has_declared_error) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.presence");
        assert((value.declared_error.code.length == 9) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.code.length");
        assert((memcmp(value.declared_error.code.data, "uncertain", 9) == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.code");
        assert((value.declared_error.message.length == 24) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.message.length");
        assert((memcmp(value.declared_error.message.data, "provider outcome unknown", 24) == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.message");
        assert((value.declared_error.payload.length == 4) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length");
        assert((value.declared_error.payload.data[0] == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0");
        assert((value.declared_error.payload.data[1] == 1) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1");
        assert((value.declared_error.payload.data[2] == 2) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2");
        assert((value.declared_error.payload.data[3] == 255) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3");
        assert((value.declared_error.media_type.length == 24) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type.length");
        assert((memcmp(value.declared_error.media_type.data, "application/octet-stream", 24) == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type");
        assert((value.declared_error.metadata_count == 1) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count");
        assert((value.declared_error.metadata[0].key.length == 8) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.key.length");
        assert((memcmp(value.declared_error.metadata[0].key.data, "contract", 8) == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.key");
        assert((value.declared_error.metadata[0].value.length == 27) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0.length");
        assert((memcmp(value.declared_error.metadata[0].value.data, "latent:http/streaming@0.3.0", 27) == 0) && "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0");
        assert((!(value.has_platform_failure)) && "typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence");
        assert((value.has_consumption) && "typed-declared-provider-uncertainty-retains-receipt.consumption.presence");
        assert((value.consumption.cpu_fuel == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel");
        assert((value.consumption.peak_memory_bytes == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes");
        assert((value.consumption.wall_time_micros == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros");
        assert((value.consumption.child_calls == 0U) && "typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls");
        assert((value.consumption.outbound_requests == 0U) && "typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests");
        assert((value.consumption.state_read_bytes == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes");
        assert((value.consumption.state_write_bytes == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes");
        assert((value.consumption.blob_read_bytes == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes");
        assert((value.consumption.blob_write_bytes == UINT64_C(18446744073709551615)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes");
        assert((value.consumption.log_bytes == UINT64_C(0)) && "typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes");
        assert((value.consumption.effect_count == 0U) && "typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count");
        assert((value.has_publication_id) && "typed-declared-provider-uncertainty-retains-receipt.publication_id.presence");
        assert((value.publication_id.length == 83) && "typed-declared-provider-uncertainty-retains-receipt.publication_id.length");
        assert((memcmp(value.publication_id.data, "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 83) == 0) && "typed-declared-provider-uncertainty-retains-receipt.publication_id");
    }
    {
        latent_profile_invoke_response value = (latent_profile_invoke_response){.activation_id = PROFILE_TEXT("activation-a"), .revision_id = PROFILE_TEXT(""), .release_digest = PROFILE_TEXT(""), .route_generation = UINT64_C(0), .has_platform_failure = true, .platform_failure = (latent_profile_platform_error){.code = PROFILE_TEXT("permission-denied"), .message = PROFILE_TEXT("capability-provider-failed"), .retryable = false, .detail_items = (const latent_profile_error_detail[]){(latent_profile_error_detail){.kind = PROFILE_TEXT("capability-observation"), .fields = (const latent_key_value[]){{.key = PROFILE_TEXT("capability"), .value = PROFILE_TEXT("latent:http/streaming@0.3.0")}, {.key = PROFILE_TEXT("state"), .value = PROFILE_TEXT("policy-revoked")}}, .fields_count = 2}, (latent_profile_error_detail){.kind = PROFILE_TEXT("future-detail"), .fields = (const latent_key_value[]){{.key = PROFILE_TEXT("bounded"), .value = PROFILE_TEXT("preserved")}}, .fields_count = 1}}, .detail_items_count = 2}, .has_consumption = true, .consumption = (latent_profile_budget_consumption){.cpu_fuel = UINT64_C(0), .peak_memory_bytes = UINT64_C(0), .wall_time_micros = UINT64_C(0), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(18446744073709551615), .effect_count = 0U}};
        assert((value.activation_id.length == 12) && "typed-platform-capability-failure-retains-detail-items.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "typed-platform-capability-failure-retains-detail-items.activation_id");
        assert((value.revision_id.length == 0) && "typed-platform-capability-failure-retains-detail-items.revision_id.length");
        assert((value.release_digest.length == 0) && "typed-platform-capability-failure-retains-detail-items.release_digest.length");
        assert((value.route_generation == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.route_generation");
        assert((!(value.has_success)) && "typed-platform-capability-failure-retains-detail-items.success.presence");
        assert((!(value.has_declared_error)) && "typed-platform-capability-failure-retains-detail-items.declared_error.presence");
        assert((value.has_platform_failure) && "typed-platform-capability-failure-retains-detail-items.platform_failure.presence");
        assert((value.platform_failure.code.length == 17) && "typed-platform-capability-failure-retains-detail-items.platform_failure.code.length");
        assert((memcmp(value.platform_failure.code.data, "permission-denied", 17) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.code");
        assert((value.platform_failure.message.length == 26) && "typed-platform-capability-failure-retains-detail-items.platform_failure.message.length");
        assert((memcmp(value.platform_failure.message.data, "capability-provider-failed", 26) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.message");
        assert((value.platform_failure.retryable == false) && "typed-platform-capability-failure-retains-detail-items.platform_failure.retryable");
        assert((value.platform_failure.detail_items_count == 2) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count");
        assert((value.platform_failure.detail_items[0].kind.length == 22) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind.length");
        assert((memcmp(value.platform_failure.detail_items[0].kind.data, "capability-observation", 22) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind");
        assert((value.platform_failure.detail_items[0].fields_count == 2) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count");
        assert((value.platform_failure.detail_items[0].fields[0].key.length == 10) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.key.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[0].key.data, "capability", 10) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.key");
        assert((value.platform_failure.detail_items[0].fields[0].value.length == 27) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[0].value.data, "latent:http/streaming@0.3.0", 27) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0");
        assert((value.platform_failure.detail_items[0].fields[1].key.length == 5) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.key.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[1].key.data, "state", 5) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.key");
        assert((value.platform_failure.detail_items[0].fields[1].value.length == 14) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[1].value.data, "policy-revoked", 14) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1");
        assert((value.platform_failure.detail_items[1].kind.length == 13) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind.length");
        assert((memcmp(value.platform_failure.detail_items[1].kind.data, "future-detail", 13) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind");
        assert((value.platform_failure.detail_items[1].fields_count == 1) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count");
        assert((value.platform_failure.detail_items[1].fields[0].key.length == 7) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.key.length");
        assert((memcmp(value.platform_failure.detail_items[1].fields[0].key.data, "bounded", 7) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.key");
        assert((value.platform_failure.detail_items[1].fields[0].value.length == 9) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0.length");
        assert((memcmp(value.platform_failure.detail_items[1].fields[0].value.data, "preserved", 9) == 0) && "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0");
        assert((value.has_consumption) && "typed-platform-capability-failure-retains-detail-items.consumption.presence");
        assert((value.consumption.cpu_fuel == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel");
        assert((value.consumption.peak_memory_bytes == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes");
        assert((value.consumption.wall_time_micros == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros");
        assert((value.consumption.child_calls == 0U) && "typed-platform-capability-failure-retains-detail-items.consumption.child_calls");
        assert((value.consumption.outbound_requests == 0U) && "typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests");
        assert((value.consumption.state_read_bytes == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes");
        assert((value.consumption.state_write_bytes == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes");
        assert((value.consumption.blob_read_bytes == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes");
        assert((value.consumption.blob_write_bytes == UINT64_C(0)) && "typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes");
        assert((value.consumption.log_bytes == UINT64_C(18446744073709551615)) && "typed-platform-capability-failure-retains-detail-items.consumption.log_bytes");
        assert((value.consumption.effect_count == 0U) && "typed-platform-capability-failure-retains-detail-items.consumption.effect_count");
        assert((!(value.has_publication_id)) && "typed-platform-capability-failure-retains-detail-items.publication_id.presence");
    }
    {
        latent_profile_invoke_response value = (latent_profile_invoke_response){.activation_id = PROFILE_TEXT("activation-a"), .revision_id = PROFILE_TEXT(""), .release_digest = PROFILE_TEXT(""), .route_generation = UINT64_C(0), .has_success = true, .success = (latent_profile_success){.payload = (latent_bytes){.data = NULL, .length = 0}, .media_type = PROFILE_TEXT(""), .effect_ids = NULL, .effect_ids_count = 0, .metadata = NULL, .metadata_count = 0}, .has_publication_id = true, .publication_id = PROFILE_TEXT("")};
        assert((value.activation_id.length == 12) && "present-invalid-publication-not-legacy.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "present-invalid-publication-not-legacy.activation_id");
        assert((value.revision_id.length == 0) && "present-invalid-publication-not-legacy.revision_id.length");
        assert((value.release_digest.length == 0) && "present-invalid-publication-not-legacy.release_digest.length");
        assert((value.route_generation == UINT64_C(0)) && "present-invalid-publication-not-legacy.route_generation");
        assert((value.has_success) && "present-invalid-publication-not-legacy.success.presence");
        assert((value.success.payload.length == 0) && "present-invalid-publication-not-legacy.success.payload.length");
        assert((value.success.media_type.length == 0) && "present-invalid-publication-not-legacy.success.media_type.length");
        assert((!(value.success.has_committed_state_version)) && "present-invalid-publication-not-legacy.success.committed_state_version.presence");
        assert((value.success.effect_ids_count == 0) && "present-invalid-publication-not-legacy.success.effect_ids.count");
        assert((value.success.metadata_count == 0) && "present-invalid-publication-not-legacy.success.metadata.count");
        assert((!(value.has_declared_error)) && "present-invalid-publication-not-legacy.declared_error.presence");
        assert((!(value.has_platform_failure)) && "present-invalid-publication-not-legacy.platform_failure.presence");
        assert((!(value.has_consumption)) && "present-invalid-publication-not-legacy.consumption.presence");
        assert((value.has_publication_id) && "present-invalid-publication-not-legacy.publication_id.presence");
        assert((value.publication_id.length == 0) && "present-invalid-publication-not-legacy.publication_id.length");
    }
    {
        latent_profile_invoke_response value = (latent_profile_invoke_response){.activation_id = PROFILE_TEXT("activation-a"), .revision_id = PROFILE_TEXT(""), .release_digest = PROFILE_TEXT(""), .route_generation = UINT64_C(0), .has_success = true, .success = (latent_profile_success){.payload = (latent_bytes){.data = NULL, .length = 0}, .media_type = PROFILE_TEXT(""), .effect_ids = NULL, .effect_ids_count = 0, .metadata = NULL, .metadata_count = 0}, .has_platform_failure = true, .platform_failure = (latent_profile_platform_error){.code = PROFILE_TEXT("internal"), .message = PROFILE_TEXT(""), .retryable = false, .detail_items = NULL, .detail_items_count = 0}};
        assert((value.activation_id.length == 12) && "contradictory-outcome-retained-for-rejection.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "contradictory-outcome-retained-for-rejection.activation_id");
        assert((value.revision_id.length == 0) && "contradictory-outcome-retained-for-rejection.revision_id.length");
        assert((value.release_digest.length == 0) && "contradictory-outcome-retained-for-rejection.release_digest.length");
        assert((value.route_generation == UINT64_C(0)) && "contradictory-outcome-retained-for-rejection.route_generation");
        assert((value.has_success) && "contradictory-outcome-retained-for-rejection.success.presence");
        assert((value.success.payload.length == 0) && "contradictory-outcome-retained-for-rejection.success.payload.length");
        assert((value.success.media_type.length == 0) && "contradictory-outcome-retained-for-rejection.success.media_type.length");
        assert((!(value.success.has_committed_state_version)) && "contradictory-outcome-retained-for-rejection.success.committed_state_version.presence");
        assert((value.success.effect_ids_count == 0) && "contradictory-outcome-retained-for-rejection.success.effect_ids.count");
        assert((value.success.metadata_count == 0) && "contradictory-outcome-retained-for-rejection.success.metadata.count");
        assert((!(value.has_declared_error)) && "contradictory-outcome-retained-for-rejection.declared_error.presence");
        assert((value.has_platform_failure) && "contradictory-outcome-retained-for-rejection.platform_failure.presence");
        assert((value.platform_failure.code.length == 8) && "contradictory-outcome-retained-for-rejection.platform_failure.code.length");
        assert((memcmp(value.platform_failure.code.data, "internal", 8) == 0) && "contradictory-outcome-retained-for-rejection.platform_failure.code");
        assert((value.platform_failure.message.length == 0) && "contradictory-outcome-retained-for-rejection.platform_failure.message.length");
        assert((value.platform_failure.retryable == false) && "contradictory-outcome-retained-for-rejection.platform_failure.retryable");
        assert((value.platform_failure.detail_items_count == 0) && "contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count");
        assert((!(value.has_consumption)) && "contradictory-outcome-retained-for-rejection.consumption.presence");
        assert((!(value.has_publication_id)) && "contradictory-outcome-retained-for-rejection.publication_id.presence");
    }
    {
        latent_profile_cancel_request value = (latent_profile_cancel_request){.activation_id = PROFILE_TEXT("activation-a"), .reason = PROFILE_TEXT("caller-requested")};
        assert((value.activation_id.length == 12) && "cancel-request-known-id.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "cancel-request-known-id.activation_id");
        assert((value.reason.length == 16) && "cancel-request-known-id.reason.length");
        assert((memcmp(value.reason.data, "caller-requested", 16) == 0) && "cancel-request-known-id.reason");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(1))};
        assert((value.disposition == 1) && "cancel-accepted-not-cleanup.disposition");
        assert((!(value.has_terminal_state)) && "cancel-accepted-not-cleanup.terminal_state.presence");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(2)), .has_terminal_state = true, .terminal_state = PROFILE_TEXT("completed")};
        assert((value.disposition == 2) && "cancel-already-terminal.disposition");
        assert((value.has_terminal_state) && "cancel-already-terminal.terminal_state.presence");
        assert((value.terminal_state.length == 9) && "cancel-already-terminal.terminal_state.length");
        assert((memcmp(value.terminal_state.data, "completed", 9) == 0) && "cancel-already-terminal.terminal_state");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(3))};
        assert((value.disposition == 3) && "cancel-not-found-not-nonexecution.disposition");
        assert((!(value.has_terminal_state)) && "cancel-not-found-not-nonexecution.terminal_state.presence");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(0)), .has_terminal_state = true, .terminal_state = PROFILE_TEXT("")};
        assert((value.disposition == 0) && "cancel-unspecified-not-accepted.disposition");
        assert((value.has_terminal_state) && "cancel-unspecified-not-accepted.terminal_state.presence");
        assert((value.terminal_state.length == 0) && "cancel-unspecified-not-accepted.terminal_state.length");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(91)), .has_terminal_state = true, .terminal_state = PROFILE_TEXT("future-terminal-state")};
        assert((value.disposition == 91) && "cancel-unknown-enum.disposition");
        assert((value.has_terminal_state) && "cancel-unknown-enum.terminal_state.presence");
        assert((value.terminal_state.length == 21) && "cancel-unknown-enum.terminal_state.length");
        assert((memcmp(value.terminal_state.data, "future-terminal-state", 21) == 0) && "cancel-unknown-enum.terminal_state");
    }
    {
        latent_profile_cancel_response value = (latent_profile_cancel_response){.disposition = ((latent_profile_cancel_disposition)(-2147483648))};
        assert((value.disposition == -2147483648) && "cancel-negative-enum.disposition");
        assert((!(value.has_terminal_state)) && "cancel-negative-enum.terminal_state.presence");
    }
    {
        latent_profile_get_activation_request value = (latent_profile_get_activation_request){.activation_id = PROFILE_TEXT("activation-a")};
        assert((value.activation_id.length == 12) && "get-activation-recovery.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "get-activation-recovery.activation_id");
    }
    {
        latent_profile_activation_status value = (latent_profile_activation_status){.activation_id = PROFILE_TEXT("activation-a"), .phase = PROFILE_TEXT("running"), .last_updated_unix_millis = UINT64_C(18446744073709551615), .metadata = NULL, .metadata_count = 0};
        assert((value.activation_id.length == 12) && "activation-running-absent-terminal.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "activation-running-absent-terminal.activation_id");
        assert((value.phase.length == 7) && "activation-running-absent-terminal.phase.length");
        assert((memcmp(value.phase.data, "running", 7) == 0) && "activation-running-absent-terminal.phase");
        assert((!(value.has_terminal_state)) && "activation-running-absent-terminal.terminal_state.presence");
        assert((value.last_updated_unix_millis == UINT64_C(18446744073709551615)) && "activation-running-absent-terminal.last_updated_unix_millis");
        assert((value.metadata_count == 0) && "activation-running-absent-terminal.metadata.count");
        assert((!(value.has_succeeded)) && "activation-running-absent-terminal.succeeded.presence");
        assert((!(value.has_declared_error)) && "activation-running-absent-terminal.declared_error.presence");
        assert((!(value.has_platform_failure)) && "activation-running-absent-terminal.platform_failure.presence");
        assert((!(value.has_final_consumption)) && "activation-running-absent-terminal.final_consumption.presence");
        assert((!(value.has_terminal_at_unix_millis)) && "activation-running-absent-terminal.terminal_at_unix_millis.presence");
    }
    {
        latent_profile_activation_status value = (latent_profile_activation_status){.activation_id = PROFILE_TEXT("activation-a"), .phase = PROFILE_TEXT("terminal"), .has_terminal_state = true, .terminal_state = PROFILE_TEXT("failed"), .last_updated_unix_millis = UINT64_C(0), .metadata = NULL, .metadata_count = 0, .has_platform_failure = true, .platform_failure = (latent_profile_platform_error){.code = PROFILE_TEXT("resource-exhausted"), .message = PROFILE_TEXT("capability-capacity"), .retryable = false, .detail_items = (const latent_profile_error_detail[]){(latent_profile_error_detail){.kind = PROFILE_TEXT("budget"), .fields = (const latent_key_value[]){{.key = PROFILE_TEXT("resource"), .value = PROFILE_TEXT("buffer-bytes")}}, .fields_count = 1}}, .detail_items_count = 1}, .has_final_consumption = true, .final_consumption = (latent_profile_budget_consumption){.cpu_fuel = UINT64_C(0), .peak_memory_bytes = UINT64_C(18446744073709551615), .wall_time_micros = UINT64_C(0), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(0), .effect_count = 0U}, .has_terminal_at_unix_millis = true, .terminal_at_unix_millis = UINT64_C(0)};
        assert((value.activation_id.length == 12) && "activation-terminal-typed-failure.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "activation-terminal-typed-failure.activation_id");
        assert((value.phase.length == 8) && "activation-terminal-typed-failure.phase.length");
        assert((memcmp(value.phase.data, "terminal", 8) == 0) && "activation-terminal-typed-failure.phase");
        assert((value.has_terminal_state) && "activation-terminal-typed-failure.terminal_state.presence");
        assert((value.terminal_state.length == 6) && "activation-terminal-typed-failure.terminal_state.length");
        assert((memcmp(value.terminal_state.data, "failed", 6) == 0) && "activation-terminal-typed-failure.terminal_state");
        assert((value.last_updated_unix_millis == UINT64_C(0)) && "activation-terminal-typed-failure.last_updated_unix_millis");
        assert((value.metadata_count == 0) && "activation-terminal-typed-failure.metadata.count");
        assert((!(value.has_succeeded)) && "activation-terminal-typed-failure.succeeded.presence");
        assert((!(value.has_declared_error)) && "activation-terminal-typed-failure.declared_error.presence");
        assert((value.has_platform_failure) && "activation-terminal-typed-failure.platform_failure.presence");
        assert((value.platform_failure.code.length == 18) && "activation-terminal-typed-failure.platform_failure.code.length");
        assert((memcmp(value.platform_failure.code.data, "resource-exhausted", 18) == 0) && "activation-terminal-typed-failure.platform_failure.code");
        assert((value.platform_failure.message.length == 19) && "activation-terminal-typed-failure.platform_failure.message.length");
        assert((memcmp(value.platform_failure.message.data, "capability-capacity", 19) == 0) && "activation-terminal-typed-failure.platform_failure.message");
        assert((value.platform_failure.retryable == false) && "activation-terminal-typed-failure.platform_failure.retryable");
        assert((value.platform_failure.detail_items_count == 1) && "activation-terminal-typed-failure.platform_failure.detail_items.count");
        assert((value.platform_failure.detail_items[0].kind.length == 6) && "activation-terminal-typed-failure.platform_failure.detail_items.0.kind.length");
        assert((memcmp(value.platform_failure.detail_items[0].kind.data, "budget", 6) == 0) && "activation-terminal-typed-failure.platform_failure.detail_items.0.kind");
        assert((value.platform_failure.detail_items[0].fields_count == 1) && "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count");
        assert((value.platform_failure.detail_items[0].fields[0].key.length == 8) && "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.key.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[0].key.data, "resource", 8) == 0) && "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.key");
        assert((value.platform_failure.detail_items[0].fields[0].value.length == 12) && "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0.length");
        assert((memcmp(value.platform_failure.detail_items[0].fields[0].value.data, "buffer-bytes", 12) == 0) && "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0");
        assert((value.has_final_consumption) && "activation-terminal-typed-failure.final_consumption.presence");
        assert((value.final_consumption.cpu_fuel == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.cpu_fuel");
        assert((value.final_consumption.peak_memory_bytes == UINT64_C(18446744073709551615)) && "activation-terminal-typed-failure.final_consumption.peak_memory_bytes");
        assert((value.final_consumption.wall_time_micros == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.wall_time_micros");
        assert((value.final_consumption.child_calls == 0U) && "activation-terminal-typed-failure.final_consumption.child_calls");
        assert((value.final_consumption.outbound_requests == 0U) && "activation-terminal-typed-failure.final_consumption.outbound_requests");
        assert((value.final_consumption.state_read_bytes == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.state_read_bytes");
        assert((value.final_consumption.state_write_bytes == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.state_write_bytes");
        assert((value.final_consumption.blob_read_bytes == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.blob_read_bytes");
        assert((value.final_consumption.blob_write_bytes == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.blob_write_bytes");
        assert((value.final_consumption.log_bytes == UINT64_C(0)) && "activation-terminal-typed-failure.final_consumption.log_bytes");
        assert((value.final_consumption.effect_count == 0U) && "activation-terminal-typed-failure.final_consumption.effect_count");
        assert((value.has_terminal_at_unix_millis) && "activation-terminal-typed-failure.terminal_at_unix_millis.presence");
        assert((value.terminal_at_unix_millis == UINT64_C(0)) && "activation-terminal-typed-failure.terminal_at_unix_millis");
    }
    {
        latent_profile_activation_status value = (latent_profile_activation_status){.activation_id = PROFILE_TEXT("activation-a"), .phase = PROFILE_TEXT("terminal"), .has_terminal_state = true, .terminal_state = PROFILE_TEXT("completed"), .last_updated_unix_millis = UINT64_C(0), .metadata = NULL, .metadata_count = 0, .has_succeeded = true, .succeeded = (latent_profile_activation_success_summary){.has_committed_state_version = true, .committed_state_version = PROFILE_TEXT("state-a"), .effect_ids = (const latent_string[]){PROFILE_TEXT("effect-a")}, .effect_ids_count = 1, .metadata = (const latent_key_value[]){{.key = PROFILE_TEXT("retained"), .value = PROFILE_TEXT("true")}}, .metadata_count = 1}, .has_final_consumption = true, .final_consumption = (latent_profile_budget_consumption){.cpu_fuel = UINT64_C(0), .peak_memory_bytes = UINT64_C(0), .wall_time_micros = UINT64_C(0), .child_calls = 0U, .outbound_requests = 0U, .state_read_bytes = UINT64_C(0), .state_write_bytes = UINT64_C(0), .blob_read_bytes = UINT64_C(0), .blob_write_bytes = UINT64_C(0), .log_bytes = UINT64_C(0), .effect_count = 4294967295U}, .has_terminal_at_unix_millis = true, .terminal_at_unix_millis = UINT64_C(18446744073709551615)};
        assert((value.activation_id.length == 12) && "activation-terminal-success-summary.activation_id.length");
        assert((memcmp(value.activation_id.data, "activation-a", 12) == 0) && "activation-terminal-success-summary.activation_id");
        assert((value.phase.length == 8) && "activation-terminal-success-summary.phase.length");
        assert((memcmp(value.phase.data, "terminal", 8) == 0) && "activation-terminal-success-summary.phase");
        assert((value.has_terminal_state) && "activation-terminal-success-summary.terminal_state.presence");
        assert((value.terminal_state.length == 9) && "activation-terminal-success-summary.terminal_state.length");
        assert((memcmp(value.terminal_state.data, "completed", 9) == 0) && "activation-terminal-success-summary.terminal_state");
        assert((value.last_updated_unix_millis == UINT64_C(0)) && "activation-terminal-success-summary.last_updated_unix_millis");
        assert((value.metadata_count == 0) && "activation-terminal-success-summary.metadata.count");
        assert((value.has_succeeded) && "activation-terminal-success-summary.succeeded.presence");
        assert((value.succeeded.has_committed_state_version) && "activation-terminal-success-summary.succeeded.committed_state_version.presence");
        assert((value.succeeded.committed_state_version.length == 7) && "activation-terminal-success-summary.succeeded.committed_state_version.length");
        assert((memcmp(value.succeeded.committed_state_version.data, "state-a", 7) == 0) && "activation-terminal-success-summary.succeeded.committed_state_version");
        assert((value.succeeded.effect_ids_count == 1) && "activation-terminal-success-summary.succeeded.effect_ids.count");
        assert((value.succeeded.effect_ids[0].length == 8) && "activation-terminal-success-summary.succeeded.effect_ids.0.length");
        assert((memcmp(value.succeeded.effect_ids[0].data, "effect-a", 8) == 0) && "activation-terminal-success-summary.succeeded.effect_ids.0");
        assert((value.succeeded.metadata_count == 1) && "activation-terminal-success-summary.succeeded.metadata.count");
        assert((value.succeeded.metadata[0].key.length == 8) && "activation-terminal-success-summary.succeeded.metadata.key.length");
        assert((memcmp(value.succeeded.metadata[0].key.data, "retained", 8) == 0) && "activation-terminal-success-summary.succeeded.metadata.key");
        assert((value.succeeded.metadata[0].value.length == 4) && "activation-terminal-success-summary.succeeded.metadata.0.length");
        assert((memcmp(value.succeeded.metadata[0].value.data, "true", 4) == 0) && "activation-terminal-success-summary.succeeded.metadata.0");
        assert((!(value.has_declared_error)) && "activation-terminal-success-summary.declared_error.presence");
        assert((!(value.has_platform_failure)) && "activation-terminal-success-summary.platform_failure.presence");
        assert((value.has_final_consumption) && "activation-terminal-success-summary.final_consumption.presence");
        assert((value.final_consumption.cpu_fuel == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.cpu_fuel");
        assert((value.final_consumption.peak_memory_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.peak_memory_bytes");
        assert((value.final_consumption.wall_time_micros == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.wall_time_micros");
        assert((value.final_consumption.child_calls == 0U) && "activation-terminal-success-summary.final_consumption.child_calls");
        assert((value.final_consumption.outbound_requests == 0U) && "activation-terminal-success-summary.final_consumption.outbound_requests");
        assert((value.final_consumption.state_read_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.state_read_bytes");
        assert((value.final_consumption.state_write_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.state_write_bytes");
        assert((value.final_consumption.blob_read_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.blob_read_bytes");
        assert((value.final_consumption.blob_write_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.blob_write_bytes");
        assert((value.final_consumption.log_bytes == UINT64_C(0)) && "activation-terminal-success-summary.final_consumption.log_bytes");
        assert((value.final_consumption.effect_count == 4294967295U) && "activation-terminal-success-summary.final_consumption.effect_count");
        assert((value.has_terminal_at_unix_millis) && "activation-terminal-success-summary.terminal_at_unix_millis.presence");
        assert((value.terminal_at_unix_millis == UINT64_C(18446744073709551615)) && "activation-terminal-success-summary.terminal_at_unix_millis");
    }
    {
        latent_profile_get_policy_response value = (latent_profile_get_policy_response){0};
        assert((!(value.has_policy)) && "policy-absence.policy.presence");
    }
    {
        latent_profile_get_policy_request value = (latent_profile_get_policy_request){.id = PROFILE_TEXT("policy-a"), .record_kind = ((latent_profile_capability_policy_record_kind)(1))};
        assert((value.id.length == 8) && "policy-record-kind.id.length");
        assert((memcmp(value.id.data, "policy-a", 8) == 0) && "policy-record-kind.id");
        assert((value.record_kind == 1) && "policy-record-kind.record_kind");
    }
    {
        latent_profile_get_policy_request value = (latent_profile_get_policy_request){.id = PROFILE_TEXT("binding-a"), .record_kind = ((latent_profile_capability_policy_record_kind)(2))};
        assert((value.id.length == 9) && "provider-binding-record-kind.id.length");
        assert((memcmp(value.id.data, "binding-a", 9) == 0) && "provider-binding-record-kind.id");
        assert((value.record_kind == 2) && "provider-binding-record-kind.record_kind");
    }
    {
        latent_profile_policy value = (latent_profile_policy){.id = PROFILE_TEXT("future-record"), .has_metadata = true, .metadata = (latent_profile_object_metadata){.name = PROFILE_TEXT("future-record"), .has_tenant = true, .tenant = PROFILE_TEXT(""), .has_namespace = true, .namespace = PROFILE_TEXT(""), .labels = (const latent_key_value[]){{.key = PROFILE_TEXT("sampled"), .value = PROFILE_TEXT("true")}}, .labels_count = 1, .annotations = (const latent_key_value[]){{.key = PROFILE_TEXT("descriptive"), .value = PROFILE_TEXT("not-authority")}}, .annotations_count = 1}, .document = PROFILE_TEXT(""), .generation = UINT64_C(18446744073709551615), .language = PROFILE_TEXT(""), .record_kind = ((latent_profile_capability_policy_record_kind)(2147483647)), .content_digest = PROFILE_TEXT(""), .revoked = true};
        assert((value.id.length == 13) && "unknown-policy-kind.id.length");
        assert((memcmp(value.id.data, "future-record", 13) == 0) && "unknown-policy-kind.id");
        assert((value.has_metadata) && "unknown-policy-kind.metadata.presence");
        assert((value.metadata.name.length == 13) && "unknown-policy-kind.metadata.name.length");
        assert((memcmp(value.metadata.name.data, "future-record", 13) == 0) && "unknown-policy-kind.metadata.name");
        assert((value.metadata.has_tenant) && "unknown-policy-kind.metadata.tenant.presence");
        assert((value.metadata.tenant.length == 0) && "unknown-policy-kind.metadata.tenant.length");
        assert((value.metadata.has_namespace) && "unknown-policy-kind.metadata.namespace.presence");
        assert((value.metadata.namespace.length == 0) && "unknown-policy-kind.metadata.namespace.length");
        assert((value.metadata.labels_count == 1) && "unknown-policy-kind.metadata.labels.count");
        assert((value.metadata.labels[0].key.length == 7) && "unknown-policy-kind.metadata.labels.key.length");
        assert((memcmp(value.metadata.labels[0].key.data, "sampled", 7) == 0) && "unknown-policy-kind.metadata.labels.key");
        assert((value.metadata.labels[0].value.length == 4) && "unknown-policy-kind.metadata.labels.0.length");
        assert((memcmp(value.metadata.labels[0].value.data, "true", 4) == 0) && "unknown-policy-kind.metadata.labels.0");
        assert((value.metadata.annotations_count == 1) && "unknown-policy-kind.metadata.annotations.count");
        assert((value.metadata.annotations[0].key.length == 11) && "unknown-policy-kind.metadata.annotations.key.length");
        assert((memcmp(value.metadata.annotations[0].key.data, "descriptive", 11) == 0) && "unknown-policy-kind.metadata.annotations.key");
        assert((value.metadata.annotations[0].value.length == 13) && "unknown-policy-kind.metadata.annotations.0.length");
        assert((memcmp(value.metadata.annotations[0].value.data, "not-authority", 13) == 0) && "unknown-policy-kind.metadata.annotations.0");
        assert((value.document.length == 0) && "unknown-policy-kind.document.length");
        assert((value.generation == UINT64_C(18446744073709551615)) && "unknown-policy-kind.generation");
        assert((value.language.length == 0) && "unknown-policy-kind.language.length");
        assert((value.record_kind == 2147483647) && "unknown-policy-kind.record_kind");
        assert((value.content_digest.length == 0) && "unknown-policy-kind.content_digest.length");
        assert((value.revoked == true) && "unknown-policy-kind.revoked");
    }
    {
        latent_profile_apply_policy_request value = (latent_profile_apply_policy_request){.operation_id = PROFILE_TEXT("operation-a")};
        assert((!(value.has_policy)) && "apply-missing-generation.policy.presence");
        assert((!(value.has_expected_generation)) && "apply-missing-generation.expected_generation.presence");
        assert((value.operation_id.length == 11) && "apply-missing-generation.operation_id.length");
        assert((memcmp(value.operation_id.data, "operation-a", 11) == 0) && "apply-missing-generation.operation_id");
    }
    {
        latent_profile_apply_policy_request value = (latent_profile_apply_policy_request){.has_expected_generation = true, .expected_generation = UINT64_C(0), .operation_id = PROFILE_TEXT("")};
        assert((!(value.has_policy)) && "apply-present-empty-operation.policy.presence");
        assert((value.has_expected_generation) && "apply-present-empty-operation.expected_generation.presence");
        assert((value.expected_generation == UINT64_C(0)) && "apply-present-empty-operation.expected_generation");
        assert((value.operation_id.length == 0) && "apply-present-empty-operation.operation_id.length");
    }
    {
        latent_profile_apply_policy_request value = (latent_profile_apply_policy_request){.has_policy = true, .policy = (latent_profile_policy){.id = PROFILE_TEXT("policy-a"), .has_metadata = true, .metadata = (latent_profile_object_metadata){.name = PROFILE_TEXT("policy-a"), .has_tenant = true, .tenant = PROFILE_TEXT("tenant-a"), .labels = NULL, .labels_count = 0, .annotations = NULL, .annotations_count = 0}, .document = PROFILE_TEXT("{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}"), .generation = UINT64_C(0), .language = PROFILE_TEXT("lsf-capability-policy-v1"), .record_kind = ((latent_profile_capability_policy_record_kind)(1)), .content_digest = PROFILE_TEXT(""), .revoked = false}, .has_expected_generation = true, .expected_generation = UINT64_C(0), .operation_id = PROFILE_TEXT("operation-a")};
        assert((value.has_policy) && "apply-create-policy-zero-generation.policy.presence");
        assert((value.policy.id.length == 8) && "apply-create-policy-zero-generation.policy.id.length");
        assert((memcmp(value.policy.id.data, "policy-a", 8) == 0) && "apply-create-policy-zero-generation.policy.id");
        assert((value.policy.has_metadata) && "apply-create-policy-zero-generation.policy.metadata.presence");
        assert((value.policy.metadata.name.length == 8) && "apply-create-policy-zero-generation.policy.metadata.name.length");
        assert((memcmp(value.policy.metadata.name.data, "policy-a", 8) == 0) && "apply-create-policy-zero-generation.policy.metadata.name");
        assert((value.policy.metadata.has_tenant) && "apply-create-policy-zero-generation.policy.metadata.tenant.presence");
        assert((value.policy.metadata.tenant.length == 8) && "apply-create-policy-zero-generation.policy.metadata.tenant.length");
        assert((memcmp(value.policy.metadata.tenant.data, "tenant-a", 8) == 0) && "apply-create-policy-zero-generation.policy.metadata.tenant");
        assert((!(value.policy.metadata.has_namespace)) && "apply-create-policy-zero-generation.policy.metadata.namespace.presence");
        assert((value.policy.metadata.labels_count == 0) && "apply-create-policy-zero-generation.policy.metadata.labels.count");
        assert((value.policy.metadata.annotations_count == 0) && "apply-create-policy-zero-generation.policy.metadata.annotations.count");
        assert((value.policy.document.length == 465) && "apply-create-policy-zero-generation.policy.document.length");
        assert((memcmp(value.policy.document.data, "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", 465) == 0) && "apply-create-policy-zero-generation.policy.document");
        assert((value.policy.generation == UINT64_C(0)) && "apply-create-policy-zero-generation.policy.generation");
        assert((value.policy.language.length == 24) && "apply-create-policy-zero-generation.policy.language.length");
        assert((memcmp(value.policy.language.data, "lsf-capability-policy-v1", 24) == 0) && "apply-create-policy-zero-generation.policy.language");
        assert((value.policy.record_kind == 1) && "apply-create-policy-zero-generation.policy.record_kind");
        assert((value.policy.content_digest.length == 0) && "apply-create-policy-zero-generation.policy.content_digest.length");
        assert((value.policy.revoked == false) && "apply-create-policy-zero-generation.policy.revoked");
        assert((value.has_expected_generation) && "apply-create-policy-zero-generation.expected_generation.presence");
        assert((value.expected_generation == UINT64_C(0)) && "apply-create-policy-zero-generation.expected_generation");
        assert((value.operation_id.length == 11) && "apply-create-policy-zero-generation.operation_id.length");
        assert((memcmp(value.operation_id.data, "operation-a", 11) == 0) && "apply-create-policy-zero-generation.operation_id");
    }
    {
        latent_profile_apply_policy_request value = (latent_profile_apply_policy_request){.has_policy = true, .policy = (latent_profile_policy){.id = PROFILE_TEXT("binding-a"), .has_metadata = true, .metadata = (latent_profile_object_metadata){.name = PROFILE_TEXT("binding-a"), .has_tenant = true, .tenant = PROFILE_TEXT("tenant-a"), .labels = NULL, .labels_count = 0, .annotations = NULL, .annotations_count = 0}, .document = PROFILE_TEXT("{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}"), .generation = UINT64_C(0), .language = PROFILE_TEXT("lsf-provider-binding-v1"), .record_kind = ((latent_profile_capability_policy_record_kind)(2)), .content_digest = PROFILE_TEXT(""), .revoked = false}, .has_expected_generation = true, .expected_generation = UINT64_C(18446744073709551615), .operation_id = PROFILE_TEXT("operation-binding")};
        assert((value.has_policy) && "apply-binding-max-precondition-and-opaque-limit-document.policy.presence");
        assert((value.policy.id.length == 9) && "apply-binding-max-precondition-and-opaque-limit-document.policy.id.length");
        assert((memcmp(value.policy.id.data, "binding-a", 9) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.id");
        assert((value.policy.has_metadata) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence");
        assert((value.policy.metadata.name.length == 9) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name.length");
        assert((memcmp(value.policy.metadata.name.data, "binding-a", 9) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name");
        assert((value.policy.metadata.has_tenant) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence");
        assert((value.policy.metadata.tenant.length == 8) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.length");
        assert((memcmp(value.policy.metadata.tenant.data, "tenant-a", 8) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant");
        assert((!(value.policy.metadata.has_namespace)) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence");
        assert((value.policy.metadata.labels_count == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count");
        assert((value.policy.metadata.annotations_count == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count");
        assert((value.policy.document.length == 385) && "apply-binding-max-precondition-and-opaque-limit-document.policy.document.length");
        assert((memcmp(value.policy.document.data, "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", 385) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.document");
        assert((value.policy.generation == UINT64_C(0)) && "apply-binding-max-precondition-and-opaque-limit-document.policy.generation");
        assert((value.policy.language.length == 23) && "apply-binding-max-precondition-and-opaque-limit-document.policy.language.length");
        assert((memcmp(value.policy.language.data, "lsf-provider-binding-v1", 23) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.language");
        assert((value.policy.record_kind == 2) && "apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind");
        assert((value.policy.content_digest.length == 0) && "apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest.length");
        assert((value.policy.revoked == false) && "apply-binding-max-precondition-and-opaque-limit-document.policy.revoked");
        assert((value.has_expected_generation) && "apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence");
        assert((value.expected_generation == UINT64_C(18446744073709551615)) && "apply-binding-max-precondition-and-opaque-limit-document.expected_generation");
        assert((value.operation_id.length == 17) && "apply-binding-max-precondition-and-opaque-limit-document.operation_id.length");
        assert((memcmp(value.operation_id.data, "operation-binding", 17) == 0) && "apply-binding-max-precondition-and-opaque-limit-document.operation_id");
    }
    {
        latent_profile_list_policies_request value = (latent_profile_list_policies_request){.record_kind = ((latent_profile_capability_policy_record_kind)(1))};
        assert((value.record_kind == 1) && "policy-page-absent.record_kind");
        assert((!(value.has_page)) && "policy-page-absent.page.presence");
    }
    {
        latent_profile_list_policies_request value = (latent_profile_list_policies_request){.record_kind = ((latent_profile_capability_policy_record_kind)(2)), .has_page = true, .page = (latent_profile_page_request){.page_size = 0U}};
        assert((value.record_kind == 2) && "policy-page-zero-invalid.record_kind");
        assert((value.has_page) && "policy-page-zero-invalid.page.presence");
        assert((value.page.page_size == 0U) && "policy-page-zero-invalid.page.page_size");
        assert((!(value.page.has_page_token)) && "policy-page-zero-invalid.page.page_token.presence");
    }
    {
        latent_profile_list_policies_request value = (latent_profile_list_policies_request){.record_kind = ((latent_profile_capability_policy_record_kind)(1)), .has_page = true, .page = (latent_profile_page_request){.page_size = 1U, .has_page_token = true, .page_token = PROFILE_TEXT("")}};
        assert((value.record_kind == 1) && "policy-page-empty-token-invalid.record_kind");
        assert((value.has_page) && "policy-page-empty-token-invalid.page.presence");
        assert((value.page.page_size == 1U) && "policy-page-empty-token-invalid.page.page_size");
        assert((value.page.has_page_token) && "policy-page-empty-token-invalid.page.page_token.presence");
        assert((value.page.page_token.length == 0) && "policy-page-empty-token-invalid.page.page_token.length");
    }
    {
        latent_profile_list_policies_response value = (latent_profile_list_policies_response){.policies = (const latent_profile_policy[]){(latent_profile_policy){.id = PROFILE_TEXT("policy-a"), .document = PROFILE_TEXT(""), .generation = UINT64_C(18446744073709551615), .language = PROFILE_TEXT(""), .record_kind = ((latent_profile_capability_policy_record_kind)(1)), .content_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .revoked = true}}, .policies_count = 1, .catalog_generation = UINT64_C(18446744073709551615), .has_page = true, .page = (latent_profile_page_response){.has_next_page_token = true, .next_page_token = PROFILE_TEXT("opaque-policy-cursor")}};
        assert((value.policies_count == 1) && "policy-page-first.policies.count");
        assert((value.policies[0].id.length == 8) && "policy-page-first.policies.0.id.length");
        assert((memcmp(value.policies[0].id.data, "policy-a", 8) == 0) && "policy-page-first.policies.0.id");
        assert((!(value.policies[0].has_metadata)) && "policy-page-first.policies.0.metadata.presence");
        assert((value.policies[0].document.length == 0) && "policy-page-first.policies.0.document.length");
        assert((value.policies[0].generation == UINT64_C(18446744073709551615)) && "policy-page-first.policies.0.generation");
        assert((value.policies[0].language.length == 0) && "policy-page-first.policies.0.language.length");
        assert((value.policies[0].record_kind == 1) && "policy-page-first.policies.0.record_kind");
        assert((value.policies[0].content_digest.length == 71) && "policy-page-first.policies.0.content_digest.length");
        assert((memcmp(value.policies[0].content_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "policy-page-first.policies.0.content_digest");
        assert((value.policies[0].revoked == true) && "policy-page-first.policies.0.revoked");
        assert((value.catalog_generation == UINT64_C(18446744073709551615)) && "policy-page-first.catalog_generation");
        assert((value.has_page) && "policy-page-first.page.presence");
        assert((value.page.has_next_page_token) && "policy-page-first.page.next_page_token.presence");
        assert((value.page.next_page_token.length == 20) && "policy-page-first.page.next_page_token.length");
        assert((memcmp(value.page.next_page_token.data, "opaque-policy-cursor", 20) == 0) && "policy-page-first.page.next_page_token");
    }
    {
        latent_profile_list_policies_response value = (latent_profile_list_policies_response){.policies = NULL, .policies_count = 0, .catalog_generation = UINT64_C(18446744073709551615), .has_page = true, .page = (latent_profile_page_response){0}};
        assert((value.policies_count == 0) && "policy-page-last.policies.count");
        assert((value.catalog_generation == UINT64_C(18446744073709551615)) && "policy-page-last.catalog_generation");
        assert((value.has_page) && "policy-page-last.page.presence");
        assert((!(value.page.has_next_page_token)) && "policy-page-last.page.next_page_token.presence");
    }
    {
        latent_profile_list_policies_request value = (latent_profile_list_policies_request){.record_kind = ((latent_profile_capability_policy_record_kind)(1)), .has_page = true, .page = (latent_profile_page_request){.page_size = 1U, .has_page_token = true, .page_token = PROFILE_TEXT("opaque-policy-cursor")}};
        assert((value.record_kind == 1) && "policy-next-page-request.record_kind");
        assert((value.has_page) && "policy-next-page-request.page.presence");
        assert((value.page.page_size == 1U) && "policy-next-page-request.page.page_size");
        assert((value.page.has_page_token) && "policy-next-page-request.page.page_token.presence");
        assert((value.page.page_token.length == 20) && "policy-next-page-request.page.page_token.length");
        assert((memcmp(value.page.page_token.data, "opaque-policy-cursor", 20) == 0) && "policy-next-page-request.page.page_token");
    }
    {
        latent_profile_apply_policy_response value = (latent_profile_apply_policy_response){.has_policy = true, .policy = (latent_profile_policy){.id = PROFILE_TEXT("policy-a"), .document = PROFILE_TEXT(""), .generation = UINT64_C(18446744073709551615), .language = PROFILE_TEXT(""), .record_kind = ((latent_profile_capability_policy_record_kind)(1)), .content_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .revoked = false}, .has_receipt = true, .receipt = (latent_profile_capability_policy_operation){.operation_id = PROFILE_TEXT("operation-a"), .tenant = PROFILE_TEXT("tenant-a"), .id = PROFILE_TEXT("policy-a"), .record_kind = ((latent_profile_capability_policy_record_kind)(1)), .generation = UINT64_C(18446744073709551615), .content_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .revoked = false}};
        assert((value.has_policy) && "apply-retains-original-receipt.policy.presence");
        assert((value.policy.id.length == 8) && "apply-retains-original-receipt.policy.id.length");
        assert((memcmp(value.policy.id.data, "policy-a", 8) == 0) && "apply-retains-original-receipt.policy.id");
        assert((!(value.policy.has_metadata)) && "apply-retains-original-receipt.policy.metadata.presence");
        assert((value.policy.document.length == 0) && "apply-retains-original-receipt.policy.document.length");
        assert((value.policy.generation == UINT64_C(18446744073709551615)) && "apply-retains-original-receipt.policy.generation");
        assert((value.policy.language.length == 0) && "apply-retains-original-receipt.policy.language.length");
        assert((value.policy.record_kind == 1) && "apply-retains-original-receipt.policy.record_kind");
        assert((value.policy.content_digest.length == 71) && "apply-retains-original-receipt.policy.content_digest.length");
        assert((memcmp(value.policy.content_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "apply-retains-original-receipt.policy.content_digest");
        assert((value.policy.revoked == false) && "apply-retains-original-receipt.policy.revoked");
        assert((value.has_receipt) && "apply-retains-original-receipt.receipt.presence");
        assert((value.receipt.operation_id.length == 11) && "apply-retains-original-receipt.receipt.operation_id.length");
        assert((memcmp(value.receipt.operation_id.data, "operation-a", 11) == 0) && "apply-retains-original-receipt.receipt.operation_id");
        assert((value.receipt.tenant.length == 8) && "apply-retains-original-receipt.receipt.tenant.length");
        assert((memcmp(value.receipt.tenant.data, "tenant-a", 8) == 0) && "apply-retains-original-receipt.receipt.tenant");
        assert((value.receipt.id.length == 8) && "apply-retains-original-receipt.receipt.id.length");
        assert((memcmp(value.receipt.id.data, "policy-a", 8) == 0) && "apply-retains-original-receipt.receipt.id");
        assert((value.receipt.record_kind == 1) && "apply-retains-original-receipt.receipt.record_kind");
        assert((value.receipt.generation == UINT64_C(18446744073709551615)) && "apply-retains-original-receipt.receipt.generation");
        assert((value.receipt.content_digest.length == 71) && "apply-retains-original-receipt.receipt.content_digest.length");
        assert((memcmp(value.receipt.content_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "apply-retains-original-receipt.receipt.content_digest");
        assert((value.receipt.revoked == false) && "apply-retains-original-receipt.receipt.revoked");
    }
    {
        latent_profile_get_policy_operation_request value = (latent_profile_get_policy_operation_request){.operation_id = PROFILE_TEXT("operation-a")};
        assert((value.operation_id.length == 11) && "get-policy-operation-known-id.operation_id.length");
        assert((memcmp(value.operation_id.data, "operation-a", 11) == 0) && "get-policy-operation-known-id.operation_id");
    }
    {
        latent_profile_get_policy_operation_response value = (latent_profile_get_policy_operation_response){0};
        assert((!(value.has_receipt)) && "operation-recovery-not-retained-is-unknown.receipt.presence");
    }
    {
        latent_profile_get_policy_operation_response value = (latent_profile_get_policy_operation_response){.has_receipt = true, .receipt = (latent_profile_capability_policy_operation){.operation_id = PROFILE_TEXT("operation-a"), .tenant = PROFILE_TEXT("tenant-a"), .id = PROFILE_TEXT("policy-a"), .record_kind = ((latent_profile_capability_policy_record_kind)(1)), .generation = UINT64_C(18446744073709551615), .content_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .revoked = false}};
        assert((value.has_receipt) && "operation-recovery-original-receipt.receipt.presence");
        assert((value.receipt.operation_id.length == 11) && "operation-recovery-original-receipt.receipt.operation_id.length");
        assert((memcmp(value.receipt.operation_id.data, "operation-a", 11) == 0) && "operation-recovery-original-receipt.receipt.operation_id");
        assert((value.receipt.tenant.length == 8) && "operation-recovery-original-receipt.receipt.tenant.length");
        assert((memcmp(value.receipt.tenant.data, "tenant-a", 8) == 0) && "operation-recovery-original-receipt.receipt.tenant");
        assert((value.receipt.id.length == 8) && "operation-recovery-original-receipt.receipt.id.length");
        assert((memcmp(value.receipt.id.data, "policy-a", 8) == 0) && "operation-recovery-original-receipt.receipt.id");
        assert((value.receipt.record_kind == 1) && "operation-recovery-original-receipt.receipt.record_kind");
        assert((value.receipt.generation == UINT64_C(18446744073709551615)) && "operation-recovery-original-receipt.receipt.generation");
        assert((value.receipt.content_digest.length == 71) && "operation-recovery-original-receipt.receipt.content_digest.length");
        assert((memcmp(value.receipt.content_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "operation-recovery-original-receipt.receipt.content_digest");
        assert((value.receipt.revoked == false) && "operation-recovery-original-receipt.receipt.revoked");
    }
    {
        latent_profile_list_capabilities_request value = (latent_profile_list_capabilities_request){.deployment_id = PROFILE_TEXT("deployment-a"), .include_node_usage = false};
        assert((!(value.has_contract_prefix)) && "capabilities-absent-page-default.contract_prefix.presence");
        assert((!(value.has_provider)) && "capabilities-absent-page-default.provider.presence");
        assert((!(value.has_page)) && "capabilities-absent-page-default.page.presence");
        assert((value.deployment_id.length == 12) && "capabilities-absent-page-default.deployment_id.length");
        assert((memcmp(value.deployment_id.data, "deployment-a", 12) == 0) && "capabilities-absent-page-default.deployment_id");
        assert((value.include_node_usage == false) && "capabilities-absent-page-default.include_node_usage");
    }
    {
        latent_profile_list_capabilities_request value = (latent_profile_list_capabilities_request){.has_page = true, .page = (latent_profile_page_request){.page_size = 0U}, .deployment_id = PROFILE_TEXT("deployment-a"), .include_node_usage = false};
        assert((!(value.has_contract_prefix)) && "capabilities-zero-page-default.contract_prefix.presence");
        assert((!(value.has_provider)) && "capabilities-zero-page-default.provider.presence");
        assert((value.has_page) && "capabilities-zero-page-default.page.presence");
        assert((value.page.page_size == 0U) && "capabilities-zero-page-default.page.page_size");
        assert((!(value.page.has_page_token)) && "capabilities-zero-page-default.page.page_token.presence");
        assert((value.deployment_id.length == 12) && "capabilities-zero-page-default.deployment_id.length");
        assert((memcmp(value.deployment_id.data, "deployment-a", 12) == 0) && "capabilities-zero-page-default.deployment_id");
        assert((value.include_node_usage == false) && "capabilities-zero-page-default.include_node_usage");
    }
    {
        latent_profile_list_capabilities_request value = (latent_profile_list_capabilities_request){.has_contract_prefix = true, .contract_prefix = PROFILE_TEXT(""), .has_provider = true, .provider = PROFILE_TEXT(""), .has_page = true, .page = (latent_profile_page_request){.page_size = 128U}, .deployment_id = PROFILE_TEXT("deployment-a"), .include_node_usage = true};
        assert((value.has_contract_prefix) && "capabilities-present-empty-filters.contract_prefix.presence");
        assert((value.contract_prefix.length == 0) && "capabilities-present-empty-filters.contract_prefix.length");
        assert((value.has_provider) && "capabilities-present-empty-filters.provider.presence");
        assert((value.provider.length == 0) && "capabilities-present-empty-filters.provider.length");
        assert((value.has_page) && "capabilities-present-empty-filters.page.presence");
        assert((value.page.page_size == 128U) && "capabilities-present-empty-filters.page.page_size");
        assert((!(value.page.has_page_token)) && "capabilities-present-empty-filters.page.page_token.presence");
        assert((value.deployment_id.length == 12) && "capabilities-present-empty-filters.deployment_id.length");
        assert((memcmp(value.deployment_id.data, "deployment-a", 12) == 0) && "capabilities-present-empty-filters.deployment_id");
        assert((value.include_node_usage == true) && "capabilities-present-empty-filters.include_node_usage");
    }
    {
        latent_profile_list_capabilities_request value = (latent_profile_list_capabilities_request){.has_page = true, .page = (latent_profile_page_request){.page_size = 1U}, .deployment_id = PROFILE_TEXT(""), .include_node_usage = false};
        assert((!(value.has_contract_prefix)) && "capabilities-explicit-deployment-required.contract_prefix.presence");
        assert((!(value.has_provider)) && "capabilities-explicit-deployment-required.provider.presence");
        assert((value.has_page) && "capabilities-explicit-deployment-required.page.presence");
        assert((value.page.page_size == 1U) && "capabilities-explicit-deployment-required.page.page_size");
        assert((!(value.page.has_page_token)) && "capabilities-explicit-deployment-required.page.page_token.presence");
        assert((value.deployment_id.length == 0) && "capabilities-explicit-deployment-required.deployment_id.length");
        assert((value.include_node_usage == false) && "capabilities-explicit-deployment-required.include_node_usage");
    }
    {
        latent_profile_list_capabilities_request value = (latent_profile_list_capabilities_request){.has_page = true, .page = (latent_profile_page_request){.page_size = 4294967295U}, .deployment_id = PROFILE_TEXT("deployment-a"), .include_node_usage = false};
        assert((!(value.has_contract_prefix)) && "capabilities-page-too-large.contract_prefix.presence");
        assert((!(value.has_provider)) && "capabilities-page-too-large.provider.presence");
        assert((value.has_page) && "capabilities-page-too-large.page.presence");
        assert((value.page.page_size == 4294967295U) && "capabilities-page-too-large.page.page_size");
        assert((!(value.page.has_page_token)) && "capabilities-page-too-large.page.page_token.presence");
        assert((value.deployment_id.length == 12) && "capabilities-page-too-large.deployment_id.length");
        assert((memcmp(value.deployment_id.data, "deployment-a", 12) == 0) && "capabilities-page-too-large.deployment_id");
        assert((value.include_node_usage == false) && "capabilities-page-too-large.include_node_usage");
    }
    {
        latent_profile_list_capabilities_response value = (latent_profile_list_capabilities_response){.capabilities = (const latent_profile_capability_descriptor[]){(latent_profile_capability_descriptor){.id = PROFILE_TEXT("latent:secrets/reader@0.1.0"), .contract = PROFILE_TEXT("latent:secrets/reader@0.1.0"), .provider = PROFILE_TEXT("local-secrets-v1"), .operations = (const latent_string[]){PROFILE_TEXT("read")}, .operations_count = 1, .attributes = NULL, .attributes_count = 0, .has_inspection = true, .inspection = (latent_profile_capability_binding_inspection){.has_definition_digest = true, .definition_digest = PROFILE_TEXT(""), .has_provider_binding = true, .provider_binding = (latent_profile_capability_inspection_policy){.id = PROFILE_TEXT("binding-a"), .revision = UINT64_C(18446744073709551615), .digest = PROFILE_TEXT("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")}, .policies = (const latent_profile_capability_inspection_policy[]){(latent_profile_capability_inspection_policy){.id = PROFILE_TEXT("policy-a"), .revision = UINT64_C(9223372036854775808), .digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")}}, .policies_count = 1, .provider_profile = PROFILE_TEXT("local-secrets-v1"), .provider_configuration_digest = PROFILE_TEXT("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), .provider_configuration_epoch = UINT64_C(18446744073709551615), .state = PROFILE_TEXT("provider-configuration-changed")}}, (latent_profile_capability_descriptor){.id = PROFILE_TEXT("future-capability"), .contract = PROFILE_TEXT("future-contract"), .provider = PROFILE_TEXT("future-provider"), .operations = NULL, .operations_count = 0, .attributes = (const latent_key_value[]){{.key = PROFILE_TEXT("descriptive"), .value = PROFILE_TEXT("not-authority")}}, .attributes_count = 1}}, .capabilities_count = 2, .has_page = true, .page = (latent_profile_page_response){.has_next_page_token = true, .next_page_token = PROFILE_TEXT("opaque-capability-cursor")}, .has_revision = true, .revision = (latent_profile_capability_inspection_revision){.deployment_id = PROFILE_TEXT("deployment-a"), .revision_id = PROFILE_TEXT("revision-a"), .component_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .has_publication_id = true, .publication_id = PROFILE_TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), .route_generation = UINT64_C(18446744073709551615), .catalog_transaction = UINT64_C(9223372036854775808)}, .has_tenant_usage = true, .tenant_usage = (latent_profile_capability_resource_usage){.scope = PROFILE_TEXT("tenant"), .counters = (const latent_profile_counter[]){{.key = PROFILE_TEXT("sessions"), .value = UINT64_C(18446744073709551615)}, {.key = PROFILE_TEXT("calls"), .value = UINT64_C(0)}}, .counters_count = 2, .unavailable = (const latent_string[]){PROFILE_TEXT("fixture-owner-unavailable")}, .unavailable_count = 1}, .state = PROFILE_TEXT("sampled")};
        assert((value.capabilities_count == 2) && "redacted-capability-provider-inspection.capabilities.count");
        assert((value.capabilities[0].id.length == 27) && "redacted-capability-provider-inspection.capabilities.0.id.length");
        assert((memcmp(value.capabilities[0].id.data, "latent:secrets/reader@0.1.0", 27) == 0) && "redacted-capability-provider-inspection.capabilities.0.id");
        assert((value.capabilities[0].contract.length == 27) && "redacted-capability-provider-inspection.capabilities.0.contract.length");
        assert((memcmp(value.capabilities[0].contract.data, "latent:secrets/reader@0.1.0", 27) == 0) && "redacted-capability-provider-inspection.capabilities.0.contract");
        assert((value.capabilities[0].provider.length == 16) && "redacted-capability-provider-inspection.capabilities.0.provider.length");
        assert((memcmp(value.capabilities[0].provider.data, "local-secrets-v1", 16) == 0) && "redacted-capability-provider-inspection.capabilities.0.provider");
        assert((value.capabilities[0].operations_count == 1) && "redacted-capability-provider-inspection.capabilities.0.operations.count");
        assert((value.capabilities[0].operations[0].length == 4) && "redacted-capability-provider-inspection.capabilities.0.operations.0.length");
        assert((memcmp(value.capabilities[0].operations[0].data, "read", 4) == 0) && "redacted-capability-provider-inspection.capabilities.0.operations.0");
        assert((value.capabilities[0].attributes_count == 0) && "redacted-capability-provider-inspection.capabilities.0.attributes.count");
        assert((value.capabilities[0].has_inspection) && "redacted-capability-provider-inspection.capabilities.0.inspection.presence");
        assert((value.capabilities[0].inspection.has_definition_digest) && "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence");
        assert((value.capabilities[0].inspection.definition_digest.length == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.length");
        assert((value.capabilities[0].inspection.has_provider_binding) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence");
        assert((value.capabilities[0].inspection.provider_binding.id.length == 9) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id.length");
        assert((memcmp(value.capabilities[0].inspection.provider_binding.id.data, "binding-a", 9) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id");
        assert((value.capabilities[0].inspection.provider_binding.revision == UINT64_C(18446744073709551615)) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision");
        assert((value.capabilities[0].inspection.provider_binding.digest.length == 71) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest.length");
        assert((memcmp(value.capabilities[0].inspection.provider_binding.digest.data, "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", 71) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest");
        assert((value.capabilities[0].inspection.policies_count == 1) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.count");
        assert((value.capabilities[0].inspection.policies[0].id.length == 8) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id.length");
        assert((memcmp(value.capabilities[0].inspection.policies[0].id.data, "policy-a", 8) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id");
        assert((value.capabilities[0].inspection.policies[0].revision == UINT64_C(9223372036854775808)) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision");
        assert((value.capabilities[0].inspection.policies[0].digest.length == 71) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest.length");
        assert((memcmp(value.capabilities[0].inspection.policies[0].digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest");
        assert((value.capabilities[0].inspection.provider_profile.length == 16) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile.length");
        assert((memcmp(value.capabilities[0].inspection.provider_profile.data, "local-secrets-v1", 16) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile");
        assert((value.capabilities[0].inspection.provider_configuration_digest.length == 71) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest.length");
        assert((memcmp(value.capabilities[0].inspection.provider_configuration_digest.data, "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", 71) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest");
        assert((value.capabilities[0].inspection.provider_configuration_epoch == UINT64_C(18446744073709551615)) && "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch");
        assert((value.capabilities[0].inspection.state.length == 30) && "redacted-capability-provider-inspection.capabilities.0.inspection.state.length");
        assert((memcmp(value.capabilities[0].inspection.state.data, "provider-configuration-changed", 30) == 0) && "redacted-capability-provider-inspection.capabilities.0.inspection.state");
        assert((value.capabilities[1].id.length == 17) && "redacted-capability-provider-inspection.capabilities.1.id.length");
        assert((memcmp(value.capabilities[1].id.data, "future-capability", 17) == 0) && "redacted-capability-provider-inspection.capabilities.1.id");
        assert((value.capabilities[1].contract.length == 15) && "redacted-capability-provider-inspection.capabilities.1.contract.length");
        assert((memcmp(value.capabilities[1].contract.data, "future-contract", 15) == 0) && "redacted-capability-provider-inspection.capabilities.1.contract");
        assert((value.capabilities[1].provider.length == 15) && "redacted-capability-provider-inspection.capabilities.1.provider.length");
        assert((memcmp(value.capabilities[1].provider.data, "future-provider", 15) == 0) && "redacted-capability-provider-inspection.capabilities.1.provider");
        assert((value.capabilities[1].operations_count == 0) && "redacted-capability-provider-inspection.capabilities.1.operations.count");
        assert((value.capabilities[1].attributes_count == 1) && "redacted-capability-provider-inspection.capabilities.1.attributes.count");
        assert((value.capabilities[1].attributes[0].key.length == 11) && "redacted-capability-provider-inspection.capabilities.1.attributes.key.length");
        assert((memcmp(value.capabilities[1].attributes[0].key.data, "descriptive", 11) == 0) && "redacted-capability-provider-inspection.capabilities.1.attributes.key");
        assert((value.capabilities[1].attributes[0].value.length == 13) && "redacted-capability-provider-inspection.capabilities.1.attributes.0.length");
        assert((memcmp(value.capabilities[1].attributes[0].value.data, "not-authority", 13) == 0) && "redacted-capability-provider-inspection.capabilities.1.attributes.0");
        assert((!(value.capabilities[1].has_inspection)) && "redacted-capability-provider-inspection.capabilities.1.inspection.presence");
        assert((value.has_page) && "redacted-capability-provider-inspection.page.presence");
        assert((value.page.has_next_page_token) && "redacted-capability-provider-inspection.page.next_page_token.presence");
        assert((value.page.next_page_token.length == 24) && "redacted-capability-provider-inspection.page.next_page_token.length");
        assert((memcmp(value.page.next_page_token.data, "opaque-capability-cursor", 24) == 0) && "redacted-capability-provider-inspection.page.next_page_token");
        assert((value.has_revision) && "redacted-capability-provider-inspection.revision.presence");
        assert((value.revision.deployment_id.length == 12) && "redacted-capability-provider-inspection.revision.deployment_id.length");
        assert((memcmp(value.revision.deployment_id.data, "deployment-a", 12) == 0) && "redacted-capability-provider-inspection.revision.deployment_id");
        assert((value.revision.revision_id.length == 10) && "redacted-capability-provider-inspection.revision.revision_id.length");
        assert((memcmp(value.revision.revision_id.data, "revision-a", 10) == 0) && "redacted-capability-provider-inspection.revision.revision_id");
        assert((value.revision.component_digest.length == 71) && "redacted-capability-provider-inspection.revision.component_digest.length");
        assert((memcmp(value.revision.component_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "redacted-capability-provider-inspection.revision.component_digest");
        assert((value.revision.has_publication_id) && "redacted-capability-provider-inspection.revision.publication_id.presence");
        assert((value.revision.publication_id.length == 83) && "redacted-capability-provider-inspection.revision.publication_id.length");
        assert((memcmp(value.revision.publication_id.data, "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 83) == 0) && "redacted-capability-provider-inspection.revision.publication_id");
        assert((value.revision.route_generation == UINT64_C(18446744073709551615)) && "redacted-capability-provider-inspection.revision.route_generation");
        assert((value.revision.catalog_transaction == UINT64_C(9223372036854775808)) && "redacted-capability-provider-inspection.revision.catalog_transaction");
        assert((value.has_tenant_usage) && "redacted-capability-provider-inspection.tenant_usage.presence");
        assert((value.tenant_usage.scope.length == 6) && "redacted-capability-provider-inspection.tenant_usage.scope.length");
        assert((memcmp(value.tenant_usage.scope.data, "tenant", 6) == 0) && "redacted-capability-provider-inspection.tenant_usage.scope");
        assert((value.tenant_usage.counters_count == 2) && "redacted-capability-provider-inspection.tenant_usage.counters.count");
        assert((value.tenant_usage.counters[0].key.length == 8) && "redacted-capability-provider-inspection.tenant_usage.counters.key.length");
        assert((memcmp(value.tenant_usage.counters[0].key.data, "sessions", 8) == 0) && "redacted-capability-provider-inspection.tenant_usage.counters.key");
        assert((value.tenant_usage.counters[0].value == UINT64_C(18446744073709551615)) && "redacted-capability-provider-inspection.tenant_usage.counters.0");
        assert((value.tenant_usage.counters[1].key.length == 5) && "redacted-capability-provider-inspection.tenant_usage.counters.key.length");
        assert((memcmp(value.tenant_usage.counters[1].key.data, "calls", 5) == 0) && "redacted-capability-provider-inspection.tenant_usage.counters.key");
        assert((value.tenant_usage.counters[1].value == UINT64_C(0)) && "redacted-capability-provider-inspection.tenant_usage.counters.1");
        assert((value.tenant_usage.unavailable_count == 1) && "redacted-capability-provider-inspection.tenant_usage.unavailable.count");
        assert((value.tenant_usage.unavailable[0].length == 25) && "redacted-capability-provider-inspection.tenant_usage.unavailable.0.length");
        assert((memcmp(value.tenant_usage.unavailable[0].data, "fixture-owner-unavailable", 25) == 0) && "redacted-capability-provider-inspection.tenant_usage.unavailable.0");
        assert((!(value.has_node_usage)) && "redacted-capability-provider-inspection.node_usage.presence");
        assert((value.state.length == 7) && "redacted-capability-provider-inspection.state.length");
        assert((memcmp(value.state.data, "sampled", 7) == 0) && "redacted-capability-provider-inspection.state");
    }
    {
        latent_profile_list_capabilities_response value = (latent_profile_list_capabilities_response){.capabilities = NULL, .capabilities_count = 0, .has_node_usage = true, .node_usage = (latent_profile_capability_resource_usage){.scope = PROFILE_TEXT("node"), .counters = NULL, .counters_count = 0, .unavailable = (const latent_string[]){PROFILE_TEXT("provider-pools-no-retained-owner"), PROFILE_TEXT("audit-owner-not-configured")}, .unavailable_count = 2}, .state = PROFILE_TEXT("binding-plan-unavailable")};
        assert((value.capabilities_count == 0) && "missing-provider-plan-not-zero-usage.capabilities.count");
        assert((!(value.has_page)) && "missing-provider-plan-not-zero-usage.page.presence");
        assert((!(value.has_revision)) && "missing-provider-plan-not-zero-usage.revision.presence");
        assert((!(value.has_tenant_usage)) && "missing-provider-plan-not-zero-usage.tenant_usage.presence");
        assert((value.has_node_usage) && "missing-provider-plan-not-zero-usage.node_usage.presence");
        assert((value.node_usage.scope.length == 4) && "missing-provider-plan-not-zero-usage.node_usage.scope.length");
        assert((memcmp(value.node_usage.scope.data, "node", 4) == 0) && "missing-provider-plan-not-zero-usage.node_usage.scope");
        assert((value.node_usage.counters_count == 0) && "missing-provider-plan-not-zero-usage.node_usage.counters.count");
        assert((value.node_usage.unavailable_count == 2) && "missing-provider-plan-not-zero-usage.node_usage.unavailable.count");
        assert((value.node_usage.unavailable[0].length == 32) && "missing-provider-plan-not-zero-usage.node_usage.unavailable.0.length");
        assert((memcmp(value.node_usage.unavailable[0].data, "provider-pools-no-retained-owner", 32) == 0) && "missing-provider-plan-not-zero-usage.node_usage.unavailable.0");
        assert((value.node_usage.unavailable[1].length == 26) && "missing-provider-plan-not-zero-usage.node_usage.unavailable.1.length");
        assert((memcmp(value.node_usage.unavailable[1].data, "audit-owner-not-configured", 26) == 0) && "missing-provider-plan-not-zero-usage.node_usage.unavailable.1");
        assert((value.state.length == 24) && "missing-provider-plan-not-zero-usage.state.length");
        assert((memcmp(value.state.data, "binding-plan-unavailable", 24) == 0) && "missing-provider-plan-not-zero-usage.state");
    }
    {
        latent_profile_capability_inspection_ceiling value = (latent_profile_capability_inspection_ceiling){.operations = 0U, .input_bytes = UINT64_C(18446744073709551615), .output_bytes = UINT64_C(0), .wall_time_millis = UINT64_C(18446744073709551615)};
        assert((value.operations == 0U) && "typed-ceiling-zero-and-max-not-grant.operations");
        assert((value.input_bytes == UINT64_C(18446744073709551615)) && "typed-ceiling-zero-and-max-not-grant.input_bytes");
        assert((value.output_bytes == UINT64_C(0)) && "typed-ceiling-zero-and-max-not-grant.output_bytes");
        assert((value.wall_time_millis == UINT64_C(18446744073709551615)) && "typed-ceiling-zero-and-max-not-grant.wall_time_millis");
    }
    {
        latent_profile_call_options value = (latent_profile_call_options){0};
        assert((!(value.has_timeout_millis)) && "local-timeout-absent.timeout_millis.presence");
    }
    {
        latent_profile_call_options value = (latent_profile_call_options){.has_timeout_millis = true, .timeout_millis = UINT64_C(0)};
        assert((value.has_timeout_millis) && "local-timeout-zero.timeout_millis.presence");
        assert((value.timeout_millis == UINT64_C(0)) && "local-timeout-zero.timeout_millis");
    }
    {
        latent_profile_call_options value = (latent_profile_call_options){.has_timeout_millis = true, .timeout_millis = UINT64_C(18446744073709551615)};
        assert((value.has_timeout_millis) && "local-timeout-max-not-wrapped.timeout_millis.presence");
        assert((value.timeout_millis == UINT64_C(18446744073709551615)) && "local-timeout-max-not-wrapped.timeout_millis");
    }
    {
        latent_profile_client_failure value = (latent_profile_client_failure){.category = ((latent_profile_failure_category)(1)), .message = PROFILE_TEXT("local-cancelled"), .dispatched = false, .outcome = ((latent_profile_outcome_knowledge)(1)), .identity = (latent_profile_request_identity){.has_activation_id = true, .activation_id = PROFILE_TEXT("activation-a")}};
        assert((value.category == 1) && "local-cancel-before-dispatch.category");
        assert((value.message.length == 15) && "local-cancel-before-dispatch.message.length");
        assert((memcmp(value.message.data, "local-cancelled", 15) == 0) && "local-cancel-before-dispatch.message");
        assert((!(value.has_grpc_status)) && "local-cancel-before-dispatch.grpc_status.presence");
        assert((!(value.has_platform_error)) && "local-cancel-before-dispatch.platform_error.presence");
        assert((value.dispatched == false) && "local-cancel-before-dispatch.dispatched");
        assert((value.outcome == 1) && "local-cancel-before-dispatch.outcome");
        assert((value.identity.has_activation_id) && "local-cancel-before-dispatch.identity.activation_id.presence");
        assert((value.identity.activation_id.length == 12) && "local-cancel-before-dispatch.identity.activation_id.length");
        assert((memcmp(value.identity.activation_id.data, "activation-a", 12) == 0) && "local-cancel-before-dispatch.identity.activation_id");
        assert((!(value.identity.has_operation_id)) && "local-cancel-before-dispatch.identity.operation_id.presence");
        assert((!(value.has_audit_ack)) && "local-cancel-before-dispatch.audit_ack.presence");
        assert((!(value.has_audit_status)) && "local-cancel-before-dispatch.audit_status.presence");
        assert((!(value.has_unsupported_wire_value)) && "local-cancel-before-dispatch.unsupported_wire_value.presence");
        assert((!(value.has_audit_attempt_sequence)) && "local-cancel-before-dispatch.audit_attempt_sequence.presence");
    }
    {
        latent_profile_client_failure value = (latent_profile_client_failure){.category = ((latent_profile_failure_category)(2)), .message = PROFILE_TEXT("deadline"), .has_grpc_status = true, .grpc_status = 4, .dispatched = true, .outcome = ((latent_profile_outcome_knowledge)(2)), .identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .has_audit_ack = true, .audit_ack = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(2)), .has_attempt_sequence = true, .attempt_sequence = UINT64_C(18446744073709551615)}, .has_audit_status = true, .audit_status = PROFILE_TEXT("outcome-unknown"), .has_audit_attempt_sequence = true, .audit_attempt_sequence = UINT64_C(18446744073709551615)};
        assert((value.category == 2) && "deadline-after-dispatch-is-uncertain.category");
        assert((value.message.length == 8) && "deadline-after-dispatch-is-uncertain.message.length");
        assert((memcmp(value.message.data, "deadline", 8) == 0) && "deadline-after-dispatch-is-uncertain.message");
        assert((value.has_grpc_status) && "deadline-after-dispatch-is-uncertain.grpc_status.presence");
        assert((value.grpc_status == 4) && "deadline-after-dispatch-is-uncertain.grpc_status");
        assert((!(value.has_platform_error)) && "deadline-after-dispatch-is-uncertain.platform_error.presence");
        assert((value.dispatched == true) && "deadline-after-dispatch-is-uncertain.dispatched");
        assert((value.outcome == 2) && "deadline-after-dispatch-is-uncertain.outcome");
        assert((!(value.identity.has_activation_id)) && "deadline-after-dispatch-is-uncertain.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "deadline-after-dispatch-is-uncertain.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "deadline-after-dispatch-is-uncertain.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "deadline-after-dispatch-is-uncertain.identity.operation_id");
        assert((value.has_audit_ack) && "deadline-after-dispatch-is-uncertain.audit_ack.presence");
        assert((value.audit_ack.status == 2) && "deadline-after-dispatch-is-uncertain.audit_ack.status");
        assert((value.audit_ack.has_attempt_sequence) && "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence");
        assert((value.audit_ack.attempt_sequence == UINT64_C(18446744073709551615)) && "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence");
        assert((value.has_audit_status) && "deadline-after-dispatch-is-uncertain.audit_status.presence");
        assert((value.audit_status.length == 15) && "deadline-after-dispatch-is-uncertain.audit_status.length");
        assert((memcmp(value.audit_status.data, "outcome-unknown", 15) == 0) && "deadline-after-dispatch-is-uncertain.audit_status");
        assert((!(value.has_unsupported_wire_value)) && "deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence");
        assert((value.has_audit_attempt_sequence) && "deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence");
        assert((value.audit_attempt_sequence == UINT64_C(18446744073709551615)) && "deadline-after-dispatch-is-uncertain.audit_attempt_sequence");
    }
    {
        latent_profile_client_failure value = (latent_profile_client_failure){.category = ((latent_profile_failure_category)(4)), .message = PROFILE_TEXT("capability-policy-conflict"), .has_grpc_status = true, .grpc_status = 9, .has_platform_error = true, .platform_error = (latent_profile_platform_error){.code = PROFILE_TEXT("state-conflict"), .message = PROFILE_TEXT("capability-policy-conflict"), .retryable = false, .detail_items = (const latent_profile_error_detail[]){(latent_profile_error_detail){.kind = PROFILE_TEXT("future-detail"), .fields = (const latent_key_value[]){{.key = PROFILE_TEXT("value"), .value = PROFILE_TEXT("retained")}}, .fields_count = 1}}, .detail_items_count = 1}, .dispatched = true, .outcome = ((latent_profile_outcome_knowledge)(3)), .identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}};
        assert((value.category == 4) && "rpc-conflict-retains-request-identity.category");
        assert((value.message.length == 26) && "rpc-conflict-retains-request-identity.message.length");
        assert((memcmp(value.message.data, "capability-policy-conflict", 26) == 0) && "rpc-conflict-retains-request-identity.message");
        assert((value.has_grpc_status) && "rpc-conflict-retains-request-identity.grpc_status.presence");
        assert((value.grpc_status == 9) && "rpc-conflict-retains-request-identity.grpc_status");
        assert((value.has_platform_error) && "rpc-conflict-retains-request-identity.platform_error.presence");
        assert((value.platform_error.code.length == 14) && "rpc-conflict-retains-request-identity.platform_error.code.length");
        assert((memcmp(value.platform_error.code.data, "state-conflict", 14) == 0) && "rpc-conflict-retains-request-identity.platform_error.code");
        assert((value.platform_error.message.length == 26) && "rpc-conflict-retains-request-identity.platform_error.message.length");
        assert((memcmp(value.platform_error.message.data, "capability-policy-conflict", 26) == 0) && "rpc-conflict-retains-request-identity.platform_error.message");
        assert((value.platform_error.retryable == false) && "rpc-conflict-retains-request-identity.platform_error.retryable");
        assert((value.platform_error.detail_items_count == 1) && "rpc-conflict-retains-request-identity.platform_error.detail_items.count");
        assert((value.platform_error.detail_items[0].kind.length == 13) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind.length");
        assert((memcmp(value.platform_error.detail_items[0].kind.data, "future-detail", 13) == 0) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind");
        assert((value.platform_error.detail_items[0].fields_count == 1) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count");
        assert((value.platform_error.detail_items[0].fields[0].key.length == 5) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.key.length");
        assert((memcmp(value.platform_error.detail_items[0].fields[0].key.data, "value", 5) == 0) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.key");
        assert((value.platform_error.detail_items[0].fields[0].value.length == 8) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0.length");
        assert((memcmp(value.platform_error.detail_items[0].fields[0].value.data, "retained", 8) == 0) && "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0");
        assert((value.dispatched == true) && "rpc-conflict-retains-request-identity.dispatched");
        assert((value.outcome == 3) && "rpc-conflict-retains-request-identity.outcome");
        assert((!(value.identity.has_activation_id)) && "rpc-conflict-retains-request-identity.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "rpc-conflict-retains-request-identity.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "rpc-conflict-retains-request-identity.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "rpc-conflict-retains-request-identity.identity.operation_id");
        assert((!(value.has_audit_ack)) && "rpc-conflict-retains-request-identity.audit_ack.presence");
        assert((!(value.has_audit_status)) && "rpc-conflict-retains-request-identity.audit_status.presence");
        assert((!(value.has_unsupported_wire_value)) && "rpc-conflict-retains-request-identity.unsupported_wire_value.presence");
        assert((!(value.has_audit_attempt_sequence)) && "rpc-conflict-retains-request-identity.audit_attempt_sequence.presence");
    }
    {
        latent_profile_client_failure value = (latent_profile_client_failure){.category = ((latent_profile_failure_category)(5)), .message = PROFILE_TEXT("invalid-response"), .dispatched = true, .outcome = ((latent_profile_outcome_knowledge)(2)), .identity = (latent_profile_request_identity){.has_activation_id = true, .activation_id = PROFILE_TEXT("activation-a"), .has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .has_unsupported_wire_value = true, .unsupported_wire_value = (latent_profile_unsupported_wire_value){.field = PROFILE_TEXT("phase"), .value = PROFILE_TEXT("future-phase-not-authority")}};
        assert((value.category == 5) && "decode-failure-retains-known-identity.category");
        assert((value.message.length == 16) && "decode-failure-retains-known-identity.message.length");
        assert((memcmp(value.message.data, "invalid-response", 16) == 0) && "decode-failure-retains-known-identity.message");
        assert((!(value.has_grpc_status)) && "decode-failure-retains-known-identity.grpc_status.presence");
        assert((!(value.has_platform_error)) && "decode-failure-retains-known-identity.platform_error.presence");
        assert((value.dispatched == true) && "decode-failure-retains-known-identity.dispatched");
        assert((value.outcome == 2) && "decode-failure-retains-known-identity.outcome");
        assert((value.identity.has_activation_id) && "decode-failure-retains-known-identity.identity.activation_id.presence");
        assert((value.identity.activation_id.length == 12) && "decode-failure-retains-known-identity.identity.activation_id.length");
        assert((memcmp(value.identity.activation_id.data, "activation-a", 12) == 0) && "decode-failure-retains-known-identity.identity.activation_id");
        assert((value.identity.has_operation_id) && "decode-failure-retains-known-identity.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "decode-failure-retains-known-identity.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "decode-failure-retains-known-identity.identity.operation_id");
        assert((!(value.has_audit_ack)) && "decode-failure-retains-known-identity.audit_ack.presence");
        assert((!(value.has_audit_status)) && "decode-failure-retains-known-identity.audit_status.presence");
        assert((value.has_unsupported_wire_value) && "decode-failure-retains-known-identity.unsupported_wire_value.presence");
        assert((value.unsupported_wire_value.field.length == 5) && "decode-failure-retains-known-identity.unsupported_wire_value.field.length");
        assert((memcmp(value.unsupported_wire_value.field.data, "phase", 5) == 0) && "decode-failure-retains-known-identity.unsupported_wire_value.field");
        assert((value.unsupported_wire_value.value.length == 26) && "decode-failure-retains-known-identity.unsupported_wire_value.value.length");
        assert((memcmp(value.unsupported_wire_value.value.data, "future-phase-not-authority", 26) == 0) && "decode-failure-retains-known-identity.unsupported_wire_value.value");
        assert((!(value.has_audit_attempt_sequence)) && "decode-failure-retains-known-identity.audit_attempt_sequence.presence");
    }
    {
        latent_profile_response_metadata value = (latent_profile_response_metadata){.identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .outcome = ((latent_profile_outcome_knowledge)(3)), .has_audit_ack = true, .audit_ack = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(2)), .has_attempt_sequence = true, .attempt_sequence = UINT64_C(18446744073709551615)}, .has_audit_status = true, .audit_status = PROFILE_TEXT("outcome-unknown"), .has_audit_attempt_sequence = true, .audit_attempt_sequence = UINT64_C(18446744073709551615)};
        assert((!(value.identity.has_activation_id)) && "observed-receipt-audit-outcome-independent.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "observed-receipt-audit-outcome-independent.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "observed-receipt-audit-outcome-independent.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "observed-receipt-audit-outcome-independent.identity.operation_id");
        assert((value.outcome == 3) && "observed-receipt-audit-outcome-independent.outcome");
        assert((value.has_audit_ack) && "observed-receipt-audit-outcome-independent.audit_ack.presence");
        assert((value.audit_ack.status == 2) && "observed-receipt-audit-outcome-independent.audit_ack.status");
        assert((value.audit_ack.has_attempt_sequence) && "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence");
        assert((value.audit_ack.attempt_sequence == UINT64_C(18446744073709551615)) && "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence");
        assert((value.has_audit_status) && "observed-receipt-audit-outcome-independent.audit_status.presence");
        assert((value.audit_status.length == 15) && "observed-receipt-audit-outcome-independent.audit_status.length");
        assert((memcmp(value.audit_status.data, "outcome-unknown", 15) == 0) && "observed-receipt-audit-outcome-independent.audit_status");
        assert((value.has_audit_attempt_sequence) && "observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence");
        assert((value.audit_attempt_sequence == UINT64_C(18446744073709551615)) && "observed-receipt-audit-outcome-independent.audit_attempt_sequence");
    }
    {
        latent_profile_response_metadata value = (latent_profile_response_metadata){.identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .outcome = ((latent_profile_outcome_knowledge)(3))};
        assert((!(value.identity.has_activation_id)) && "policy-response-has-no-fabricated-audit.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "policy-response-has-no-fabricated-audit.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "policy-response-has-no-fabricated-audit.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "policy-response-has-no-fabricated-audit.identity.operation_id");
        assert((value.outcome == 3) && "policy-response-has-no-fabricated-audit.outcome");
        assert((!(value.has_audit_ack)) && "policy-response-has-no-fabricated-audit.audit_ack.presence");
        assert((!(value.has_audit_status)) && "policy-response-has-no-fabricated-audit.audit_status.presence");
        assert((!(value.has_audit_attempt_sequence)) && "policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence");
    }
    {
        latent_profile_response_metadata value = (latent_profile_response_metadata){.identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .outcome = ((latent_profile_outcome_knowledge)(2))};
        assert((!(value.identity.has_activation_id)) && "missing-recovery-keeps-outcome-unknown.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "missing-recovery-keeps-outcome-unknown.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "missing-recovery-keeps-outcome-unknown.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "missing-recovery-keeps-outcome-unknown.identity.operation_id");
        assert((value.outcome == 2) && "missing-recovery-keeps-outcome-unknown.outcome");
        assert((!(value.has_audit_ack)) && "missing-recovery-keeps-outcome-unknown.audit_ack.presence");
        assert((!(value.has_audit_status)) && "missing-recovery-keeps-outcome-unknown.audit_status.presence");
        assert((!(value.has_audit_attempt_sequence)) && "missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence");
    }
    {
        latent_profile_response_metadata value = (latent_profile_response_metadata){.identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .outcome = ((latent_profile_outcome_knowledge)(91)), .has_audit_ack = true, .audit_ack = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(91)), .has_attempt_sequence = true, .attempt_sequence = UINT64_C(0)}, .has_audit_status = true, .audit_status = PROFILE_TEXT("future-audit-status"), .has_audit_attempt_sequence = true, .audit_attempt_sequence = UINT64_C(0)};
        assert((!(value.identity.has_activation_id)) && "unknown-audit-enum-and-status.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "unknown-audit-enum-and-status.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "unknown-audit-enum-and-status.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "unknown-audit-enum-and-status.identity.operation_id");
        assert((value.outcome == 91) && "unknown-audit-enum-and-status.outcome");
        assert((value.has_audit_ack) && "unknown-audit-enum-and-status.audit_ack.presence");
        assert((value.audit_ack.status == 91) && "unknown-audit-enum-and-status.audit_ack.status");
        assert((value.audit_ack.has_attempt_sequence) && "unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence");
        assert((value.audit_ack.attempt_sequence == UINT64_C(0)) && "unknown-audit-enum-and-status.audit_ack.attempt_sequence");
        assert((value.has_audit_status) && "unknown-audit-enum-and-status.audit_status.presence");
        assert((value.audit_status.length == 19) && "unknown-audit-enum-and-status.audit_status.length");
        assert((memcmp(value.audit_status.data, "future-audit-status", 19) == 0) && "unknown-audit-enum-and-status.audit_status");
        assert((value.has_audit_attempt_sequence) && "unknown-audit-enum-and-status.audit_attempt_sequence.presence");
        assert((value.audit_attempt_sequence == UINT64_C(0)) && "unknown-audit-enum-and-status.audit_attempt_sequence");
    }
    {
        latent_profile_response_metadata value = (latent_profile_response_metadata){.identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .outcome = ((latent_profile_outcome_knowledge)(3)), .has_audit_status = true, .audit_status = PROFILE_TEXT("future-state"), .has_audit_attempt_sequence = true, .audit_attempt_sequence = UINT64_C(18446744073709551615)};
        assert((!(value.identity.has_activation_id)) && "unknown-audit-header-and-max-attempt.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "unknown-audit-header-and-max-attempt.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "unknown-audit-header-and-max-attempt.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "unknown-audit-header-and-max-attempt.identity.operation_id");
        assert((value.outcome == 3) && "unknown-audit-header-and-max-attempt.outcome");
        assert((!(value.has_audit_ack)) && "unknown-audit-header-and-max-attempt.audit_ack.presence");
        assert((value.has_audit_status) && "unknown-audit-header-and-max-attempt.audit_status.presence");
        assert((value.audit_status.length == 12) && "unknown-audit-header-and-max-attempt.audit_status.length");
        assert((memcmp(value.audit_status.data, "future-state", 12) == 0) && "unknown-audit-header-and-max-attempt.audit_status");
        assert((value.has_audit_attempt_sequence) && "unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
        assert((value.audit_attempt_sequence == UINT64_C(18446744073709551615)) && "unknown-audit-header-and-max-attempt.audit_attempt_sequence");
    }
    {
        latent_profile_client_failure value = (latent_profile_client_failure){.category = ((latent_profile_failure_category)(4)), .message = PROFILE_TEXT("rpc-failure"), .has_grpc_status = true, .grpc_status = 13, .dispatched = true, .outcome = ((latent_profile_outcome_knowledge)(2)), .identity = (latent_profile_request_identity){.has_operation_id = true, .operation_id = PROFILE_TEXT("operation-a")}, .has_audit_status = true, .audit_status = PROFILE_TEXT("future-state"), .has_audit_attempt_sequence = true, .audit_attempt_sequence = UINT64_C(18446744073709551615)};
        assert((value.category == 4) && "failed-rpc-unknown-audit-header-and-max-attempt.category");
        assert((value.message.length == 11) && "failed-rpc-unknown-audit-header-and-max-attempt.message.length");
        assert((memcmp(value.message.data, "rpc-failure", 11) == 0) && "failed-rpc-unknown-audit-header-and-max-attempt.message");
        assert((value.has_grpc_status) && "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence");
        assert((value.grpc_status == 13) && "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status");
        assert((!(value.has_platform_error)) && "failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence");
        assert((value.dispatched == true) && "failed-rpc-unknown-audit-header-and-max-attempt.dispatched");
        assert((value.outcome == 2) && "failed-rpc-unknown-audit-header-and-max-attempt.outcome");
        assert((!(value.identity.has_activation_id)) && "failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence");
        assert((value.identity.has_operation_id) && "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence");
        assert((value.identity.operation_id.length == 11) && "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.length");
        assert((memcmp(value.identity.operation_id.data, "operation-a", 11) == 0) && "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id");
        assert((!(value.has_audit_ack)) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence");
        assert((value.has_audit_status) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence");
        assert((value.audit_status.length == 12) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.length");
        assert((memcmp(value.audit_status.data, "future-state", 12) == 0) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_status");
        assert((!(value.has_unsupported_wire_value)) && "failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence");
        assert((value.has_audit_attempt_sequence) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
        assert((value.audit_attempt_sequence == UINT64_C(18446744073709551615)) && "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence");
    }
    {
        latent_profile_audit_ack value = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(1))};
        assert((value.status == 1) && "audit-durable-attempt-absent.status");
        assert((!(value.has_attempt_sequence)) && "audit-durable-attempt-absent.attempt_sequence.presence");
    }
    {
        latent_profile_audit_ack value = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(3)), .has_attempt_sequence = true, .attempt_sequence = UINT64_C(0)};
        assert((value.status == 3) && "audit-unavailable-attempt-zero.status");
        assert((value.has_attempt_sequence) && "audit-unavailable-attempt-zero.attempt_sequence.presence");
        assert((value.attempt_sequence == UINT64_C(0)) && "audit-unavailable-attempt-zero.attempt_sequence");
    }
    {
        latent_profile_audit_ack value = (latent_profile_audit_ack){.status = ((latent_profile_audit_ack_status)(4))};
        assert((value.status == 4) && "audit-disabled-distinct-from-absence.status");
        assert((!(value.has_attempt_sequence)) && "audit-disabled-distinct-from-absence.attempt_sequence.presence");
    }
    {
        latent_profile_publication_ref value = (latent_profile_publication_ref){.id = PROFILE_TEXT(""), .tenant = PROFILE_TEXT("tenant-a")};
        assert((value.id.length == 0) && "publication-reference-invalid-id.id.length");
        assert((value.tenant.length == 8) && "publication-reference-invalid-id.tenant.length");
        assert((memcmp(value.tenant.data, "tenant-a", 8) == 0) && "publication-reference-invalid-id.tenant");
    }
    {
        latent_profile_publication_ref value = (latent_profile_publication_ref){.id = PROFILE_TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), .tenant = PROFILE_TEXT("tenant-b")};
        assert((value.id.length == 83) && "publication-reference-tenant-scope.id.length");
        assert((memcmp(value.id.data, "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 83) == 0) && "publication-reference-tenant-scope.id");
        assert((value.tenant.length == 8) && "publication-reference-tenant-scope.tenant.length");
        assert((memcmp(value.tenant.data, "tenant-b", 8) == 0) && "publication-reference-tenant-scope.tenant");
    }
    {
        latent_profile_publication_identity value = (latent_profile_publication_identity){.publication = (latent_profile_publication_ref){.id = PROFILE_TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), .tenant = PROFILE_TEXT("tenant-a")}, .component_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .package_digest = PROFILE_TEXT("sha256:1111111111111111111111111111111111111111111111111111111111111111")};
        assert((value.publication.id.length == 83) && "publication-original-package.publication.id.length");
        assert((memcmp(value.publication.id.data, "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", 83) == 0) && "publication-original-package.publication.id");
        assert((value.publication.tenant.length == 8) && "publication-original-package.publication.tenant.length");
        assert((memcmp(value.publication.tenant.data, "tenant-a", 8) == 0) && "publication-original-package.publication.tenant");
        assert((value.component_digest.length == 71) && "publication-original-package.component_digest.length");
        assert((memcmp(value.component_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "publication-original-package.component_digest");
        assert((value.package_digest.length == 71) && "publication-original-package.package_digest.length");
        assert((memcmp(value.package_digest.data, "sha256:1111111111111111111111111111111111111111111111111111111111111111", 71) == 0) && "publication-original-package.package_digest");
    }
    {
        latent_profile_publication_identity value = (latent_profile_publication_identity){.publication = (latent_profile_publication_ref){.id = PROFILE_TEXT("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222"), .tenant = PROFILE_TEXT("tenant-a")}, .component_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .package_digest = PROFILE_TEXT("sha256:2222222222222222222222222222222222222222222222222222222222222222")};
        assert((value.publication.id.length == 83) && "publication-corrected-package-same-component.publication.id.length");
        assert((memcmp(value.publication.id.data, "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", 83) == 0) && "publication-corrected-package-same-component.publication.id");
        assert((value.publication.tenant.length == 8) && "publication-corrected-package-same-component.publication.tenant.length");
        assert((memcmp(value.publication.tenant.data, "tenant-a", 8) == 0) && "publication-corrected-package-same-component.publication.tenant");
        assert((value.component_digest.length == 71) && "publication-corrected-package-same-component.component_digest.length");
        assert((memcmp(value.component_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "publication-corrected-package-same-component.component_digest");
        assert((value.package_digest.length == 71) && "publication-corrected-package-same-component.package_digest.length");
        assert((memcmp(value.package_digest.data, "sha256:2222222222222222222222222222222222222222222222222222222222222222", 71) == 0) && "publication-corrected-package-same-component.package_digest");
    }
    {
        latent_profile_publication_identity value = (latent_profile_publication_identity){.publication = (latent_profile_publication_ref){.id = PROFILE_TEXT("publication:sha256:3333333333333333333333333333333333333333333333333333333333333333"), .tenant = PROFILE_TEXT("tenant-b")}, .component_digest = PROFILE_TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), .package_digest = PROFILE_TEXT("sha256:2222222222222222222222222222222222222222222222222222222222222222")};
        assert((value.publication.id.length == 83) && "publication-other-tenant-same-package.publication.id.length");
        assert((memcmp(value.publication.id.data, "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", 83) == 0) && "publication-other-tenant-same-package.publication.id");
        assert((value.publication.tenant.length == 8) && "publication-other-tenant-same-package.publication.tenant.length");
        assert((memcmp(value.publication.tenant.data, "tenant-b", 8) == 0) && "publication-other-tenant-same-package.publication.tenant");
        assert((value.component_digest.length == 71) && "publication-other-tenant-same-package.component_digest.length");
        assert((memcmp(value.component_digest.data, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 71) == 0) && "publication-other-tenant-same-package.component_digest");
        assert((value.package_digest.length == 71) && "publication-other-tenant-same-package.package_digest.length");
        assert((memcmp(value.package_digest.data, "sha256:2222222222222222222222222222222222222222222222222222222222222222", 71) == 0) && "publication-other-tenant-same-package.package_digest");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("0"), &parsed);
        assert((valid == true) && "uint64 decimal");
        assert((parsed == UINT64_C(0)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("9007199254740993"), &parsed);
        assert((valid == true) && "uint64 decimal");
        assert((parsed == UINT64_C(9007199254740993)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("9223372036854775808"), &parsed);
        assert((valid == true) && "uint64 decimal");
        assert((parsed == UINT64_C(9223372036854775808)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("18446744073709551615"), &parsed);
        assert((valid == true) && "uint64 decimal");
        assert((parsed == UINT64_C(18446744073709551615)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("18446744073709551616"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("-1"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("+1"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("01"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT(" 1"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1 "), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1.0"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1e3"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT(""), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1\000"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1\n"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
    {
        uint64_t parsed = UINT64_C(42);
        bool valid = latent_profile_parse_u64(PROFILE_TEXT("1\r\n"), &parsed);
        assert((valid == false) && "uint64 decimal");
        assert((parsed == UINT64_C(42)) && "uint64 parsed or unchanged");
    }
}

#undef PROFILE_TEXT
