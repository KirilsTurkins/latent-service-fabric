/* SPDX-License-Identifier: Apache-2.0 */
/* Maintained source backend for the finite libfetch HTTP profile. It calls
 * typed HTTP operations, never an emulated socket or application transport.
 * Generated C calls use the existing pinned --async=-all synchronous ABI.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fetch.h>
#include "lsf/streaming.h"
#include "common.h"

#define LSF_FETCH_URL_BYTES 8192u
#define LSF_FETCH_BODY_BYTES 65536u
#define LSF_FETCH_READ_BYTES 4096u

struct response_stream {
    lsf_body_t body;
    bool eof;
    bool failed;
    int saved_errno;
    int saved_fetch_code;
    char saved_error[MAXERRSTRING];
};

static void failure(int code, int error, const char *message) {
    fetchLastErrCode = code;
    snprintf(fetchLastErrString, MAXERRSTRING, "%s", message);
    errno = error;
}

void fetch_seterr(struct fetcherr *errors, int number) {
    while (errors->num != -1 && errors->num != number) ++errors;
    fetchLastErrCode = errors->cat;
    snprintf(fetchLastErrString, MAXERRSTRING, "%s", errors->string);
}

void fetch_syserr(void) {
    const int error = errno;
    failure(error == ENOMEM ? FETCH_MEMORY : FETCH_UNKNOWN, error, "C runtime failure");
}

static void unsupported(void) {
    failure(FETCH_PROTO, ENOTSUP, "Operation outside the selected libfetch HTTP profile");
}

static void http_failure(uint8_t tag) {
    switch (tag) {
    case LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_URL:
        failure(FETCH_URL, EINVAL, "Invalid HTTP URL"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_REQUEST:
        failure(FETCH_PROTO, EINVAL, "Invalid HTTP request"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED:
        failure(FETCH_AUTH, EACCES, "HTTP permission denied"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_REQUEST_TOO_LARGE:
    case LATENT_HTTP_STREAMING_HTTP_ERROR_RESPONSE_TOO_LARGE:
        failure(FETCH_FULL, EFBIG, "HTTP transfer exceeds its bound"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_DEADLINE_EXCEEDED:
        failure(FETCH_TIMEOUT, ETIMEDOUT, "HTTP deadline exceeded"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_CANCELLED:
        failure(FETCH_ABORT, ECANCELED, "HTTP call cancelled"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_BUDGET_EXHAUSTED:
        failure(FETCH_MEMORY, ENOMEM, "HTTP budget exhausted"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_DNS_FAILED:
        failure(FETCH_RESOLV, EHOSTUNREACH, "HTTP destination resolution failed"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_TLS_FAILED:
        failure(FETCH_AUTH, EACCES, "HTTP TLS validation failed"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_CONNECTION_FAILED:
        failure(FETCH_NETWORK, ECONNREFUSED, "HTTP connection failed"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_UNAVAILABLE:
        failure(FETCH_DOWN, EHOSTUNREACH, "HTTP provider unavailable"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_UNCERTAIN:
        failure(FETCH_UNKNOWN, EIO, "HTTP completion uncertain; no retry"); break;
    case LATENT_HTTP_STREAMING_HTTP_ERROR_UNSUPPORTED_ENCODING:
        failure(FETCH_PROTO, ENOTSUP, "Unsupported HTTP content encoding"); break;
    default:
        failure(FETCH_PROTO, EIO, "Invalid or incomplete HTTP transfer"); break;
    }
}

static ssize_t response_read(void *object, char *destination, size_t length) {
    struct response_stream *stream = object;
    if (!length) return 0;
    if (stream->failed) {
        fetchLastErrCode = stream->saved_fetch_code;
        memcpy(fetchLastErrString, stream->saved_error, MAXERRSTRING);
        errno = stream->saved_errno; return -1;
    }
    if (stream->eof) return 0;
    const uint32_t maximum = length < LSF_FETCH_READ_BYTES ? (uint32_t)length : LSF_FETCH_READ_BYTES;
    latent_http_streaming_result_option_own_chunk_http_error_t result = {0};
    result.is_err = !latent_http_streaming_read(lsf_body_borrow(&stream->body), maximum,
                                                &result.val.ok, &result.val.err);
    if (result.is_err) {
        http_failure(result.val.err.tag);
        goto failed;
    }
    if (!result.val.ok.is_some) { stream->eof = true; return 0; }
    lsf_http_chunk_t chunk = {0};
    lsf_http_chunk_adopt(&chunk, result.val.ok.val);
    latent_http_streaming_result_list_u8_http_error_t bytes = {0};
    bytes.is_err = !latent_http_streaming_chunk_bytes(lsf_http_chunk_borrow(&chunk),
                                                    &bytes.val.ok, &bytes.val.err);
    if (bytes.is_err) {
        lsf_http_chunk_close(&chunk);
        http_failure(bytes.val.err.tag);
        goto failed;
    }
    const size_t count = bytes.val.ok.len;
    if (!count || count > maximum) {
        probe_list_u8_free(&bytes.val.ok);
        lsf_http_chunk_close(&chunk);
        failure(FETCH_PROTO, EIO, "Invalid HTTP chunk; EOF was not observed");
        goto failed;
    }
    memcpy(destination, bytes.val.ok.ptr, count);
    probe_list_u8_free(&bytes.val.ok);
    lsf_http_chunk_close(&chunk);
    return (ssize_t)count;
failed:
    stream->failed = true;
    stream->saved_errno = errno;
    stream->saved_fetch_code = fetchLastErrCode;
    memcpy(stream->saved_error, fetchLastErrString, MAXERRSTRING);
    return -1;
}

static int response_close(void *object) {
    struct response_stream *stream = object;
    int result = 0;
    if (stream->body.owned) {
        latent_http_streaming_result_void_http_error_t closed = {0};
        /* Consume only this original body. Error/uncertainty does not restore
         * the handle or certify that the peer rolled back the request. */
        closed.is_err = !latent_http_streaming_abort_body(lsf_body_move(&stream->body), &closed.val.err);
        if (closed.is_err) { http_failure(closed.val.err.tag); result = -1; }
    }
    if (stream->failed) {
        fetchLastErrCode = stream->saved_fetch_code;
        memcpy(fetchLastErrString, stream->saved_error, MAXERRSTRING);
        errno = stream->saved_errno;
    }
    const int error = errno;
    free(stream);
    /* fclose still owns and frees FILE/BUFSIZ AFTER this callback. Guest
     * linear memory stays charged to its original Store; no Root refund. */
    errno = error;
    return result;
}

