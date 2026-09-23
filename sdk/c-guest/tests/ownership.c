/* SPDX-License-Identifier: Apache-2.0 */
/* Native sanitizer execution against freshly generated authoritative headers.
 * Imports below are test doubles, not an alternate production ABI. The real
 * admitted-component tests separately execute the actual provider boundary. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

struct allocation { void *pointer; size_t length; bool must_be_zero; };
static struct allocation allocations[1024];
static size_t live;
static bool fail_allocation;
static void *tracked_calloc(size_t count, size_t width) {
    if (fail_allocation) return NULL;
    void *value = calloc(count, width);
    assert(value && live < 1024);
    allocations[live++] = (struct allocation){value, count * width, false};
    return value;
}
static void tracked_free(void *value) {
    if (!value) return;
    size_t i = 0;
    while (i < live && allocations[i].pointer != value) ++i;
    assert(i < live); /* Unknown owner or double free. */
    if (allocations[i].must_be_zero)
        for (size_t j = 0; j < allocations[i].length; ++j)
            assert(((uint8_t *)value)[j] == 0);
    allocations[i] = allocations[--live];
    free(value);
}
#define calloc tracked_calloc
#define free tracked_free
#include "lsf/guest.h"
#include "lsf/async.h"
#include "lsf/http.h"
#include "lsf/streaming.h"
#include "lsf/blob.h"
#include "lsf/secrets.h"
#include "lsf/service.h"

void probe_string_free(probe_string_t *value) {
    if (value->len) tracked_free(value->ptr);
    *value = (probe_string_t){0};
}
static probe_string_t string(const char *text) {
    size_t length = strlen(text);
    uint8_t *data = tracked_calloc(length, 1);
    memcpy(data, text, length);
    return (probe_string_t){data, length};
}

static uint32_t dropped_resources;
#define RESOURCE_STUB(PREFIX, NAME) \
    PREFIX##_borrow_##NAME##_t PREFIX##_borrow_##NAME(PREFIX##_own_##NAME##_t value) { \
        return (PREFIX##_borrow_##NAME##_t){value.__handle}; \
    } \
    void PREFIX##_##NAME##_drop_own(PREFIX##_own_##NAME##_t value) { \
        assert(value.__handle > 0); ++dropped_resources; \
    }
RESOURCE_STUB(latent_http_streaming, upload)
RESOURCE_STUB(latent_http_streaming, body)
RESOURCE_STUB(latent_http_streaming, chunk)
RESOURCE_STUB(latent_blob_blob, chunk)

static void *context;
static uint32_t cancel_result, tasks_dropped, sets_dropped, joined;
probe_subtask_status_t probe_subtask_cancel(probe_subtask_t task) {
    assert(task == 9 && joined == 0); return cancel_result;
}
void probe_subtask_drop(probe_subtask_t task) {
    assert(task == 9 && joined == 0); ++tasks_dropped;
}
probe_waitable_set_t probe_waitable_set_new(void) { return 7; }
void probe_waitable_join(uint32_t task, probe_waitable_set_t set) {
    assert(task == 9 && (set == 0 || set == 7)); joined = set;
}
void probe_waitable_set_drop(probe_waitable_set_t set) {
    assert(set == 7 && joined == 0); ++sets_dropped;
}
void *probe_context_get_0(void) { return context; }
void probe_context_set_0(void *value) { context = value; }

