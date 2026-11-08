/* Real maintained libfetch frontend/backend; HTTP ports are explicit doubles. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <fetch.h>
#include "lsf/streaming.h"

static const char *expected_range, *content_range, *content_length;
static const char *payload;
static struct url *rewrite_url;
static off_t offset_after_open;
static size_t position, chunk_length;
static int status, opens, aborts, reads;
static bool duplicate_range, denied;

bool latent_http_streaming_open(const latent_http_streaming_request_t *request, int *out, http_error *error) {
    opens++;
    assert(request->method == LATENT_HTTP_STREAMING_METHOD_GET);
    int found = 0;
    for (size_t i = 0; i < request->headers.len; ++i) {
        latent_http_streaming_header_t h = request->headers.ptr[i];
        if (h.name.len == 5 && !memcmp(h.name.ptr, "range", 5)) {
            found++;
            assert(expected_range && h.value.len == strlen(expected_range));
            assert(!memcmp(h.value.ptr, expected_range, h.value.len));
        }
    }
    assert(found == (expected_range != NULL));
    if (denied) { error->tag = LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED; return false; }
    *out = 17; return true;
}
bool latent_http_streaming_write(int upload, const probe_list_u8_t *bytes, http_error *error) {
    (void)upload; (void)bytes; (void)error; assert(!"unexpected write"); return false;
}
static void header(latent_http_streaming_header_t *out, const char *name, const char *value) {
    out->name.ptr = (uint8_t *)strdup(name); out->name.len = strlen(name);
    out->value.ptr = (uint8_t *)strdup(value); out->value.len = strlen(value);
    assert(out->name.ptr && out->value.ptr);
}
bool latent_http_streaming_finish(int upload, response *out, http_error *error) {
    (void)error; assert(upload == 17);
    if (rewrite_url) rewrite_url->offset = offset_after_open;
    out->status = status; out->body = 23;
    size_t count = (content_range != NULL) + (content_length != NULL) + duplicate_range;
    out->headers.ptr = calloc(count ? count : 1, sizeof(*out->headers.ptr));
    assert(out->headers.ptr); out->headers.len = count;
    size_t i = 0;
    if (content_range) header(&out->headers.ptr[i++], "Content-Range", content_range);
    if (content_length) header(&out->headers.ptr[i++], "Content-Length", content_length);
    if (duplicate_range) header(&out->headers.ptr[i++], "content-range", content_range);
    return true;
}
bool latent_http_streaming_read(int body, uint32_t max, optional_chunk *out, http_error *error) {
    (void)error; assert(body == 23); reads++;
    size_t left = payload ? strlen(payload) - position : 0;
    chunk_length = left < max ? left : max;
    out->is_some = chunk_length != 0; out->val = 31; return true;
}
bool latent_http_streaming_chunk_bytes(int chunk, probe_list_u8_t *out, http_error *error) {
    (void)error; assert(chunk == 31 && chunk_length);
    out->ptr = malloc(chunk_length); assert(out->ptr);
    memcpy(out->ptr, payload + position, chunk_length);
    out->len = chunk_length; position += chunk_length; return true;
}
bool latent_http_streaming_abort_body(int body, http_error *error) {
    (void)error; assert(body == 23); aborts++; return true;
}
static void reset(void) {
    expected_range = content_range = content_length = NULL;
    payload = NULL; position = chunk_length = 0;
    rewrite_url = NULL; offset_after_open = 0;
    status = 200; opens = aborts = reads = 0; duplicate_range = denied = false; errno = 0;
}
static struct url *url(off_t offset) {
    struct url *u = fetchParseURL("https://example.test/item");
    assert(u); u->offset = offset; return u;
}
static void succeeds(off_t requested, off_t actual, size_t partial, off_t size) {
    struct url *u = url(requested); struct url_stat st;
    FILE *f = fetchXGet(u, &st, "A");
    assert(f && u->offset == actual && u->length == partial && st.size == size);
    if (payload) {
        char bytes[64] = {0}; size_t n = strlen(payload);
        assert(n < sizeof(bytes) && fread(bytes, 1, n, f) == n);
        assert(!memcmp(bytes, payload, n));
    }
    assert(opens == 1 && fclose(f) == 0 && aborts == 1);
    fetchFreeURL(u);
}
static void refuses(off_t requested) {
    struct url *u = url(requested); struct url_stat st;
    FILE *f = fetchXGet(u, &st, "A");
    assert(!f && fetchLastErrCode == FETCH_PROTO && opens == 1 && aborts == 1 && reads == 0);
    assert(u->offset == requested); fetchFreeURL(u);
}
int main(void) {
    reset(); expected_range="bytes=10-"; status=206;
    content_range="ByTeS 10-13/14"; content_length="4"; payload="klmn"; succeeds(10,10,4,14);
    reset(); expected_range="bytes=10-"; content_length="100"; succeeds(10,0,100,100);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-99/*"; content_length="90"; succeeds(10,10,90,-1);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 5-99/100"; content_length="95"; succeeds(10,5,95,100);
    /* The returned interval may start earlier, but it must include byte 10. */
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 5-10/11"; content_length="6"; payload="fghijk"; succeeds(10,5,6,11);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 0-3/*"; content_length="4"; payload="abcd"; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 0-3/4"; content_length="4"; payload="abcd"; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 5-9/*"; content_length="5"; payload="fghij"; refuses(10);
    /* Near the signed offset limit, validate by subtraction rather than addition. */
    reset(); expected_range="bytes=9223372036854775807-"; status=206;
    content_range="bytes 9223372036854775806-9223372036854775807/*";
    content_length="2"; payload="xy"; succeeds((off_t)INT64_MAX,(off_t)(INT64_MAX-1),2,-1);
    reset(); expected_range="bytes=9223372036854775807-"; status=206;
    content_range="bytes 9223372036854775805-9223372036854775806/*";
    content_length="2"; payload="xy"; refuses((off_t)INT64_MAX);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 11-99/100"; content_length="89"; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-99/100"; content_length="89"; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-99/100"; content_length="90"; duplicate_range=true; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-99/100"; refuses(10);
    reset(); status=206; content_range="bytes 10-99/100"; content_length="90"; refuses(0);
    /* A server cannot turn an ordinary full GET into a partial success. */
    reset(); status=206; content_range="bytes 0-3/*"; content_length="4"; payload="abcd"; refuses(0);
    reset(); status=206; content_range="bytes 0-3/4"; content_length="4"; payload="abcd"; refuses(0);
    /* The offset sent in the request, not a later URL mutation, controls 206. */
    reset(); status=206; content_range="bytes 0-3/*"; content_length="4"; payload="abcd";
    struct url *changed=url(0); rewrite_url=changed; offset_after_open=10;
    struct url_stat changed_stat; FILE *changed_file=fetchXGet(changed, &changed_stat, "A");
    assert(!changed_file && fetchLastErrCode==FETCH_PROTO && opens==1 && aborts==1 && reads==0);
    assert(changed->offset==10); fetchFreeURL(changed);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-13/14"; content_length="4"; payload="klmn";
    changed=url(10); rewrite_url=changed; offset_after_open=0;
    changed_file=fetchXGet(changed, &changed_stat, "A");
    assert(changed_file && changed->offset==10 && changed->length==4 && changed_stat.size==14);
    char changed_bytes[4]; assert(fread(changed_bytes, 1, sizeof(changed_bytes), changed_file)==4);
    assert(!memcmp(changed_bytes, "klmn", 4));
    assert(opens==1 && fclose(changed_file)==0 && aborts==1); fetchFreeURL(changed);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-18446744073709551616/100"; content_length="90"; refuses(10);
    reset(); expected_range="bytes=10-"; status=206;
    content_range="bytes 10-99/99"; content_length="90"; refuses(10);
    reset(); expected_range="bytes=10-"; status=416;
    struct url *out_of_range=url(10);
    assert(!fetchGet(out_of_range,"A") && fetchLastErrCode==FETCH_SERVER && aborts==1);
    fetchFreeURL(out_of_range);
    reset(); expected_range="bytes=10-"; denied=true;
    struct url *u=url(10); assert(!fetchGet(u,"A") && errno==EACCES && opens==1 && aborts==0); fetchFreeURL(u);
    reset(); u=url(-1); assert(!fetchGet(u,"A") && errno==ENOTSUP && opens==0); fetchFreeURL(u);
    puts("libfetch Range/Content-Range source controls passed (fake HTTP ports)");
}
