/* SPDX-License-Identifier: Apache-2.0 */
/* Ordinary libfetch API only; the HTTP transport remains the SDK backend. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fetch.h>
#include "probe.h"

static bool range_request(const char *mode, const char *text, probe_string_t *result,
                          probe_string_t *error) {
    struct url *url = fetchParseURL(text);
    if (!url) { probe_string_dup(error, "range-url"); return false; }
    url->offset = !strcmp(mode, "range-unsolicited") ? 0 : 5;
    struct url_stat stat;
    FILE *file = fetchXGet(url, &stat, "A");
    int saved = errno, code = fetchLastErrCode;
    if (!file) {
        fetchFreeURL(url);
        probe_string_dup(error, !strcmp(mode, "range-denied") && code == FETCH_AUTH && saved == EACCES
                                ? "permission-denied" :
            (!strcmp(mode, "range-unsolicited") || !strcmp(mode, "range-before")) && code == FETCH_PROTO &&
                !strcmp(fetchLastErrString, "Invalid or inconsistent HTTP content range")
                                ? "invalid-content-range" : "unexpected-range-error");
        return false;
    }
    if (strcmp(mode, "range") && strcmp(mode, "range-ignored")) {
        fclose(file); fetchFreeURL(url); probe_string_dup(error, "unexpected-range-success"); return false;
    }
    uint32_t checksum = 0;
    size_t count = 0;
    unsigned char bytes[256];
    for (;;) {
        size_t n = fread(bytes, 1, sizeof(bytes), file);
        if (count > 32768 - n) {
            fclose(file); fetchFreeURL(url); probe_string_dup(error, "range-body-limit"); return false;
        }
        count += n;
        for (size_t i = 0; i < n; ++i) checksum = checksum * 33u + bytes[i];
        if (n < sizeof(bytes)) break;
    }
    int failed = ferror(file);
    if (fclose(file) != 0) failed = 1;
    if (failed) {
        fetchFreeURL(url); probe_string_dup(error, "range-body-error"); return false;
    }
    char output[128];
    int written = snprintf(output, sizeof(output), "%lld:%zu:%lld:%zu:%u",
                           (long long)url->offset, url->length, (long long)stat.size,
                           count, (unsigned)checksum);
    fetchFreeURL(url);
    if (written < 0 || (size_t)written >= sizeof(output)) {
        probe_string_dup(error, "range-format"); return false;
    }
    probe_string_dup(result, output); return true;
}

bool exports_examples_libfetch_api_run(probe_string_t *input, probe_string_t *result,
                                      probe_string_t *error) {
    if (!input->len || input->len > 8192 || memchr(input->ptr, 0, input->len)) {
        probe_string_free(input); probe_string_dup(error, "invalid-input"); return false;
    }
    char *copy = malloc(input->len + 1);
    if (!copy) { probe_string_free(input); probe_string_dup(error, "input-memory"); return false; }
    memcpy(copy, input->ptr, input->len); copy[input->len] = 0; probe_string_free(input);
    char *url = strchr(copy, '\n');
    if (!url) { free(copy); probe_string_dup(error, "invalid-input"); return false; }
    *url++ = 0;
    if (!strncmp(copy, "range", 5)) {
        bool ok = range_request(copy, url, result, error);
        free(copy); return ok;
    }
    struct url_stat stat;
    int rc = fetchStatURL(url, &stat, "A");
    int saved = errno, code = fetchLastErrCode;
    if (rc != 0) {
        const char *message = !strcmp(copy, "denied") && code == FETCH_AUTH && saved == EACCES
            ? "permission-denied" : !strcmp(copy, "not-found") && code == FETCH_UNAVAIL && saved == ENOENT
            ? "unavailable" : "unexpected-stat-error";
        free(copy); probe_string_dup(error, message); return false;
    }
    if (strcmp(copy, "normal") && strcmp(copy, "fresh")) {
        free(copy); probe_string_dup(error, "unexpected-stat-success"); return false;
    }
    free(copy);
    char text[96];
    int written = snprintf(text, sizeof(text), "%lld:%lld:%lld", (long long)stat.size,
                           (long long)stat.atime, (long long)stat.mtime);
    if (written < 0 || (size_t)written >= sizeof(text)) {
        probe_string_dup(error, "stat-format"); return false;
    }
    probe_string_dup(result, text); return true;
}