static char *request_url(const struct url *url) {
    if (!url || (strcmp(url->scheme, SCHEME_HTTP) && strcmp(url->scheme, SCHEME_HTTPS)) ||
        !url->host[0] || url->user[0] || url->pwd[0] || url->netrcfd != -1 ||
        url->ims_time || !url->doc || url->doc[0] != '/' ||
        url->port < 0 || url->port > 65535) {
        unsupported(); return NULL;
    }
    const size_t document = strnlen(url->doc, LSF_FETCH_URL_BYTES + 1);
    const size_t host = strnlen(url->host, sizeof(url->host));
    const size_t scheme = strlen(url->scheme);
    if (document > LSF_FETCH_URL_BYTES || host == sizeof(url->host) ||
        document + host + scheme + 10 > LSF_FETCH_URL_BYTES) {
        failure(FETCH_URL, ENAMETOOLONG, "HTTP URL exceeds its bound"); return NULL;
    }
    /* Host and document are separate libfetch fields. Do not let a URL
     * component delimiter in the host change the requested document. */
    if (memchr(url->host, '/', host) || memchr(url->host, '?', host) ||
        memchr(url->host, '#', host) || memchr(url->host, '@', host) ||
        memchr(url->host, '\\', host)) {
        failure(FETCH_URL, EINVAL, "Invalid constructed HTTP host"); return NULL;
    }
    /* A literal fragment is client-side only. Keep encoded %23 and queries
     * intact, without modifying the caller's original parsed URL. */
    const char *fragment = memchr(url->doc, '#', document);
    const size_t path = fragment ? (size_t)(fragment - url->doc) : document;
    char *text = malloc(path + host + scheme + 11);
    if (!text) { fetch_syserr(); return NULL; }
    if (url->port) snprintf(text, path + host + scheme + 11, "%s://%s:%d%.*s", url->scheme, url->host, url->port, (int)path, url->doc);
    else snprintf(text, path + host + scheme + 11, "%s://%s%.*s", url->scheme, url->host, (int)path, url->doc);
    return text;
}

/* Keep the upstream libfetch categories for actual HTTP errors.
 * This does not retry a request or change the profile's existing errno values. */
static int http_status_category(uint16_t status) {
    switch (status) {
    case 400: case 405: case 406: case 411: case 413: case 414: case 415:
    case 501: case 505:
        return FETCH_PROTO;
    case 402: case 407:
        return FETCH_AUTH;
    case 408: case 504:
        return FETCH_TIMEOUT;
    case 409:
        return FETCH_EXISTS;
    case 416:
        return FETCH_UNAVAIL;
    case 503:
        return FETCH_TEMP;
    default:
        return FETCH_SERVER;
    }
}

