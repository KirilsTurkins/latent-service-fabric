/* SPDX-License-Identifier: Apache-2.0 */
/* Ordinary public libfetch/stdio only; no transport callback or SDK HTTP call. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fetch.h>
#include "probe.h"

static const char body[] = "ordinary-post:value=42";
static const char media[] = "text/plain; charset=utf-8";

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
    const int normal = !strcmp(copy, "fresh-get");
    const int echo = !strcmp(copy, "post-echo");
    const int uncertain = !strcmp(copy, "post-uncertain");
    const int cancelled = !strcmp(copy, "post-cancel");
    if (!normal && !echo && !uncertain && !cancelled) {
        free(copy); probe_string_dup(error, "invalid-input"); return false;
    }
    struct url *parsed = fetchParseURL(url);
    FILE *file = parsed ? (normal ? fetchGetHTTP(parsed, "A") :
        fetchReqHTTP(parsed, "POST", "A", media, body)) : NULL;
    const int saved_errno = errno, saved_code = fetchLastErrCode;
    if (parsed) fetchFreeURL(parsed);
    free(copy);
    if (!file) {
        probe_string_dup(error, uncertain && saved_errno == EIO && saved_code == FETCH_UNKNOWN
            ? "uncertain" : "unexpected-open-error");
        return false;
    }
    if (uncertain || cancelled) {
        fclose(file); probe_string_dup(error, "unexpected-success"); return false;
    }
    unsigned char bytes[7];
    uint32_t count = 0, checksum = 0;
    size_t size;
    while ((size = fread(bytes, 1, sizeof(bytes), file)) != 0) {
        if (size > 65536u - count) {
            fclose(file); probe_string_dup(error, "response-bound"); return false;
        }
        count += (uint32_t)size;
        for (size_t i = 0; i < size; ++i) checksum = checksum * 33u + bytes[i];
    }
    const int failed = ferror(file) != 0;
    const int closed = fclose(file);
    if (failed || closed) { probe_string_dup(error, "read-or-close-error"); return false; }
    char text[64];
    snprintf(text, sizeof(text), "%u:%u", count, checksum);
    probe_string_dup(result, text); return true;
}
