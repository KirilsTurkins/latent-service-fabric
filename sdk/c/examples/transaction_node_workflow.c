/* Actual bounded C SDK participant. Callback data is copied before retirement. */
#include "internal.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAXIMUM (2u * 1024u * 1024u)
typedef struct fixture {
    const char *directory;
    char id[65];
    lsf_operation operation;
    uint64_t deadline;
    unsigned callbacks;
    bool valid;
    uint8_t *output;
} fixture;

static bool path(char *output, size_t capacity, const char *directory, const char *id, const char *suffix) {
    int count = snprintf(output, capacity, "%s/%s%s", directory, id, suffix);
    return count > 0 && (size_t)count < capacity;
}
static bool read_file(const char *path_value, uint8_t *output, size_t maximum, size_t *length) {
    int fd = open(path_value, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return false;
    struct stat information;
    bool valid = fstat(fd, &information) == 0 && S_ISREG(information.st_mode) && information.st_uid == geteuid() &&
        (information.st_mode & 0077u) == 0 && information.st_size >= 0 && (uint64_t)information.st_size <= maximum;
    *length = 0;
    while (valid && *length <= maximum) {
        ssize_t count = read(fd, output + *length, maximum + 1u - *length);
        if (count == 0) break;
        if (count < 0) { valid = false; break; }
        *length += (size_t)count;
    }
    valid = valid && *length == (size_t)information.st_size && *length <= maximum;
    return close(fd) == 0 && valid;
}
static bool write_file(const char *path_value, const uint8_t *data, size_t length) {
    if (length > MAXIMUM) return false;
    int fd = open(path_value, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return false;
    size_t written = 0;
    while (written < length) {
        ssize_t count = write(fd, data + written, length - written);
        if (count <= 0) { close(fd); return false; }
        written += (size_t)count;
    }
    bool valid = fsync(fd) == 0;
    return close(fd) == 0 && valid;
}
static bool encoded(fixture *owner, const char *kind, const lsf_message *schema, const void *value) {
    char file[4096], suffix[40]; size_t length = 0; bool limit = false;
    int count = snprintf(suffix, sizeof(suffix), ".%s.pb", kind);
    return count > 0 && (size_t)count < sizeof(suffix) && path(file, sizeof(file), owner->directory, owner->id, suffix) &&
        lsf_encode(schema, value, owner->output, MAXIMUM, &length, owner->deadline, &limit) && write_file(file, owner->output, length);
}
static bool observations(fixture *owner, const latent_transaction_observed_outcome *value) {
    bool valid = true;
    if (value->has_command) valid = valid && encoded(owner, "command", &lsf_latent_transaction_v1_CommandInspection, &value->command);
    if (value->state != NULL) valid = valid && encoded(owner, "state", &lsf_latent_control_v1_StateOperationReceipt, value->state);
    if (value->namespace != NULL) valid = valid && encoded(owner, "namespace", &lsf_latent_control_v1_NamespaceOperationReceipt, value->namespace);
    if (value->effect != NULL) valid = valid && encoded(owner, "effect", &lsf_latent_transaction_v1_EffectReceipt, value->effect);
    if (value->dispatcher != NULL) valid = valid && encoded(owner, "dispatcher", &lsf_latent_control_v1_DispatcherOperationReceipt, value->dispatcher);
    if (value->effect_plan != NULL) valid = valid && encoded(owner, "effectPlan", &lsf_latent_control_v1_EffectManagementPlan, value->effect_plan);
    return valid;
}
static void result(fixture *owner, const void *value, const latent_transaction_response_metadata *metadata,
                   const latent_transaction_client_failure *failure) {
    if (++owner->callbacks != 1u) { owner->valid = false; return; }
    char file[4096], summary[256];
    bool valid = (value != NULL) != (failure != NULL);
    if (valid && value != NULL) valid = encoded(owner, "response", lsf_rpcs[owner->operation].response, value) && observations(owner, &metadata->observed);
    if (valid && failure != NULL) valid = observations(owner, &failure->observed);
    int count;
    if (failure == NULL) count = snprintf(summary, sizeof(summary), "{\"status\":\"response\"}");
    else {
        char grpc[32] = "null";
        if (failure->transport.has_grpc_status) snprintf(grpc, sizeof(grpc), "%d", (int)failure->transport.grpc_status);
        count = snprintf(summary, sizeof(summary), "{\"status\":\"failure\",\"failureCategory\":%d,\"grpcStatus\":%s,\"dispatched\":%s}",
            (int)failure->transport.category, grpc, failure->transport.dispatched ? "true" : "false");
    }
    owner->valid = valid && count > 0 && (size_t)count < sizeof(summary) && path(file, sizeof(file), owner->directory, owner->id, ".result.json") &&
        write_file(file, (uint8_t *)summary, (size_t)count);
}

#define CALLBACK(method, request, response) \
static void callback_##method(const latent_transaction_##method##_result *reply, const latent_transaction_client_failure *failure, void *context) { \
    result(context, reply == NULL ? NULL : &reply->value, reply == NULL ? NULL : &reply->metadata, failure); \
}
LATENT_TRANSACTION_METHODS(CALLBACK)
#undef CALLBACK

static bool identifier(const char *value) {
    size_t length = strlen(value); if (length < 1u || length > 64u) return false;
    for (size_t index = 0; index < length; index++) {
        char c = value[index]; if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) return false;
    }
    return true;
}
static int run(int argc, char **argv) {
    if (argc != 6 || strcmp(argv[1], "--node-fixture") != 0) return 1;
    struct stat directory;
    if (lstat(argv[5], &directory) != 0 || !S_ISDIR(directory.st_mode) || directory.st_uid != geteuid() || (directory.st_mode & 0077u) != 0) return 1;
    uint8_t token[257]; size_t token_length;
    if (!read_file(argv[4], token, 256u, &token_length)) return 1;
    latent_transport_config config = latent_transport_defaults();
    config.endpoint = (latent_string){argv[2], strlen(argv[2])}; config.tenant = (latent_string){argv[3], strlen(argv[3])};
    config.bearer_token = (latent_bytes){token, token_length}; config.timeout_millis = 5000u;
    config.maximum_request_bytes = MAXIMUM; config.maximum_response_bytes = MAXIMUM;
    latent_transport *transport = NULL; latent_profile_client_failure failure;
    bool created = latent_transport_create(&config, &transport, &failure); memset(token, 0, sizeof(token));
    if (!created) return 1;
    fixture owner = {.directory = argv[5], .valid = true, .output = malloc(MAXIMUM)};
    uint8_t *input = malloc(MAXIMUM + 1u);
    bool valid = owner.output != NULL && input != NULL;
    uint64_t deadline = lsf_now() + 120000u;
    char ids[32][65]; unsigned count = 0;
    if (valid) { puts("ready"); fflush(stdout); }
    char line[194];
    while (valid && fgets(line, sizeof(line), stdin) != NULL) {
        if (strcmp(line, "close\n") == 0) break;
        char method[64], id[65], extra; unsigned timeout; int cancellation;
        if (strchr(line, '\n') == NULL || strlen(line) > 193u || sscanf(line, "%63s %64s %u %d %c", method, id, &timeout, &cancellation, &extra) != 4 ||
            !identifier(id) || timeout < 1u || timeout > 5000u || cancellation < -1 || cancellation > 5000 || count >= 32u || lsf_now() >= deadline) { valid = false; break; }
        for (unsigned index = 0; index < count; index++) if (strcmp(ids[index], id) == 0) valid = false;
        if (!valid) break;
        strcpy(ids[count++], id);
        strcpy(owner.id, id);
        bool selected = false;
#define SELECT(method_name, request, response) if (strcmp(method, #method_name) == 0) { owner.operation = LSF_TX_##method_name; selected = true; }
        LATENT_TRANSACTION_METHODS(SELECT)
#undef SELECT
        char file[4096]; size_t length = 0; bool limit = false;
        owner.deadline = deadline;
        uint64_t call_deadline = deadline < lsf_now() + timeout ? deadline : lsf_now() + timeout;
        if (!selected || !path(file, sizeof(file), owner.directory, id, ".request.pb") || !read_file(file, input, MAXIMUM, &length)) { valid = false; break; }
        lsf_arena arena = {.owner = transport, .maximum = 8u * 1024u * 1024u};
        const lsf_message *schema = lsf_rpcs[owner.operation].request;
        void *request = lsf_arena_allocate(&arena, schema->native_size);
        valid = request != NULL && lsf_transaction_wire(schema, input, length, call_deadline, &limit) &&
            lsf_decode(schema, input, length, request, &arena, call_deadline, &limit) && lsf_now() < call_deadline;
        latent_profile_call *call = NULL;
        latent_profile_call_options options = {.has_timeout_millis = true, .timeout_millis = valid ? call_deadline - lsf_now() : 1u};
        owner.callbacks = 0u; owner.valid = true;
        if (valid) {
            const latent_transaction_client_vtable *api = latent_transport_transaction_vtable();
            latent_transaction_client *client = latent_transport_transaction(transport);
            switch (owner.operation) {
#define START(method_name, request_type, response_type) case LSF_TX_##method_name: call = api->method_name(client, request, &options, callback_##method_name, &owner); break;
                LATENT_TRANSACTION_METHODS(START)
#undef START
                default: valid = false; break;
            }
        }
        uint64_t cancel_at = cancellation < 0 ? UINT64_MAX : lsf_now() + (uint64_t)cancellation;
        bool cancelled = false;
        if (call == NULL) valid = false;
        while (valid && owner.callbacks == 0u && lsf_now() < deadline) {
            if (!cancelled && lsf_now() >= cancel_at) { latent_transport_transaction_vtable()->cancel_local(call); cancelled = true; }
            latent_transport_poll(transport, 10u);
        }
        if (call != NULL) latent_transport_transaction_vtable()->release_call(call);
        lsf_arena_clear(&arena);
        valid = valid && owner.valid && owner.callbacks == 1u;
        if (valid) { printf("done %s\n", id); fflush(stdout); }
    }
    bool shutdown = latent_transport_shutdown(transport, 5000u);
    latent_transport_usage usage = latent_transport_get_usage(transport);
    bool clean = shutdown && usage.stopped && usage.in_flight == 0u && usage.queued == 0u && usage.retained_calls == 0u &&
        usage.callbacks_pending == 0u && usage.sockets == 0u && usage.sessions == 0u;
    char file[4096], summary[256];
    int written = snprintf(summary, sizeof(summary), "{\"schemaVersion\":\"latent.sdk.transaction.node.cleanup.v1\",\"clean\":%s,\"callbacksPending\":%u,\"retainedCalls\":%u,\"sockets\":%u}",
        clean ? "true" : "false", usage.callbacks_pending, usage.retained_calls, usage.sockets);
    bool recorded = written > 0 && (size_t)written < sizeof(summary) && path(file, sizeof(file), owner.directory, "cleanup", ".json") && write_file(file, (uint8_t *)summary, (size_t)written);
    valid = valid && recorded;
    bool destroyed = latent_transport_destroy(transport);
    free(input); free(owner.output);
    return valid && clean && destroyed ? 0 : 1;
}
int main(int argc, char **argv) {
    int status = run(argc, argv); if (status != 0) fputs("transaction-node-workflow-failed\n", stderr); return status;
}