static unsigned order[32], cleaned;
static void record_cleanup(void *value) { order[cleaned++] = *(unsigned *)value; }
static void scope_tests(void) {
    lsf_scope_t scope;
    lsf_scope_init(&scope, 8);
    assert(!lsf_scope_alloc(&scope, 0, 1));
    assert(!lsf_scope_alloc(&scope, SIZE_MAX, 2));
    void *a = lsf_scope_alloc(&scope, 8, 1);
    assert(a && scope.live == 8 && scope.peak == 8 && live == 1);
    assert(!lsf_scope_alloc(&scope, 1, 1));
    assert(!lsf_scope_adopt(&scope, a, 0, tracked_free));
    assert(lsf_scope_release(&scope, a));
    assert(!lsf_scope_release(&scope, a));
    assert(live == 0 && scope.live == 0);
    fail_allocation = true;
    assert(!lsf_scope_alloc(&scope, 1, 1) && scope.live == 0);
    fail_allocation = false;
    probe_string_t returned = {0};
    assert(lsf_string_copy(&scope, &returned, (const uint8_t *)"hello", 5));
    lsf_string_return(&scope, &returned);
    assert(live == 1 && scope.live == 0);
    lsf_scope_close(&scope);
    probe_string_free(&returned);
    unsigned values[33];
    for (unsigned i = 0; i < 33; ++i) values[i] = i;
    for (unsigned i = 0; i < 32; ++i)
        assert(lsf_scope_adopt(&scope, &values[i], 0, record_cleanup));
    assert(!lsf_scope_adopt(&scope, &values[32], 0, record_cleanup));
    lsf_scope_close(&scope);
    lsf_scope_close(&scope);
    assert(cleaned == 32 && live == 0);
    for (unsigned i = 0; i < 32; ++i) assert(order[i] == 31 - i);
    puts("PASS C scope: overflow, budget, allocation failure, transfer, LIFO, capacity, double-close");
}

static probe_list_tuple2_string_string_t metadata(void) {
    probe_tuple2_string_string_t *pair = tracked_calloc(1, sizeof(*pair));
    pair->f0 = string("name"); pair->f1 = string("value");
    return (probe_list_tuple2_string_string_t){pair, 1};
}
static void result_tests(void) {
    latent_http_client_response_t response = {0};
    response.headers.ptr = tracked_calloc(1, sizeof(*response.headers.ptr));
    response.headers.len = 1;
    response.headers.ptr[0].name = string("content-type");
    response.headers.ptr[0].value = string("text/plain");
    response.body.ptr = tracked_calloc(8, 1); response.body.len = 8;
    response.body_media_type.is_some = true; response.body_media_type.val = string("text/plain");
    lsf_http_response_close(&response);
    lsf_http_response_close(&response);
    assert(live == 0);
    lsf_secret_t secret = {.owned = true};
    secret.value.bytes.ptr = tracked_calloc(16, 1); secret.value.bytes.len = 16;
    memset(secret.value.bytes.ptr, 0x73, 16);
    allocations[live - 1].must_be_zero = true;
    secret.value.media_type = string("text/plain");
    secret.value.version.is_some = true; secret.value.version.val = string("version");
    assert(lsf_secret_borrow(&secret)->bytes.len == 16);
    lsf_secret_close(&secret); lsf_secret_close(&secret);
    assert(live == 0 && !secret.owned);
    latent_service_invoke_invocation_outcome_t outcome = {0};
    outcome.tag = LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_SUCCESS;
    outcome.val.success.payload.ptr = tracked_calloc(4, 1); outcome.val.success.payload.len = 4;
    outcome.val.success.media_type = string("application/json");
    outcome.val.success.metadata = metadata();
    lsf_service_outcome_close(&outcome);
    assert(live == 0);
    outcome.tag = LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_DECLARED_ERROR;
    outcome.val.declared_error.code = string("invalid");
    outcome.val.declared_error.message = string("invalid input");
    outcome.val.declared_error.payload.ptr = tracked_calloc(4, 1); outcome.val.declared_error.payload.len = 4;
    outcome.val.declared_error.media_type = string("application/json");
    outcome.val.declared_error.metadata = metadata();
    lsf_service_outcome_close(&outcome);
    assert(live == 0);
    outcome.tag = LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_PLATFORM_FAILURE;
    outcome.val.platform_failure.message = string("denied");
    outcome.val.platform_failure.details.ptr = tracked_calloc(1, sizeof(*outcome.val.platform_failure.details.ptr));
    outcome.val.platform_failure.details.len = 1;
    outcome.val.platform_failure.details.ptr[0].kind = string("policy");
    outcome.val.platform_failure.details.ptr[0].fields = metadata();
    lsf_service_outcome_close(&outcome); lsf_service_outcome_close(&outcome);
    assert(live == 0);
    puts("PASS C results: nested lists/options, all service outcomes, secrets wiped before free");
}

