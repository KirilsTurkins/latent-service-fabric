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
static const char *expected_url = "https://example.test/item";
static bool validate_url;
static char last_url[8193];

bool latent_http_streaming_open(const latent_http_streaming_request_t *request, int *out, http_error *error) {
    opens++;
    assert(request->method == expected_method && request->body_length.is_some && request->body_length.val == 0);
    assert(request->url.len < sizeof(last_url));
    memcpy(last_url, request->url.ptr, request->url.len);
    last_url[request->url.len] = 0;
    if (validate_url) {
        const char *authority = strstr(last_url, "://");
        assert(authority);
        const char *path = strchr(authority + 3, '/');
        const char *query = path ? strchr(path, '?') : NULL;
        const char *percent = path ? strchr(path, '%') : NULL;
        /* Model only the real provider's literal-fragment and encoded-path
         * rejection; percent escapes in a query remain unchanged. */
        if (strchr(last_url, '#') || (percent && (!query || percent < query))) {
            error->tag = LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_URL;
            return false;
        }
    }
    assert(!strcmp(last_url, expected_url));
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
    status = 200; deny = abort_failure = validate_url = false; length = NULL; errno = 0;
    expected_url = "https://example.test/item"; last_url[0] = 0;
}

static void constructed_url(const char *document, int port, const char *target, bool rejected) {
    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
    validate_url = true; expected_url = target;
    struct url *url = fetchMakeURL("https", "example.test", port, document, "", "");
    assert(url && !strcmp(url->doc, document));
    FILE *file = fetchXGet(url, NULL, "A");
    assert(!strcmp(last_url, target) && !strcmp(url->doc, document));
    if (rejected) {
        assert(!file && errno == EINVAL && fetchLastErrCode == FETCH_URL);
        assert(opens == 1 && finishes == 0 && aborts == 0);
    } else {
        assert(file && fclose(file) == 0);
        assert(opens == 1 && finishes == 1 && aborts == 1);
    }
    fetchFreeURL(url);
}

static void malformed_constructed_host(const char *host, const char *old_target) {
    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
    expected_url = old_target;
    struct url *url = fetchMakeURL("https", host, 0, "/item?document=1", "", "");
    assert(url && !strcmp(url->host, host) && !strcmp(url->doc, "/item?document=1"));
    FILE *file = fetchXGet(url, NULL, "A");
    assert(!file && errno == EINVAL && fetchLastErrCode == FETCH_URL);
    assert(opens == 0 && finishes == 0 && aborts == 0);
    assert(!strcmp(url->host, host) && !strcmp(url->doc, "/item?document=1"));
    fetchFreeURL(url);
}

