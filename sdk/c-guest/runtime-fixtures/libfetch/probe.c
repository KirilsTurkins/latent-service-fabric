/* SPDX-License-Identifier: Apache-2.0 */
/* Only ordinary libfetch/stdio/pthreads; no application transport callbacks. */
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <threads.h>
#include <fetch.h>
#include "probe.h"

typedef struct { const char *url; uint32_t bytes, checksum; int failed; } transfer;
static transfer held, sibling;
static atomic_int entered, returned, completed;

static int consume(FILE *file, transfer *value, int first_read) {
    unsigned char bytes[64];
    size_t size;
    if (first_read) {
        /* No intervening yield/import: fresh read-only FILE enters its read. */
        atomic_store(&entered, 1);
        size = fread(bytes, 1, sizeof(bytes), file);
        atomic_store(&returned, 1);
    } else size = fread(bytes, 1, 7, file);
    do {
        if (size > 65536u - value->bytes) { value->failed = 1; break; }
        value->bytes += (uint32_t)size;
        for (size_t i = 0; i < size; ++i) value->checksum = value->checksum * 33u + bytes[i];
    } while ((size = fread(bytes, 1, 7, file)) != 0);
    const int failed = ferror(file) != 0;
    const int closed = fclose(file);
    return value->failed || failed || closed != 0;
}

static void *held_read(void *unused) {
    (void)unused;
    FILE *file = fetchGetURL(held.url, "A");
    if (!file) { held.failed = 1; atomic_store(&returned, 1); return NULL; }
    held.failed = consume(file, &held, 1);
    return NULL;
}

static void *sibling_read(void *unused) {
    (void)unused;
    while (!atomic_load(&entered) && !atomic_load(&returned)) thrd_yield();
    if (atomic_load(&returned)) { sibling.failed = 1; return NULL; }
    FILE *file = fetchGetURL(sibling.url, "A");
    if (!file) { sibling.failed = 1; return NULL; }
    sibling.failed = consume(file, &sibling, 0);
    if (sibling.failed || atomic_load(&returned)) { sibling.failed = 1; return NULL; }
    atomic_store(&completed, 1);
    /* Third ordinary request is sent only after B's full read AND fclose. */
    file = fetchGetURL(sibling.url, "A");
    if (!file) { sibling.failed = 1; return NULL; }
    if (fclose(file) != 0) sibling.failed = 1;
    return NULL;
}

bool exports_tests_libfetch_api_run(probe_string_t *input, probe_string_t *result,
                                    probe_string_t *error) {
    if (!input->len || input->len > 8192 || memchr(input->ptr, 0, input->len)) {
        probe_string_dup(error, "invalid-input"); probe_string_free(input); return false;
    }
    char *copy = malloc(input->len + 1);
    if (!copy) { probe_string_dup(error, "input-memory"); probe_string_free(input); return false; }
    memcpy(copy, input->ptr, input->len); copy[input->len] = 0; probe_string_free(input);
    char *url = strchr(copy, '\n');
    if (!url) { free(copy); probe_string_dup(error, "invalid-input"); return false; }
    *url++ = 0;
    char text[128];
    if (!strcmp(copy, "sibling")) {
        char *second = strchr(url, '\n');
        if (!second) { free(copy); probe_string_dup(error, "invalid-input"); return false; }
        *second++ = 0;
        held = (transfer){.url = url}; sibling = (transfer){.url = second};
        atomic_store(&entered, 0); atomic_store(&returned, 0); atomic_store(&completed, 0);
        pthread_t a, b;
        int made_a = pthread_create(&a, NULL, held_read, NULL);
        int made_b = made_a ? -1 : pthread_create(&b, NULL, sibling_read, NULL);
        int joined_a = made_a ? -1 : pthread_join(a, NULL);
        int joined_b = made_b ? -1 : pthread_join(b, NULL);
        if (made_a || made_b || joined_a || joined_b) {
            /* Unknown child lifetime: keep its input until original Store retirement. */
            probe_string_dup(error, "thread-lifetime-refused"); return false;
        }
        free(copy);
        if (held.failed || sibling.failed || !atomic_load(&entered) ||
            !atomic_load(&returned) || !atomic_load(&completed)) {
            probe_string_dup(error, "sibling-failed"); return false;
        }
        snprintf(text, sizeof(text), "%u:%u:%u:%u:1:1:1", held.bytes, held.checksum,
                 sibling.bytes, sibling.checksum);
        probe_string_dup(result, text); return true;
    }
    FILE *file = fetchGetURL(url, "A");
    if (!file) {
        int code = fetchLastErrCode, saved = errno;
        const char *reason = !strcmp(copy, "not-found") && code == FETCH_UNAVAIL && saved == ENOENT
            ? "unavailable" : !strcmp(copy, "denied") && code == FETCH_AUTH && saved == EACCES
            ? "permission-denied" : "unexpected-open-error";
        free(copy); probe_string_dup(error, reason); return false;
    }
    if (!strcmp(copy, "early-close")) {
        free(copy);
        if (fclose(file) != 0) { probe_string_dup(error, "close-failed"); return false; }
        probe_string_dup(result, "closed"); return true;
    }
    const int normal = !strcmp(copy, "normal"); free(copy);
    transfer value = {0};
    if (consume(file, &value, 0) || !normal) {
        probe_string_dup(error, "read-failed"); return false;
    }
    snprintf(text, sizeof(text), "%u:%u", value.bytes, value.checksum);
    probe_string_dup(result, text); return true;
}