static bool content_length(const latent_http_streaming_list_header_t *headers, size_t *length, bool *known) {
    bool found = false;
    *length = SIZE_MAX; /* The original libfetch unknown-length sentinel. */
    *known = false;
    for (size_t i = 0; i < headers->len; ++i) {
        const latent_http_streaming_header_t *header = &headers->ptr[i];
        static const char name[] = "content-length";
        if (header->name.len != sizeof(name) - 1) continue;
        bool match = true;
        for (size_t at = 0; at < sizeof(name) - 1; ++at) {
            uint8_t value = header->name.ptr[at];
            if (value >= 'A' && value <= 'Z') value += 'a' - 'A';
            if (value != (uint8_t)name[at]) match = false;
        }
        if (!match) continue;
        if (found || !header->value.len) return false;
        found = true;
        size_t value = 0;
        for (size_t at = 0; at < header->value.len; ++at) {
            uint8_t digit = header->value.ptr[at];
            if (digit < '0' || digit > '9' || value > (SIZE_MAX - (digit - '0')) / 10) return false;
            value = value * 10 + digit - '0';
        }
        *length = value;
    }
    *known = found;
    return true;
}

/* A resumed GET accepts one bounded byte range, never a multipart response.
 * Parse without temporary allocation and reject values outside the selected
 * wasm32 size_t / signed 64-bit off_t representation. */
static bool range_number(const uint8_t **cursor, const uint8_t *end, uint64_t *number) {
    if (*cursor == end || **cursor < '0' || **cursor > '9') return false;
    uint64_t value = 0;
    do {
        uint8_t digit = **cursor - '0';
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
        ++*cursor;
    } while (*cursor != end && **cursor >= '0' && **cursor <= '9');
    *number = value;
    return true;
}

static bool content_range(const latent_http_streaming_list_header_t *headers,
                          off_t *first, size_t *length, off_t *total) {
    bool found = false;
    for (size_t i = 0; i < headers->len; ++i) {
        const latent_http_streaming_header_t *header = &headers->ptr[i];
        static const char name[] = "content-range";
        if (header->name.len != sizeof(name) - 1) continue;
        bool match = true;
        for (size_t at = 0; at < sizeof(name) - 1; ++at) {
            uint8_t value = header->name.ptr[at];
            if (value >= 'A' && value <= 'Z') value += 'a' - 'A';
            if (value != (uint8_t)name[at]) match = false;
        }
        if (!match) continue;
        if (found || header->value.len < 8) return false;
        found = true;
        const uint8_t *cursor = header->value.ptr, *end = cursor + header->value.len;
        for (size_t at = 0; at < 5; ++at) {
            uint8_t value = cursor[at];
            if (value >= 'A' && value <= 'Z') value += 'a' - 'A';
            if (value != (uint8_t)"bytes"[at]) return false;
        }
        if (cursor[5] != ' ') return false;
        cursor += 6;
        uint64_t start, last, complete;
        if (!range_number(&cursor, end, &start) || cursor == end || *cursor++ != '-'
            || !range_number(&cursor, end, &last) || cursor == end || *cursor++ != '/'
            || start > last || last > INT64_MAX || last - start >= SIZE_MAX) return false;
        if (cursor != end && *cursor == '*') {
            ++cursor;
            *total = (off_t)-1;
        } else {
            if (!range_number(&cursor, end, &complete) || complete > INT64_MAX
                || complete != last + 1) return false;
            *total = (off_t)complete;
        }
        if (cursor != end) return false;
        *first = (off_t)start;
        *length = (size_t)(last - start + 1);
    }
    return found;
}