static void valid_constructed_host(const char *host, int port, const char *target) {
    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
    expected_url = target;
    struct url *url = fetchMakeURL("https", host, port, "/item?document=1", "", "");
    assert(url && !strcmp(url->host, host));
    FILE *file = fetchXGet(url, NULL, "A");
    assert(file && fclose(file) == 0);
    assert(opens == 1 && finishes == 1 && aborts == 1);
    assert(!strcmp(last_url, target) && !strcmp(url->host, host) &&
           !strcmp(url->doc, "/item?document=1"));
    fetchFreeURL(url);
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

    /* The actual status is never retried or turned into a transport timeout.
     * Preserve the profile's existing errno while matching libfetch categories. */
    const struct { int status, category, error; } errors[] = {
        {400, FETCH_PROTO, EIO}, {401, FETCH_AUTH, EACCES},
        {402, FETCH_AUTH, EIO}, {403, FETCH_AUTH, EACCES},
        {404, FETCH_UNAVAIL, ENOENT}, {405, FETCH_PROTO, EIO},
        {406, FETCH_PROTO, EIO}, {407, FETCH_AUTH, EIO},
        {408, FETCH_TIMEOUT, EIO}, {409, FETCH_EXISTS, EIO},
        {410, FETCH_UNAVAIL, ENOENT}, {411, FETCH_PROTO, EIO},
        {412, FETCH_SERVER, EIO}, {413, FETCH_PROTO, EIO},
        {414, FETCH_PROTO, EIO}, {415, FETCH_PROTO, EIO},
        {416, FETCH_UNAVAIL, EIO}, {417, FETCH_SERVER, EIO},
        {418, FETCH_SERVER, EIO}, {500, FETCH_SERVER, EIO},
        {501, FETCH_PROTO, EIO}, {502, FETCH_SERVER, EIO},
        {503, FETCH_TEMP, EIO}, {504, FETCH_TIMEOUT, EIO},
        {505, FETCH_PROTO, EIO}, {599, FETCH_SERVER, EIO},
    };
    for (size_t index = 0; index < sizeof(errors) / sizeof(errors[0]); ++index) {
        reset();
        status = errors[index].status;
        /* An abort failure cannot replace the first actual HTTP outcome. */
        abort_failure = status == 503;
        assert(fetchStatURL(url, &stat, "A") == -1);
        assert(fetchLastErrCode == errors[index].category);
        assert(errno == errors[index].error);
        char expected_status[32];
        snprintf(expected_status, sizeof(expected_status), "HTTP status %d", status);
        assert(strstr(fetchLastErrString, expected_status));
        assert(opens == 1 && finishes == 1 && aborts == 1);

        /* Same frontend/port, fresh explicit request; no automatic replay. */
        status = 200; abort_failure = false;
        assert(fetchStatURL(url, &stat, "A") == 0);
        assert(opens == 2 && finishes == 2 && aborts == 2);
    }
    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
    status = 503; abort_failure = true;
    assert(!fetchXGetURL(url, &stat, "A"));
    assert(fetchLastErrCode == FETCH_TEMP && errno == EIO);
    assert(opens == 1 && finishes == 1 && aborts == 1);
    status = 200; abort_failure = false;
    FILE *after_error = fetchXGetURL(url, &stat, "A");
    assert(after_error && fclose(after_error) == 0);
    assert(opens == 2 && finishes == 2 && aborts == 2);

    malformed_constructed_host("example.test?changed=1",
                               "https://example.test?changed=1/item?document=1");
    malformed_constructed_host("example.test/other",
                               "https://example.test/other/item?document=1");
    malformed_constructed_host("example.test#local",
                               "https://example.test#local/item?document=1");
    malformed_constructed_host("a@example.test",
                               "https://a@example.test/item?document=1");
    malformed_constructed_host("example.test\\other",
                               "https://example.test\\other/item?document=1");
    valid_constructed_host("example.test", 8443,
                           "https://example.test:8443/item?document=1");
    valid_constructed_host("example.test:8443", 0,
                           "https://example.test:8443/item?document=1");
    valid_constructed_host("[::1]", 8443,
                           "https://[::1]:8443/item?document=1");
    valid_constructed_host("[::1]:8443", 0,
                           "https://[::1]:8443/item?document=1");
    valid_constructed_host("[2001:db8::1]", 0,
                           "https://[2001:db8::1]/item?document=1");

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
    constructed_url("/item?query=%23value#local", 0, "https://example.test/item?query=%23value", false);
    constructed_url("/item#", 0, "https://example.test/item", false);
    constructed_url("/item#local?ignored=1", 0, "https://example.test/item", false);
    constructed_url("/item?query=%23value", 0, "https://example.test/item?query=%23value", false);
    constructed_url("/item?query=%23value#local", 8443, "https://example.test:8443/item?query=%23value", false);
    constructed_url("/item%23encoded?query=%23value#local", 0,
                    "https://example.test/item%23encoded?query=%23value", true);

    /* The same existing provider denial remains authoritative after stripping. */
    reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
    validate_url = true; deny = true;
    struct url *denied = fetchMakeURL("https", "example.test", 0, "/item#local", "", "");
    assert(denied && !fetchXGet(denied, NULL, "A") && errno == EACCES && fetchLastErrCode == FETCH_AUTH);
    assert(opens == 1 && !strcmp(last_url, "https://example.test/item") && !strcmp(denied->doc, "/item#local"));
    fetchFreeURL(denied);
    constructed_url("/item#fresh", 0, "https://example.test/item", false);

    /* Both original full-document bounds still apply before fragment removal. */
    char long_document[8194];
    for (size_t i = 0; i < 2; ++i) {
        const size_t size = i ? 8193 : 8180;
        memset(long_document, 'a', size);
        long_document[0] = '/'; long_document[1] = '#'; long_document[size] = 0;
        reset(); expected_method = LATENT_HTTP_STREAMING_METHOD_GET;
        struct url *long_url = fetchMakeURL("https", "example.test", 0, long_document, "", "");
        assert(long_url && !strcmp(long_url->doc, long_document));
        assert(!fetchXGet(long_url, NULL, "A") && errno == ENAMETOOLONG && fetchLastErrCode == FETCH_URL);
        assert(opens == 0 && !strcmp(long_url->doc, long_document));
        fetchFreeURL(long_url);
    }
    puts("libfetch HEAD metadata, fragment and failure controls passed (fake HTTP port)");
}
