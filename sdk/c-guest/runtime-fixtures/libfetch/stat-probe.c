/* SPDX-License-Identifier: Apache-2.0 */
/* Ordinary libfetch API only; the HTTP transport remains the SDK backend. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fetch.h>
#include "probe.h"

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