static FILE *request(struct url *url, struct url_stat *stat, const char *flags,
                     const char *method, const char *content_type, const char *body) {
    const off_t requested_offset = url ? url->offset : 0;
    if ((stat && strcmp(method, "GET") && strcmp(method, "HEAD")) ||
        fetchAuthMethod || fetchDebug || fetchTimeout < 0 ||
        (url && (requested_offset < 0 || (requested_offset > 0 && strcmp(method, "GET"))))) {
        unsupported(); return NULL;
    }
    if (flags) for (const char *flag = flags; *flag; ++flag)
        if (*flag != 'A') { unsupported(); return NULL; }
    latent_http_streaming_method_t operation;
    if (!strcmp(method, "GET")) operation = LATENT_HTTP_STREAMING_METHOD_GET;
    else if (!strcmp(method, "HEAD")) operation = LATENT_HTTP_STREAMING_METHOD_HEAD;
    else if (!strcmp(method, "POST")) operation = LATENT_HTTP_STREAMING_METHOD_POST;
    else if (!strcmp(method, "PUT")) operation = LATENT_HTTP_STREAMING_METHOD_PUT;
    else if (!strcmp(method, "PATCH")) operation = LATENT_HTTP_STREAMING_METHOD_PATCH;
    else if (!strcmp(method, "DELETE")) operation = LATENT_HTTP_STREAMING_METHOD_DELETE;
    else if (!strcmp(method, "OPTIONS")) operation = LATENT_HTTP_STREAMING_METHOD_OPTIONS;
    else { unsupported(); return NULL; }
    const size_t body_length = body ? strnlen(body, LSF_FETCH_BODY_BYTES + 1) : 0;
    const size_t media_length = content_type ? strnlen(content_type, 257) : 0;
    if (body_length > LSF_FETCH_BODY_BYTES || media_length > 256) {
        failure(FETCH_FULL, EFBIG, "HTTP input exceeds its bound"); return NULL;
    }
    char *target = request_url(url);
    if (!target) return NULL;
    struct response_stream *stream = calloc(1, sizeof(*stream));
    if (!stream) { free(target); fetch_syserr(); return NULL; }
    const cookie_io_functions_t functions = {.read = response_read, .close = response_close};
    FILE *file = fopencookie(stream, "rb", functions);
    if (!file) { const int error = errno; free(stream); free(target); errno = error; fetch_syserr(); return NULL; }
    /* All guest-owned FILE backing exists before the first external effect. */
    latent_http_streaming_header_t headers[3] = {
        {.name = LSF_LITERAL("accept"), .value = LSF_LITERAL("*/*")},
        {.name = LSF_LITERAL("user-agent"), .value = LSF_LITERAL(_LIBFETCH_VER)},
    };
    size_t header_count = 2;
    char range_value[32];
    if (requested_offset > 0) {
        int written = snprintf(range_value, sizeof(range_value), "bytes=%lld-", (long long)requested_offset);
        if (written < 0 || (size_t)written >= sizeof(range_value)) {
            free(target);
            failure(FETCH_PROTO, EOVERFLOW, "HTTP range offset is unrepresentable"); goto fail_file;
        }
        headers[header_count++] = (latent_http_streaming_header_t){
            .name = LSF_LITERAL("range"), .value = {(uint8_t *)range_value, (size_t)written}};
    }
    latent_http_streaming_request_t metadata = {.method = operation,
        .headers = {headers, header_count},
        .url = {(uint8_t *)target, strlen(target)}, .body_length = {true, body_length},
        .timeout_millis = {fetchTimeout != 0, (uint64_t)fetchTimeout * 1000}};
    if (content_type) {
        metadata.body_media_type.is_some = true;
        metadata.body_media_type.val = (probe_string_t){(uint8_t *)content_type, media_length};
    }
    latent_http_streaming_result_own_upload_http_error_t opened = {0};
    opened.is_err = !latent_http_streaming_open(&metadata, &opened.val.ok, &opened.val.err);
    free(target);
    if (opened.is_err) { http_failure(opened.val.err.tag); goto fail_file; }
    lsf_upload_t upload = {0};
    lsf_upload_adopt(&upload, opened.val.ok);
    for (size_t offset = 0; offset < body_length;) {
        const size_t remaining = body_length - offset;
        const size_t count = remaining < LSF_FETCH_READ_BYTES ? remaining : LSF_FETCH_READ_BYTES;
        probe_list_u8_t bytes = {(uint8_t *)body + offset, count};
        latent_http_streaming_result_void_http_error_t written = {0};
        written.is_err = !latent_http_streaming_write(lsf_upload_borrow(&upload), &bytes, &written.val.err);
        if (written.is_err) {
            lsf_upload_close(&upload);
            http_failure(written.val.err.tag); goto fail_file;
        }
        offset += count;
    }
    latent_http_streaming_result_response_http_error_t completed = {0};
    completed.is_err = !latent_http_streaming_finish(lsf_upload_move(&upload),
                                                   &completed.val.ok, &completed.val.err);
    if (completed.is_err) { http_failure(completed.val.err.tag); goto fail_file; }
    lsf_body_adopt(&stream->body, completed.val.ok.body);
    const uint16_t status = completed.val.ok.status;
    size_t length;
    bool known_length;
    const bool valid_length = content_length(&completed.val.ok.headers, &length, &known_length);
    off_t actual_offset = 0, representation_size = known_length ? (off_t)length : (off_t)-1;
    size_t partial_length = length;
    bool valid_range = true;
    if (status == 206) {
        /* Subtract after ordering to avoid an overflowing range end. */
        valid_range = operation == LATENT_HTTP_STREAMING_METHOD_GET && requested_offset > 0 && known_length &&
            content_range(&completed.val.ok.headers, &actual_offset, &partial_length, &representation_size) &&
            actual_offset <= requested_offset &&
            (uint64_t)requested_offset - (uint64_t)actual_offset < (uint64_t)partial_length &&
            partial_length == length;
    }
    lsf_streaming_metadata_close(&completed.val.ok);
    if (!valid_length) {
        failure(FETCH_PROTO, EOVERFLOW, "HTTP content length is invalid or unrepresentable");
        goto fail_file;
    }
    if (status < 200 || status >= 300) {
        if (status >= 300 && status < 400) failure(FETCH_MOVED, ENOTSUP, "HTTP redirects are outside this profile");
        else if (status == 401 || status == 403) failure(FETCH_AUTH, EACCES, "HTTP authentication refused");
        else if (status == 404 || status == 410) failure(FETCH_UNAVAIL, ENOENT, "HTTP resource unavailable");
        else failure(http_status_category(status), EIO, "HTTP server returned an error response");
        snprintf(fetchLastErrString, MAXERRSTRING, "HTTP status %u%s", (unsigned)status,
                 status >= 300 && status < 400 ? ": redirects unsupported" : ": request failed");
        goto fail_file;
    }
    if (!valid_range) {
        failure(FETCH_PROTO, EIO, "Invalid or inconsistent HTTP content range");
        goto fail_file;
    }
    /* Servers may ignore Range and return 200; tell the caller its real start. */
    url->offset = actual_offset;
    url->length = partial_length;
    if (stat) {
        /* Selected wasm32 WASI size_t is 32-bit and off_t is signed 64-bit.
         * Keep a valid maximum-size header distinct from missing length.
         * This profile does not interpret Last-Modified; both times are the
         * original unknown sentinel, never a fabricated local clock value. */
        stat->size = representation_size;
        stat->atime = stat->mtime = 0;
    }
    return file;
fail_file:
    {
        const int error = errno, code = fetchLastErrCode;
        char message[MAXERRSTRING]; memcpy(message, fetchLastErrString, sizeof(message));
        /* Cleanup cannot replace the first declared HTTP/transport failure. */
        fclose(file);
        fetchLastErrCode = code; memcpy(fetchLastErrString, message, sizeof(message)); errno = error;
        return NULL;
    }
}