static void resource_tests(void) {
    lsf_upload_t upload = {0};
    lsf_upload_adopt(&upload, (latent_http_streaming_own_upload_t){1});
    assert(lsf_upload_borrow(&upload).__handle == 1);
    latent_http_streaming_own_upload_t consumed = lsf_upload_move(&upload);
    lsf_upload_close(&upload); assert(dropped_resources == 0);
    latent_http_streaming_upload_drop_own(consumed);
    lsf_body_t body = {0};
    lsf_body_adopt(&body, (latent_http_streaming_own_body_t){2});
    lsf_http_chunk_t chunk = {0};
    lsf_http_chunk_adopt(&chunk, (latent_http_streaming_own_chunk_t){3});
    lsf_body_close(&body); lsf_body_close(&body);
    assert(lsf_http_chunk_borrow(&chunk).__handle == 3);
    lsf_http_chunk_close(&chunk); lsf_http_chunk_close(&chunk);
    lsf_blob_chunk_t blob = {0};
    lsf_blob_chunk_adopt(&blob, (latent_blob_blob_own_chunk_t){4});
    assert(lsf_blob_chunk_borrow(&blob).__handle == 4);
    lsf_blob_chunk_close(&blob); lsf_blob_chunk_close(&blob);
    assert(dropped_resources == 4);
    puts("PASS C resources: exact move/drop and chunk ownership independent of parent");
}

static void async_tests(void) {
    lsf_async_t async = {0};
    assert(lsf_async_submit(&async, PROBE_SUBTASK_RETURNED) == LSF_ASYNC_RETURNED);
    lsf_async_close(&async);
    for (unsigned scenario = 0; scenario < 5; ++scenario) {
        unsigned frame = scenario;
        lsf_frame_enter(&frame);
        assert(lsf_async_submit(&async, (9 << 4) | PROBE_SUBTASK_STARTING) == LSF_ASYNC_PENDING);
        assert(lsf_async_wait(&async) == PROBE_CALLBACK_CODE_WAIT(7));
        probe_event_t event = {PROBE_EVENT_SUBTASK, 9, PROBE_SUBTASK_STARTED};
        assert(lsf_async_event(&async, &event) == LSF_ASYNC_PENDING);
        if (scenario == 0) {
            event.code = PROBE_SUBTASK_RETURNED;
            assert(lsf_async_event(&async, &event) == LSF_ASYNC_RETURNED);
        } else {
            cancel_result = scenario == 1 ? PROBE_SUBTASK_RETURNED :
                            scenario == 2 ? PROBE_SUBTASK_STARTED_CANCELLED : UINT32_MAX;
            event = (probe_event_t){PROBE_EVENT_CANCEL, 0, 0};
            lsf_async_result_t result = lsf_async_event(&async, &event);
            if (scenario <= 2) {
                assert(result == (scenario == 1 ? LSF_ASYNC_CANCELLED_RETURNED : LSF_ASYNC_CANCELLED));
            } else {
                assert(result == LSF_ASYNC_PENDING && context == &frame && async.task == 9);
                event = (probe_event_t){PROBE_EVENT_SUBTASK, 9,
                    scenario == 3 ? PROBE_SUBTASK_RETURNED : PROBE_SUBTASK_RETURNED_CANCELLED};
                assert(lsf_async_event(&async, &event) ==
                    (scenario == 3 ? LSF_ASYNC_CANCELLED_RETURNED : LSF_ASYNC_CANCELLED));
            }
        }
        lsf_async_close(&async); lsf_frame_leave(&frame);
        assert(tasks_dropped == scenario + 1 && sets_dropped == scenario + 1 && context == NULL);
    }
    puts("PASS C async: immediate, suspended, progress, cancellation and returned-result race");
}
int main(void) {
    scope_tests(); result_tests(); resource_tests(); async_tests();
    assert(live == 0 && context == NULL);
    puts("PASS C ownership: no retained allocations or activation context");
    return 0;
}
