/* Execute the real libfetch frontend/backend with explicit fake HTTP ports. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <fetch.h>
#include "lsf/streaming.h"

static int opens, finishes, aborts, expected_method, status = 200;
static bool deny, abort_failure;
static const char *length;

bool latent_http_streaming_open(const latent_http_streaming_request_t *request, int *out, http_error *error) {
    opens++;
    assert(request->method == expected_method && request->body_length.is_some && request->body_length.val == 0);
    assert(request->url.len == strlen("https://example.test/item"));
    assert(!memcmp(request->url.ptr, "https://example.test/item", request->url.len));
    if (deny) { error->tag = LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED; return false; }
    *out = 17; return true;
}
bool latent_http_streaming_write(int upload, const probe_list_u8_t *bytes, http_error *error) {
    (void)upload; (void)bytes; (void)error; assert(!"unexpected write"); return false;
}
bool latent_http_streaming_finish(int upload, response *out, http_error *error) {
    (void)error; assert(upload == 17); finishes++;
    out->status = status; out->body = 23;
    if (length) {
        out->headers.ptr = calloc(1, sizeof(*out->headers.ptr)); assert(out->headers.ptr);
        out->headers.len = 1;
        out->headers.ptr[0].name.ptr = (uint8_t *)strdup("Content-Length");
        out->headers.ptr[0].name.len = strlen("Content-Length");
        out->headers.ptr[0].value.ptr = (uint8_t *)strdup(length);
        out->headers.ptr[0].value.len = strlen(length);
        assert(out->headers.ptr[0].name.ptr && out->headers.ptr[0].value.ptr);
    }
    return true;
}
bool latent_http_streaming_read(int body, uint32_t max, optional_chunk *out, http_error *error) {
    (void)body; (void)max; (void)error; out->is_some = false; return true;
}
bool latent_http_streaming_chunk_bytes(int chunk, probe_list_u8_t *out, http_error *error) {
    (void)chunk; (void)out; (void)error; assert(!"unexpected chunk"); return false;
}
bool latent_http_streaming_abort_body(int body, http_error *error) {
    assert(body == 23); aborts++;
    if (abort_failure) { error->tag = LATENT_HTTP_STREAMING_HTTP_ERROR_UNCERTAIN; return false; }
    return true;
}

static void reset(void) {
    opens = finishes = aborts = 0; expected_method = LATENT_HTTP_STREAMING_METHOD_HEAD;
    status = 200; deny = abort_failure = false; length = NULL; errno = 0;
}
int main(void) {
    const char *url = "https://example.test/item";
    struct url_stat stat;
    reset(); length = "12345";
    assert(fetchStatURL(url, &stat, "A") == 0);
    assert(stat.size == 12345 && stat.atime == 0 && stat.mtime == 0);
    assert(opens == 1 && finishes == 1 && aborts == 1);

    reset(); assert(fetchStatURL(url, &stat, "A") == 0);
    assert(stat.size == -1 && stat.atime == 0 && stat.mtime == 0 && aborts == 1);
    reset(); assert(fetchStatURL(url, NULL, "A") == 0 && aborts == 1);

    reset(); status = 404;
    assert(fetchStatURL(url, &stat, "A") == -1 && errno == ENOENT && fetchLastErrCode == FETCH_UNAVAIL);
    assert(opens == 1 && finishes == 1 && aborts == 1);
    reset(); length = "12x";
    assert(fetchStatURL(url, &stat, "A") == -1 && errno == EOVERFLOW && fetchLastErrCode == FETCH_PROTO);
    assert(opens == 1 && finishes == 1 && aborts == 1);
    reset(); deny = true;
    assert(fetchStatURL(url, &stat, "A") == -1 && errno == EACCES && fetchLastErrCode == FETCH_AUTH);
    assert(opens == 1 && finishes == 0 && aborts == 0);
    reset(); abort_failure = true; length = "9";
    assert(fetchStatURL(url, &stat, "A") == -1 && errno == EIO && fetchLastErrCode == FETCH_UNKNOWN);
    assert(stat.size == -1 && aborts == 1);
    reset(); assert(fetchStatURL(url, &stat, "unsupported") == -1 && errno == ENOTSUP && opens == 0);

    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET; length = "12";
    FILE *file = fetchXGetURL(url, &stat, "A");
    assert(file && stat.size == 12 && fclose(file) == 0 && aborts == 1);
    puts("libfetch HEAD metadata and failure controls passed (fake HTTP port)");
}
