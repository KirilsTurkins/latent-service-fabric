#include "internal.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

/* These views use the offsets generated from the authoritative protobuf
 * descriptors. They do not own data or perform a second wire conversion. */
typedef struct tx_value {
    const lsf_message *message;
    const lsf_field *field;
    const uint8_t *data;
    size_t count;
} tx_value;
typedef struct tx_validator { latent_profile_call *call; bool valid; } tx_validator;

static tx_value object(const lsf_message *message, const void *data) {
    return (tx_value){message, NULL, data, 0};
}
static tx_value field(tx_value value, const char *name) {
    if (value.data == NULL || value.message == NULL) return (tx_value){0};
    for (size_t index = 0; index < value.message->field_count; ++index) {
        const lsf_field *definition = &value.message->fields[index];
        if (strcmp(definition->name, name) != 0) continue;
        if (definition->presence != LSF_NO_OFFSET && !*(const bool *)(value.data + definition->presence))
            return (tx_value){0};
        const uint8_t *data = value.data + definition->offset;
        size_t count = 0;
        if (definition->count != LSF_NO_OFFSET) {
            count = *(const size_t *)(value.data + definition->count);
            memcpy(&data, data, sizeof(data));
        }
        return (tx_value){definition->message, definition, data, count};
    }
    return (tx_value){0};
}
static tx_value item(tx_value list, size_t index) {
    if (list.field == NULL || list.data == NULL || index >= list.count) return (tx_value){0};
    return (tx_value){list.message, list.field, list.data + index * list.field->stride, SIZE_MAX};
}
static bool has(tx_value value) { return value.data != NULL; }
static void check(tx_validator *v, bool condition) { v->valid = v->valid && condition; }
static latent_string text(tx_value value) {
    return has(value) && value.field != NULL && value.field->kind == LSF_STRING
        ? *(const latent_string *)value.data : (latent_string){NULL, 0};
}
static latent_bytes data(tx_value value) {
    return has(value) && value.field != NULL && value.field->kind == LSF_BYTES
        ? *(const latent_bytes *)value.data : (latent_bytes){NULL, 0};
}
static uint64_t number(tx_value value) {
    if (!has(value) || value.field == NULL) return 0;
    return value.field->kind == LSF_U64 ? *(const uint64_t *)value.data
        : value.field->kind == LSF_U32 ? *(const uint32_t *)value.data : 0;
}
static bool boolean(tx_value value) {
    return has(value) && value.field != NULL && value.field->kind == LSF_BOOL && *(const bool *)value.data;
}
static bool equal(tx_value left, tx_value right) {
    if (!has(left) || !has(right)) return has(left) == has(right);
    if (left.field != NULL && right.field != NULL && left.field->kind != right.field->kind) return false;
    if (left.field != NULL && left.field->count != LSF_NO_OFFSET && left.count != SIZE_MAX && left.count != right.count) return false;
    if (left.message != NULL && right.message != NULL) {
        if (strcmp(left.message->name, right.message->name) != 0) return false;
        if (left.field != NULL && left.field->count != LSF_NO_OFFSET && left.count != SIZE_MAX) {
            for (size_t index = 0; index < left.count; ++index) {
                if (!left.field->map) { if (!equal(item(left, index), item(right, index))) return false; continue; }
                bool found = false;
                for (size_t other = 0; other < right.count; ++other)
                    if (equal(field(item(left, index), "key"), field(item(right, other), "key"))) {
                        if (!equal(item(left, index), item(right, other))) return false;
                        found = true; break;
                    }
                if (!found) return false;
            }
            return true;
        }
        for (size_t index = 0; index < left.message->field_count; ++index) {
            const char *name = left.message->fields[index].name;
            if (!equal(field(left, name), field(right, name))) return false;
        }
        return true;
    }
    if (left.field == NULL || right.field == NULL) return false;
    if (left.field->count != LSF_NO_OFFSET && left.count != SIZE_MAX) {
        for (size_t index = 0; index < left.count; ++index) if (!equal(item(left, index), item(right, index))) return false;
        return true;
    }
    if (left.field->kind == LSF_STRING) return lsf_text_equal(text(left), text(right));
    if (left.field->kind == LSF_BYTES) {
        latent_bytes a = data(left), b = data(right);
        return a.length == b.length && (a.length == 0 || memcmp(a.data, b.data, a.length) == 0);
    }
    return memcmp(left.data, right.data, left.field->stride) == 0;
}
static bool bounded_text(latent_string value, size_t maximum, bool required, bool controls) {
    if (value.length > maximum || (required && value.length == 0)
        || !lsf_utf8((const uint8_t *)value.data, value.length)) return false;
    if (controls) for (size_t index = 0; index < value.length; ++index) {
        uint8_t byte = (uint8_t)value.data[index];
        if (byte < 32 || byte == 127 || (byte == 194 && index + 1 < value.length
            && (uint8_t)value.data[index + 1] >= 128 && (uint8_t)value.data[index + 1] <= 159)) return false;
    }
    return true;
}
static void string_value(tx_validator *v, tx_value value, size_t maximum, bool required, bool controls) {
    check(v, has(value) && bounded_text(text(value), maximum, required, controls));
}
static void id(tx_validator *v, tx_value value) { string_value(v, value, 256, true, true); }
static void identity(tx_validator *v, tx_value value) {
    string_value(v, value, 256, true, false);
    latent_string input = text(value);
    check(v, input.length <= 256 && (input.length == 0 || input.data != NULL));
    if (input.length <= 256 && input.data != NULL) check(v, memchr(input.data, 0, input.length) == NULL);
}
static void optional_id(tx_validator *v, tx_value value) { if (has(value)) id(v, value); }
static void bytes(tx_validator *v, tx_value value, size_t maximum, bool required) {
    latent_bytes input = data(value);
    check(v, has(value) && input.length <= maximum && (!required || input.length != 0)
        && (input.length == 0 || input.data != NULL));
}
static int32_t enumeration(tx_validator *v, tx_value value, int32_t maximum, const char *name) {
    int32_t input = has(value) && value.field != NULL && value.field->kind == LSF_I32 ? *(const int32_t *)value.data : 0;
    if (input < 1 || input > maximum) {
        if (v->valid) {
            char raw[24]; int length = snprintf(raw, sizeof(raw), "%" PRId32, input);
            if (length > 0 && (size_t)length < sizeof(raw))
                lsf_unsupported(v->call, name, (latent_string){raw, (size_t)length});
        }
        check(v, false);
    }
    return input;
}
static void digest(tx_validator *v, tx_value value) {
    latent_string input = text(value);
    string_value(v, value, 71, true, true);
    bool valid = input.length == 71 && input.data != NULL && memcmp(input.data, "sha256:", 7) == 0;
    if (valid) for (size_t index = 7; index < 71; ++index) {
        char byte = input.data[index];
        valid = valid && ((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'));
    }
    check(v, valid);
}
static void publication_id(tx_validator *v, tx_value value) {
    latent_string input = text(value);
    id(v, value);
    bool valid = input.length == 83 && input.data != NULL && memcmp(input.data, "publication:", 12) == 0;
    check(v, valid);
    if (valid) {
        latent_string tail = {input.data + 12, 71};
        tx_value wrapped = value; wrapped.data = (const uint8_t *)&tail;
        digest(v, wrapped);
    }
}
static void namespace_value(tx_validator *v, tx_value value, latent_string tenant) {
    id(v, field(value, "tenant")); id(v, field(value, "namespace"));
    latent_string incarnation = text(field(value, "incarnation"));
    uint64_t parsed = 0;
    check(v, latent_profile_parse_u64(incarnation, &parsed) && parsed != 0
        && (tenant.length == 0 || lsf_text_equal(tenant, text(field(value, "tenant")))));
}
static void publication(tx_validator *v, tx_value value, latent_string tenant) {
    publication_id(v, field(value, "id")); id(v, field(value, "tenant"));
    check(v, lsf_text_equal(text(field(value, "tenant")), tenant));
}
static void profile(tx_validator *v, tx_value value) {
    latent_transaction_transaction_profile current = latent_transaction_current_profile();
    check(v, has(value) && lsf_text_equal(text(field(value, "profile")), current.profile)
        && lsf_text_equal(text(field(value, "host_abi_digest")), current.host_abi_digest)
        && lsf_text_equal(text(field(value, "preparation_profile_digest")), current.preparation_profile_digest));
}
static latent_string selector(tx_validator *v, tx_value value) {
    namespace_value(v, field(value, "namespace"), (latent_string){NULL, 0});
    identity(v, field(value, "operation")); identity(v, field(value, "client_key"));
    if (has(field(value, "entity"))) identity(v, field(value, "entity"));
    if (has(field(value, "shared_recovery_scope"))) identity(v, field(value, "shared_recovery_scope"));
    return text(field(field(value, "namespace"), "tenant"));
}
static void lookup(tx_validator *v, tx_value value) {
    profile(v, field(value, "profile"));
    publication(v, field(value, "authorization_publication"), selector(v, field(value, "command")));
    optional_id(v, field(value, "attempt_id"));
}
static void inspect(tx_validator *v, tx_value value) {
    profile(v, field(value, "profile"));
    namespace_value(v, field(value, "namespace"), (latent_string){NULL, 0});
    publication(v, field(value, "authorization_publication"), text(field(field(value, "namespace"), "tenant")));
}
static void fence(tx_validator *v, tx_value value) {
    id(v, field(value, "command_id")); id(v, field(value, "attempt_id")); id(v, field(value, "transaction_id"));
    bytes(v, field(value, "owner_fence"), 256, true);
}
static void page(tx_validator *v, tx_value value) {
    uint64_t limit = number(field(value, "limit")); check(v, has(value) && limit >= 1 && limit <= 128);
    if (has(field(value, "cursor"))) bytes(v, field(value, "cursor"), 256, true);
}
static void media(tx_validator *v, tx_value value) {
    string_value(v, value, 128, true, true);
    latent_string input = text(value);
    if (input.length <= 128 && input.data != NULL) for (size_t index = 0; index < input.length; ++index)
        check(v, (uint8_t)input.data[index] >= 32 && (uint8_t)input.data[index] <= 126);
}
static void metadata(tx_validator *v, tx_value value, bool caller) {
    check(v, value.field != NULL && value.count <= 32 && (value.count == 0 || value.data != NULL));
    if (value.count > 32 || (value.count != 0 && value.data == NULL)) return;
    size_t total = 0;
    for (size_t index = 0; index < value.count; ++index) {
        tx_value entry = item(value, index);
        id(v, field(entry, "key")); string_value(v, field(entry, "value"), 1024, false, true);
        latent_string key = text(field(entry, "key"));
        total += key.length + text(field(entry, "value")).length;
        for (size_t previous = 0; previous < index; ++previous)
            check(v, !lsf_text_equal(key, text(field(item(value, previous), "key"))));
        if (caller && key.length <= 256 && key.data != NULL) {
            char lower[257];
            for (size_t byte = 0; byte < key.length; ++byte) lower[byte] = key.data[byte] >= 'A' && key.data[byte] <= 'Z'
                ? key.data[byte] + ('a' - 'A') : key.data[byte];
            lower[key.length] = 0;
            check(v, strncmp(lower, "latent.auth.", 12) != 0 && strncmp(lower, "latent.principal.", 17) != 0);
        }
    }
    check(v, total <= 8192);
}
static void invocation(tx_validator *v, tx_value value, latent_string tenant) {
    optional_id(v, field(value, "activation_id")); optional_id(v, field(value, "parent_activation_id"));
    optional_id(v, field(value, "root_activation_id")); optional_id(v, field(value, "idempotency_key"));
    check(v, !has(field(value, "parent_activation_id")) || has(field(value, "root_activation_id")));
    tx_value target = field(value, "target");
    id(v, field(target, "tenant")); id(v, field(target, "service")); id(v, field(target, "contract")); id(v, field(target, "function"));
    optional_id(v, field(target, "route")); check(v, lsf_text_equal(text(field(target, "tenant")), tenant));
    bytes(v, field(value, "payload"), 1048576, false); media(v, field(value, "media_type"));
    metadata(v, field(value, "metadata"), true);
    check(v, has(field(value, "budget")) && number(field(value, "priority")) <= 255);
}
static void quota(tx_validator *v, tx_value value) {
    const char *rows[] = {"state_keys", "result_rows", "effect_rows"};
    const char *sizes[] = {"state_bytes", "result_bytes", "effect_bytes", "payload_bytes", "recovery_bytes"};
    for (size_t index = 0; index < 3; ++index) {
        uint64_t n = number(field(value, rows[index])); check(v, n >= 1 && n <= 1000000);
    }
    for (size_t index = 0; index < 5; ++index) {
        uint64_t n = number(field(value, sizes[index])); check(v, n >= 1 && n <= 1073741824);
    }
    check(v, number(field(value, "recovery_bytes")) <= number(field(value, "result_bytes")));
}
static void generation(tx_validator *v, tx_value value) {
    check(v, has(value) && number(field(value, "owner_epoch")) != 0 && number(field(value, "revision")) != 0);
}
static void dispatcher_control(tx_validator *v, tx_value value) {
    profile(v, field(value, "profile")); enumeration(v, field(value, "scope"), 1, "dispatcher.scope");
    id(v, field(value, "operation_id")); enumeration(v, field(value, "action"), 2, "dispatcher.action");
    generation(v, field(value, "expected_generation"));
    check(v, number(field(field(value, "expected_generation"), "revision")) != UINT64_MAX);
}

static bool graph(tx_value value, unsigned depth, size_t *nodes, size_t *total) {
    if (value.field != NULL && value.field->count != LSF_NO_OFFSET && value.count != 0 && value.data == NULL) return false;
    if (!has(value)) return true;
    if (depth > LSF_MAX_DEPTH || *nodes == 0) return false;
    --*nodes;
    if (value.field != NULL && value.field->count != LSF_NO_OFFSET) {
        size_t maximum = value.field->map ? 32 : strcmp(value.field->name, "required_record_ids") == 0 ? 256 : 128;
        if (value.count > maximum || (value.count != 0 && value.data == NULL)) return false;
        for (size_t index = 0; index < value.count; ++index) {
            tx_value entry = item(value, index); lsf_field definition = *value.field;
            definition.count = LSF_NO_OFFSET; entry.field = &definition;
            if (!graph(entry, depth + 1, nodes, total)) return false;
        }
        return true;
    }
    if (value.message != NULL) {
        for (size_t index = 0; index < value.message->field_count; ++index)
            if (!graph(field(value, value.message->fields[index].name), depth + 1, nodes, total)) return false;
    } else if (value.field != NULL && value.field->kind == LSF_STRING) {
        latent_string input = text(value);
        if (!bounded_text(input, 4096, false, false)) return false;
        *total += input.length;
    } else if (value.field != NULL && value.field->kind == LSF_BYTES) {
        latent_bytes input = data(value);
        if (input.length > 1048576 || (input.length != 0 && input.data == NULL)) return false;
        *total += input.length;
    }
    return *total <= 8388608;
}

bool lsf_transaction_request_valid(latent_profile_call *call, const void *request) {
    tx_value value = object(lsf_rpcs[call->operation].request, request);
    size_t nodes = LSF_MAX_ELEMENTS, total = 0;
    if (!graph(value, 0, &nodes, &total)) return false;
    tx_validator v = {call, true};
    switch (call->operation) {
        case LSF_TX_invoke_command: {
            profile(&v, field(value, "profile"));
            latent_string tenant = selector(&v, field(value, "command"));
            check(&v, lsf_text_equal(tenant, call->owner->config.tenant));
            invocation(&v, field(value, "invocation"), tenant); identity(&v, field(value, "input_format"));
            tx_value versions = field(value, "expected_versions");
            for (size_t index = 0; index < versions.count; ++index) {
                tx_value entry = item(versions, index), key = field(entry, "key");
                bytes(&v, key, 1024, false);
                check(&v, has(field(entry, "absent")) != has(field(entry, "version")));
                if (has(field(entry, "absent"))) check(&v, boolean(field(entry, "absent")));
                if (has(field(entry, "version"))) bytes(&v, field(entry, "version"), 256, true);
                for (size_t previous = 0; previous < index; ++previous)
                    check(&v, !equal(key, field(item(versions, previous), "key")));
            }
            tx_value retry = field(value, "retry_attempt");
            if (has(retry)) { id(&v, field(retry, "request_id")); fence(&v, field(retry, "expected_abort")); }
            break;
        }
        case LSF_TX_query:
            profile(&v, field(value, "profile")); namespace_value(&v, field(value, "namespace"), call->owner->config.tenant);
            invocation(&v, field(value, "invocation"), call->owner->config.tenant);
            if (has(field(value, "entity"))) identity(&v, field(value, "entity"));
            if (has(field(value, "minimum_view_version"))) bytes(&v, field(value, "minimum_view_version"), 256, true);
            break;
        case LSF_TX_lookup_command: lookup(&v, value); break;
        case LSF_TX_lookup_commit: lookup(&v, value); id(&v, field(value, "receipt_id")); break;
        case LSF_TX_get_effect: lookup(&v, value); id(&v, field(value, "effect_id")); break;
        case LSF_TX_list_effect_history:
            lookup(&v, field(value, "effect")); id(&v, field(field(value, "effect"), "effect_id")); page(&v, field(value, "page")); break;
        case LSF_TX_cancel_command:
            lookup(&v, field(value, "command")); string_value(&v, field(value, "reason"), 1024, true, true); break;
        case LSF_TX_inspect_namespace: inspect(&v, value); break;
        case LSF_TX_select_entity:
            inspect(&v, field(value, "namespace")); page(&v, field(value, "page"));
            if (has(field(value, "prefix"))) bytes(&v, field(value, "prefix"), 256, false);
            break;
        case LSF_TX_get_state_operation_receipt:
            inspect(&v, field(value, "namespace")); id(&v, field(value, "operation_id")); break;
        case LSF_TX_mutate_state: {
            inspect(&v, field(value, "namespace")); id(&v, field(value, "operation_id"));
            bytes(&v, field(value, "expected_version"), 256, true); digest(&v, field(value, "expected_policy_digest"));
            string_value(&v, field(value, "reason"), 1024, true, true);
            int32_t mutation = enumeration(&v, field(value, "mutation"), 4, "state.mutation");
            check(&v, (mutation == 4) == !has(field(value, "record_id"))); optional_id(&v, field(value, "record_id")); break;
        }
        case LSF_TX_mutate_namespace: {
            tx_value target = field(value, "namespace"); inspect(&v, target); id(&v, field(value, "operation_id"));
            int32_t mutation = enumeration(&v, field(value, "mutation"), 5, "namespace.mutation");
            check(&v, has(field(value, "expected_generation")) && (mutation == 1) == (number(field(value, "expected_generation")) == 0));
            if (mutation == 1) check(&v, lsf_text_equal(text(field(field(target, "namespace"), "incarnation")), LSF_TEXT("1")));
            tx_value config = field(value, "configuration");
            if (mutation == 1 || mutation == 5) { id(&v, field(config, "state_schema")); quota(&v, field(config, "quota")); }
            else check(&v, !has(config));
            break;
        }
        case LSF_TX_inspect_dispatcher:
            profile(&v, field(value, "profile")); enumeration(&v, field(value, "scope"), 1, "dispatcher.scope"); break;
        case LSF_TX_control_dispatcher: dispatcher_control(&v, value); break;
        case LSF_TX_get_dispatcher_operation: dispatcher_control(&v, field(value, "original")); break;
        default: check(&v, false); break;
    }
    if (call->transaction_identity.namespace != NULL)
        check(&v, lsf_text_equal(call->transaction_identity.namespace->tenant, call->owner->config.tenant));
    return v.valid;
}

static void source(tx_validator *v, tx_value value) {
    publication_id(v, field(value, "publication_id")); identity(v, field(value, "revision_id"));
    identity(v, field(value, "input_format")); identity(v, field(value, "result_format"));
    digest(v, field(value, "release_digest")); digest(v, field(value, "component_digest"));
    digest(v, field(value, "contract_digest")); digest(v, field(value, "state_schema"));
    check(v, number(field(value, "route_generation")) != 0);
}
static void retention(tx_validator *v, tx_value value) {
    if (!has(value)) return;
    id(v, field(value, "record_format")); check(v, number(field(value, "record_version")) != 0);
    tx_value ids = field(value, "required_record_ids");
    for (size_t index = 0; index < ids.count; ++index) id(v, item(ids, index));
}
static void unique_ids(tx_validator *v, tx_value ids) {
    for (size_t index = 0; index < ids.count; ++index) {
        id(v, item(ids, index));
        for (size_t previous = 0; previous < index; ++previous) check(v, !equal(item(ids, previous), item(ids, index)));
    }
}
static void result(tx_validator *v, tx_value value, bool technical, bool rejected) {
    if (technical) {
        id(v, field(value, "code")); string_value(v, field(value, "message"), 1024, false, false);
        const char *known[] = {"unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied",
            "unauthenticated", "invalid-argument", "not-found", "already-exists", "incompatible-contract", "state-conflict",
            "dependency-failed", "guest-trap", "corrupt-artifact", "route-unavailable", "admission-rejected", "internal"};
        bool found = false;
        for (size_t index = 0; index < sizeof(known) / sizeof(known[0]); ++index)
            found = found || lsf_text_equal(text(field(value, "code")), (latent_string){known[index], strlen(known[index])});
        if (!found && v->valid) lsf_unsupported(v->call, "platform_error.code", text(field(value, "code")));
        check(v, found);
        tx_value details = field(value, "detail_items"); check(v, details.count <= 16);
        if (details.count <= 16) for (size_t index = 0; index < details.count; ++index) {
            id(v, field(item(details, index), "kind")); metadata(v, field(item(details, index), "fields"), false);
        }
        return;
    }
    bytes(v, field(value, "payload"), 1048576, false); media(v, field(value, "media_type")); metadata(v, field(value, "metadata"), false);
    if (rejected) { id(v, field(value, "code")); string_value(v, field(value, "message"), 4096, false, false); }
    else { optional_id(v, field(value, "committed_state_version")); unique_ids(v, field(value, "effect_ids")); }
}
static void command(tx_validator *v, tx_value value, tx_value selected) {
    tx_value key = field(value, "key");
    namespace_value(v, field(key, "namespace"), text(field(field(selected, "namespace"), "tenant")));
    identity(v, field(key, "recovery_scope")); identity(v, field(key, "operation")); identity(v, field(key, "client_key"));
    if (has(field(key, "entity"))) identity(v, field(key, "entity"));
    const char *parts[] = {"namespace", "operation", "entity", "client_key"};
    for (size_t index = 0; index < 4; ++index) check(v, equal(field(key, parts[index]), field(selected, parts[index])));
    int32_t outcome = enumeration(v, field(value, "outcome"), 7, "command.outcome");
    bool known = outcome != 5 && outcome != 6;
    if (known || text(field(value, "command_id")).length != 0) id(v, field(value, "command_id"));
    if (known || text(field(value, "attempt_id")).length != 0) id(v, field(value, "attempt_id"));
    bytes(v, field(value, "fingerprint_sha256"), 32, known);
    check(v, !known || data(field(value, "fingerprint_sha256")).length == 32);
    if (known || has(field(value, "source"))) source(v, field(value, "source"));
    retention(v, field(value, "retention"));
    bool success = has(field(value, "success")), rejected = has(field(value, "business_rejection")), technical = has(field(value, "technical_failure"));
    unsigned results = (unsigned)success + (unsigned)rejected + (unsigned)technical; check(v, results <= 1);
    if (success) result(v, field(value, "success"), false, false);
    if (rejected) result(v, field(value, "business_rejection"), false, true);
    if (technical) result(v, field(value, "technical_failure"), true, false);
    if (has(field(value, "cleanup_failure"))) result(v, field(value, "cleanup_failure"), true, false);
    tx_value commit = field(value, "commit"), abort = field(value, "proven_abort");
    if (has(commit)) {
        id(v, field(commit, "command_id")); id(v, field(commit, "attempt_id")); id(v, field(commit, "transaction_id")); id(v, field(commit, "receipt_id"));
        bytes(v, field(commit, "committed_version"), 256, true); source(v, field(commit, "source")); unique_ids(v, field(commit, "effect_ids"));
        check(v, equal(field(commit, "command_id"), field(value, "command_id")) && equal(field(commit, "attempt_id"), field(value, "attempt_id"))
            && equal(field(commit, "source"), field(value, "source")));
    }
    if (has(abort)) {
        fence(v, abort);
        check(v, equal(field(abort, "command_id"), field(value, "command_id")) && equal(field(abort, "attempt_id"), field(value, "attempt_id")));
    }
    bool durable = boolean(field(value, "metadata_durable")), committed = boolean(field(value, "application_state_committed"));
    tx_value retained = field(value, "retention"); bool omitted = results == 0 && has(retained) && !boolean(field(retained, "payload_available"));
    switch (outcome) {
        case 2: check(v, durable && committed && has(commit) && !has(abort) && (success || omitted)); break;
        case 3: check(v, durable && !committed && !has(commit) && !has(abort) && (rejected || omitted)); break;
        case 4: check(v, durable && !committed && !has(commit) && has(abort) && !success && !rejected); break;
        case 7: check(v, durable && !has(abort) && results == 0 && committed == has(commit)); break;
        default: check(v, !committed && !has(commit) && !has(abort) && results == 0); break;
    }
}
static void effect(tx_validator *v, tx_value value, tx_value expected) {
    id(v, field(value, "effect_id")); id(v, field(value, "command_id")); id(v, field(value, "command_attempt_id")); id(v, field(value, "provider_profile"));
    optional_id(v, field(value, "provider_receipt")); optional_id(v, field(value, "failure_code")); optional_id(v, field(value, "management_operation_receipt_id"));
    enumeration(v, field(value, "disposition"), 8, "effect.disposition"); check(v, equal(field(value, "effect_id"), expected));
    retention(v, field(value, "retention"));
}
static void page_response(tx_validator *v, tx_value value, tx_value request, size_t count) {
    check(v, has(value) && number(field(value, "returned_count")) == count && count <= number(field(request, "limit"))
        && number(field(value, "encoded_bytes")) <= 1048576);
    if (has(field(value, "next_cursor"))) {
        bytes(v, field(value, "next_cursor"), 256, true); check(v, !equal(field(value, "next_cursor"), field(request, "cursor")));
    }
}
static void view(tx_validator *v, tx_value value, tx_value expected) {
    namespace_value(v, field(value, "namespace"), text(field(expected, "tenant"))); check(v, equal(field(value, "namespace"), expected));
    bytes(v, field(value, "version"), 256, true); id(v, field(value, "state_schema"));
}
static void invocation_response(tx_validator *v, tx_value value, tx_value origin, tx_value activation) {
    source(v, origin); id(v, field(value, "activation_id")); check(v, has(field(value, "consumption")));
    if (has(activation)) check(v, equal(field(value, "activation_id"), activation));
    check(v, equal(field(value, "publication_id"), field(origin, "publication_id")) && equal(field(value, "revision_id"), field(origin, "revision_id"))
        && equal(field(value, "release_digest"), field(origin, "component_digest")) && equal(field(value, "route_generation"), field(origin, "route_generation")));
    bool success = has(field(value, "success")), declared = has(field(value, "declared_error")), technical = has(field(value, "platform_failure"));
    check(v, (unsigned)success + (unsigned)declared + (unsigned)technical == 1);
    if (success) result(v, field(value, "success"), false, false);
    if (declared) result(v, field(value, "declared_error"), false, true);
    if (technical) result(v, field(value, "platform_failure"), true, false);
}
static void receipt(tx_validator *v, tx_value value, tx_value request, bool lifecycle) {
    tx_value target = field(field(request, "namespace"), "namespace"), actual = field(value, "namespace");
    namespace_value(v, actual, text(field(target, "tenant"))); id(v, field(value, "operation_id")); id(v, field(value, "receipt_id"));
    id(v, field(value, "authenticated_operator")); check(v, equal(field(value, "operation_id"), field(request, "operation_id")));
    int32_t disposition = enumeration(v, field(value, "disposition"), 5, "state.disposition");
    if (lifecycle) {
        check(v, equal(field(actual, "namespace"), field(target, "namespace"))); id(v, field(value, "state_schema"));
        enumeration(v, field(value, "status"), 4, "namespace.status"); enumeration(v, field(value, "mutation"), 5, "namespace.mutation");
        check(v, disposition != 1 || number(field(value, "after_generation")) != 0);
    } else {
        check(v, equal(actual, target)); bytes(v, field(value, "before_version"), 256, true); bytes(v, field(value, "after_version"), 256, true);
        digest(v, field(value, "policy_digest")); enumeration(v, field(value, "mutation"), 4, "state.mutation"); optional_id(v, field(value, "record_id"));
    }
}
static void dispatcher_receipt(tx_validator *v, tx_value value, tx_value original) {
    id(v, field(value, "operation_id")); id(v, field(value, "receipt_id")); id(v, field(value, "authenticated_operator")); id(v, field(value, "actor_tenant"));
    int32_t action = enumeration(v, field(value, "action"), 2, "dispatcher.action");
    int32_t disposition = enumeration(v, field(value, "disposition"), 5, "dispatcher.disposition");
    tx_value before = field(value, "before_generation"), after = field(value, "after_generation"); generation(v, before); generation(v, after);
    uint64_t revision = number(field(before, "revision"));
    check(v, equal(field(value, "operation_id"), field(original, "operation_id")) && equal(field(value, "action"), field(original, "action"))
        && equal(before, field(original, "expected_generation")) && disposition == 1 && revision != UINT64_MAX
        && number(field(before, "owner_epoch")) == number(field(after, "owner_epoch")) && number(field(after, "revision")) == revision + 1);
    if (action == 2) check(v, boolean(field(value, "clock_continuity_proven")) && !boolean(field(value, "restore_review_required")));
}

bool lsf_transaction_response_valid(latent_profile_call *call) {
    tx_value value = object(lsf_rpcs[call->operation].response, &call->result);
    tx_value request = object(lsf_rpcs[call->operation].request, call->transaction_original);
    size_t nodes = LSF_MAX_ELEMENTS, total = 0;
    if (!has(request) || !graph(value, 0, &nodes, &total)) return false;
    tx_validator v = {call, true};
    switch (call->operation) {
        case LSF_TX_invoke_command: {
            tx_value cmd = field(value, "command"), invoked = field(value, "invocation"); command(&v, cmd, field(request, "command"));
            invocation_response(&v, invoked, field(cmd, "source"), field(field(request, "invocation"), "activation_id"));
            const char *left[] = {"success", "business_rejection", "technical_failure"};
            const char *right[] = {"success", "declared_error", "platform_failure"};
            for (size_t index = 0; index < 3; ++index) if (has(field(cmd, left[index]))) check(&v, equal(field(cmd, left[index]), field(invoked, right[index])));
            check(&v, has(field(cmd, "success")) || has(field(cmd, "business_rejection")) || has(field(cmd, "technical_failure")) || has(field(invoked, "platform_failure")));
            break;
        }
        case LSF_TX_lookup_command:
            command(&v, field(value, "command"), field(request, "command"));
            if (has(field(request, "attempt_id"))) check(&v, equal(field(field(value, "command"), "attempt_id"), field(request, "attempt_id")));
            break;
        case LSF_TX_lookup_commit:
            command(&v, field(value, "command"), field(request, "command"));
            check(&v, equal(field(field(field(value, "command"), "commit"), "receipt_id"), field(request, "receipt_id"))); break;
        case LSF_TX_get_effect: effect(&v, field(value, "effect"), field(request, "effect_id")); break;
        case LSF_TX_list_effect_history: {
            tx_value entries = field(value, "receipts");
            for (size_t index = 0; index < entries.count; ++index) effect(&v, item(entries, index), field(field(request, "effect"), "effect_id"));
            page_response(&v, field(value, "page"), field(request, "page"), entries.count); break;
        }
        case LSF_TX_cancel_command: {
            int32_t disposition = enumeration(&v, field(value, "disposition"), 5, "command.cancel.disposition");
            tx_value cmd = field(value, "command");
            if (has(cmd)) { command(&v, cmd, field(field(request, "command"), "command"));
                check(&v, disposition != 2 || enumeration(&v, field(cmd, "outcome"), 7, "command.outcome") == 2); }
            else check(&v, disposition == 4);
            break;
        }
        case LSF_TX_query:
            view(&v, field(value, "view"), field(request, "namespace"));
            invocation_response(&v, field(value, "invocation"), field(value, "source"), field(field(request, "invocation"), "activation_id")); break;
        case LSF_TX_inspect_namespace: {
            tx_value inspected = field(value, "namespace"); view(&v, field(inspected, "view"), field(request, "namespace"));
            enumeration(&v, field(inspected, "status"), 4, "namespace.status"); check(&v, number(field(inspected, "generation")) != 0);
            quota(&v, field(inspected, "quota")); id(&v, field(inspected, "engine_profile")); digest(&v, field(inspected, "engine_profile_digest"));
            tx_value formats = field(inspected, "retained_formats");
            for (size_t index = 0; index < formats.count; ++index) retention(&v, item(formats, index));
            break;
        }
        case LSF_TX_select_entity: {
            tx_value entries = field(value, "entities");
            for (size_t index = 0; index < entries.count; ++index) {
                identity(&v, field(item(entries, index), "entity")); bytes(&v, field(item(entries, index), "version"), 256, true);
                for (size_t previous = 0; previous < index; ++previous)
                    check(&v, !equal(field(item(entries, previous), "entity"), field(item(entries, index), "entity")));
            }
            page_response(&v, field(value, "page"), field(request, "page"), entries.count); break;
        }
        case LSF_TX_mutate_state: {
            tx_value observed = field(value, "receipt"); receipt(&v, observed, request, false);
            check(&v, equal(field(observed, "mutation"), field(request, "mutation")) && equal(field(observed, "record_id"), field(request, "record_id"))
                && equal(field(observed, "before_version"), field(request, "expected_version")) && equal(field(observed, "policy_digest"), field(request, "expected_policy_digest")));
            break;
        }
        case LSF_TX_mutate_namespace: {
            tx_value observed = field(value, "receipt"); receipt(&v, observed, request, true);
            int32_t mutation = enumeration(&v, field(request, "mutation"), 5, "namespace.mutation");
            check(&v, equal(field(observed, "mutation"), field(request, "mutation")));
            check(&v, mutation == 1 ? !has(field(observed, "before_generation")) : equal(field(observed, "before_generation"), field(request, "expected_generation")));
            if (enumeration(&v, field(observed, "disposition"), 5, "state.disposition") == 1) {
                uint64_t before = number(field(request, "expected_generation")), inc = 0, after_inc = 0;
                check(&v, before != UINT64_MAX && number(field(observed, "after_generation")) == before + 1);
                tx_value target = field(field(request, "namespace"), "namespace");
                check(&v, latent_profile_parse_u64(text(field(target, "incarnation")), &inc)
                    && latent_profile_parse_u64(text(field(field(observed, "namespace"), "incarnation")), &after_inc)
                    && (mutation != 5 || inc != UINT64_MAX) && after_inc == inc + (mutation == 5 ? 1u : 0u));
                int32_t status = mutation == 1 || mutation == 5 ? 1 : mutation;
                check(&v, enumeration(&v, field(observed, "status"), 4, "namespace.status") == status);
                if (has(field(request, "configuration"))) check(&v, equal(field(observed, "state_schema"), field(field(request, "configuration"), "state_schema")));
            }
            break;
        }
        case LSF_TX_get_state_operation_receipt:
            check(&v, has(field(value, "receipt")) != has(field(value, "namespace_receipt")));
            if (has(field(value, "receipt"))) receipt(&v, field(value, "receipt"), request, false);
            else receipt(&v, field(value, "namespace_receipt"), request, true);
            break;
        case LSF_TX_inspect_dispatcher: {
            tx_value snapshot = field(value, "dispatcher"); generation(&v, field(snapshot, "generation"));
            enumeration(&v, field(snapshot, "failure"), 7, "dispatcher.failure");
            check(&v, !(boolean(field(snapshot, "pending_control")) || boolean(field(snapshot, "restore_review_required"))) || boolean(field(snapshot, "paused"))); break;
        }
        case LSF_TX_control_dispatcher:
            dispatcher_receipt(&v, field(value, "receipt"), request);
            check(&v, !(boolean(field(value, "replayed")) && boolean(field(value, "published"))));
            check(&v, enumeration(&v, field(request, "action"), 2, "dispatcher.action") != 1 || !boolean(field(value, "published")) || boolean(field(value, "paused"))); break;
        case LSF_TX_get_dispatcher_operation: dispatcher_receipt(&v, field(value, "receipt"), field(request, "original")); break;
        default: check(&v, false); break;
    }
    if (!v.valid) return false;
    /* A validated primary receipt is independent of its subsequent audit ack. */
    memset(&call->transaction_observed, 0, sizeof(call->transaction_observed));
    tx_value cmd = field(value, "command");
    if (has(cmd) && cmd.message != NULL && strcmp(cmd.message->name, "latent.transaction.v1.CommandInspection") == 0) {
        call->transaction_observed.has_command = true;
        call->transaction_observed.command = *(const latent_transaction_command_inspection *)cmd.data;
        latent_transaction_command_inspection *copy = &call->transaction_observed.command;
        copy->has_success = copy->has_business_rejection = copy->has_technical_failure = copy->has_cleanup_failure = false;
        memset(&copy->success, 0, sizeof(copy->success)); memset(&copy->business_rejection, 0, sizeof(copy->business_rejection));
        memset(&copy->technical_failure, 0, sizeof(copy->technical_failure)); memset(&copy->cleanup_failure, 0, sizeof(copy->cleanup_failure));
        call->transaction_identity.has_command_id = copy->command_id.length != 0; call->transaction_identity.command_id = copy->command_id;
        call->transaction_identity.has_attempt_id = copy->attempt_id.length != 0; call->transaction_identity.attempt_id = copy->attempt_id;
        call->transaction_identity.fingerprint_sha256 = copy->fingerprint_sha256;
        if (copy->has_commit) { call->transaction_identity.has_receipt_id = true; call->transaction_identity.receipt_id = copy->commit.receipt_id; }
        call->transaction_known = copy->outcome != 5 && copy->outcome != 6;
    }
    tx_value observed = field(value, "receipt");
    if (has(observed)) {
        const char *name = observed.message->name;
        if (strcmp(name, "latent.control.v1.StateOperationReceipt") == 0) call->transaction_observed.state = (const void *)observed.data;
        if (strcmp(name, "latent.control.v1.NamespaceOperationReceipt") == 0) call->transaction_observed.namespace = (const void *)observed.data;
        if (strcmp(name, "latent.control.v1.DispatcherOperationReceipt") == 0) call->transaction_observed.dispatcher = (const void *)observed.data;
        call->transaction_identity.has_receipt_id = true; call->transaction_identity.receipt_id = text(field(observed, "receipt_id"));
        call->transaction_known = true;
    }
    tx_value lifecycle = field(value, "namespace_receipt");
    if (has(lifecycle)) { call->transaction_observed.namespace = (const void *)lifecycle.data; call->transaction_known = true;
        call->transaction_identity.has_receipt_id = true; call->transaction_identity.receipt_id = text(field(lifecycle, "receipt_id")); }
    tx_value observed_effect = field(value, "effect");
    if (has(observed_effect)) { call->transaction_observed.effect = (const void *)observed_effect.data; call->transaction_known = true; }
    call->metadata.outcome = call->transaction_known ? LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED : LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN;
    if (has(field(value, "audit_ack"))) enumeration(&v, field(field(value, "audit_ack"), "status"), 4, "audit.status");
    if (call->metadata.has_audit_ack && (call->metadata.audit_ack.status == 1 || call->metadata.audit_ack.status == 2))
        check(&v, call->metadata.has_audit_attempt_sequence && call->metadata.audit_attempt_sequence != 0);
    check(&v, !call->transaction_audit_invalid);
    return v.valid;
}

static void recovery(latent_profile_call *call, tx_value request) {
    latent_transaction_recovery_identity *out = &call->transaction_identity;
    memset(out, 0, sizeof(*out));
    tx_value base = request, inspect_request = {0}, command_value = {0}, ns = {0}, original = {0};
    switch (call->operation) {
        case LSF_TX_invoke_command: command_value = field(request, "command"); break;
        case LSF_TX_query: ns = field(request, "namespace"); break;
        case LSF_TX_lookup_command: case LSF_TX_lookup_commit: case LSF_TX_get_effect: command_value = field(request, "command"); break;
        case LSF_TX_list_effect_history: base = field(request, "effect"); command_value = field(base, "command"); break;
        case LSF_TX_cancel_command: base = field(request, "command"); command_value = field(base, "command"); break;
        case LSF_TX_inspect_namespace: inspect_request = request; break;
        case LSF_TX_mutate_namespace: case LSF_TX_select_entity: case LSF_TX_mutate_state: case LSF_TX_get_state_operation_receipt:
            inspect_request = field(request, "namespace"); break;
        case LSF_TX_control_dispatcher: original = request; break;
        case LSF_TX_get_dispatcher_operation: original = field(request, "original"); break;
        default: break;
    }
    if (has(command_value)) { out->command = (const void *)command_value.data; ns = field(command_value, "namespace"); }
    if (has(inspect_request)) { ns = field(inspect_request, "namespace"); out->authorization_publication = (const void *)field(inspect_request, "authorization_publication").data; }
    else out->authorization_publication = (const void *)field(base, "authorization_publication").data;
    out->namespace = (const void *)ns.data;
#define TX_RECOVERY_STRING(member, value) do { tx_value selected = value; out->has_##member = has(selected); out->member = text(selected); } while (0)
    TX_RECOVERY_STRING(activation_id, field(field(request, "invocation"), "activation_id"));
    TX_RECOVERY_STRING(operation_id, field(has(original) ? original : request, "operation_id"));
    TX_RECOVERY_STRING(attempt_id, field(base, "attempt_id")); TX_RECOVERY_STRING(receipt_id, field(request, "receipt_id"));
    TX_RECOVERY_STRING(effect_id, field(base, "effect_id"));
    tx_value retry = field(request, "retry_attempt"); TX_RECOVERY_STRING(retry_request_id, field(retry, "request_id"));
#undef TX_RECOVERY_STRING
    out->expected_abort = (const void *)field(retry, "expected_abort").data;
    tx_value versions = field(request, "expected_versions"); out->expected_versions = (const void *)versions.data; out->expected_versions_count = versions.count;
    out->has_expected_generation = has(field(request, "expected_generation")); out->expected_generation = number(field(request, "expected_generation"));
    out->has_expected_version = has(field(request, "expected_version")); out->expected_version = data(field(request, "expected_version"));
    out->has_expected_policy_digest = has(field(request, "expected_policy_digest")); out->expected_policy_digest = text(field(request, "expected_policy_digest"));
    if (has(original)) {
        out->has_dispatcher_action = has(field(original, "action"));
        out->dispatcher_action = out->has_dispatcher_action ? *(const int32_t *)field(original, "action").data : 0;
        out->dispatcher_expected_generation = (const void *)field(original, "expected_generation").data;
    }
}
void lsf_transaction_identity(latent_profile_call *call, const void *request) {
    recovery(call, object(lsf_rpcs[call->operation].request, request));
}
bool lsf_transaction_snapshot(latent_profile_call *call) {
    const lsf_message *message = lsf_rpcs[call->operation].request;
    call->transaction_original = lsf_arena_allocate(&call->arena, message->native_size);
    bool limit = false;
    if (call->transaction_original == NULL || !lsf_decode(message, call->request + 5, call->request_length - 5,
        call->transaction_original, &call->arena, call->deadline, &limit)) return false;
    lsf_transaction_identity(call, call->transaction_original);
    return true;
}