FILE *fetchXGetHTTP(struct url *url, struct url_stat *stat, const char *flags) { return request(url, stat, flags, "GET", NULL, NULL); }
FILE *fetchGetHTTP(struct url *url, const char *flags) { return fetchXGetHTTP(url, NULL, flags); }
FILE *fetchReqHTTP(struct url *url, const char *method, const char *flags, const char *type, const char *body) {
    if (!method) { failure(FETCH_PROTO, EINVAL, "HTTP method is required"); return NULL; }
    return request(url, NULL, flags, method, type, body);
}
FILE *fetchPutHTTP(struct url *url, const char *flags) { (void)url; (void)flags; unsupported(); return NULL; }
int fetchStatHTTP(struct url *url, struct url_stat *stat, const char *flags) {
    struct url_stat result;
    FILE *file = request(url, stat ? &result : NULL, flags, "HEAD", NULL, NULL);
    if (!file) return -1;
    /* The returned body is a real provider owner even for HEAD. Preserve an
     * abort failure and only publish metadata after it has been closed. */
    if (fclose(file) != 0) return -1;
    if (stat) *stat = result;
    return 0;
}
struct url_ent *fetchListHTTP(struct url *url, const char *flags) { (void)url; (void)flags; unsupported(); return NULL; }

/* The genuine frontend routes non-HTTP schemes here; no ambient filesystem,
 * FTP socket, fake successful open, or library-specific privileged provider. */
#define CLOSED_SCHEME(name) \
FILE *fetchXGet##name(struct url *url, struct url_stat *stat, const char *flags) { (void)url; (void)stat; (void)flags; unsupported(); return NULL; } \
FILE *fetchGet##name(struct url *url, const char *flags) { (void)url; (void)flags; unsupported(); return NULL; } \
FILE *fetchPut##name(struct url *url, const char *flags) { (void)url; (void)flags; unsupported(); return NULL; } \
int fetchStat##name(struct url *url, struct url_stat *stat, const char *flags) { (void)url; (void)stat; (void)flags; unsupported(); return -1; } \
struct url_ent *fetchList##name(struct url *url, const char *flags) { (void)url; (void)flags; unsupported(); return NULL; }
CLOSED_SCHEME(File)
CLOSED_SCHEME(FTP)
