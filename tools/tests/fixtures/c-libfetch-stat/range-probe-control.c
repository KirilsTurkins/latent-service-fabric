/* Execute the real signed-qualification guest source with fake HTTP imports. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <fetch.h>
#include "lsf/streaming.h"

static int status, aborts;
static bool deny;
static const char *payload;
static size_t position, chunk_length;

void probe_string_free(probe_string_t *value) { free(value->ptr); value->ptr = NULL; value->len = 0; }
void probe_string_dup(probe_string_t *value, const char *text) {
    value->ptr = (uint8_t *)strdup(text); assert(value->ptr); value->len = strlen(text);
}
bool exports_examples_libfetch_api_run(probe_string_t *, probe_string_t *, probe_string_t *);

bool latent_http_streaming_open(const latent_http_streaming_request_t *request, int *out, http_error *error) {
    bool found = false;
    assert(request->method == LATENT_HTTP_STREAMING_METHOD_GET);
    for (size_t i = 0; i < request->headers.len; ++i) {
        latent_http_streaming_header_t header = request->headers.ptr[i];
        if (header.name.len == 5 && !memcmp(header.name.ptr, "range", 5)) {
            assert(!found && header.value.len == 8 && !memcmp(header.value.ptr, "bytes=5-", 8));
            found = true;
        }
    }
    assert(found);
    if (deny) { error->tag = LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED; return false; }
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
    (void)error; assert(upload == 17); out->status = status; out->body = 23;
    out->headers.len = status == 206 ? 2 : 1;
    out->headers.ptr = calloc(out->headers.len, sizeof(*out->headers.ptr)); assert(out->headers.ptr);
    header(&out->headers.ptr[0], "Content-Length", status == 206 ? "5" : "10");
    if (status == 206) header(&out->headers.ptr[1], "Content-Range", "bytes 5-9/10");
    return true;
}
bool latent_http_streaming_read(int body, uint32_t maximum, optional_chunk *out, http_error *error) {
    (void)error; assert(body == 23); size_t left = strlen(payload) - position;
    chunk_length = left < maximum ? left : maximum; out->is_some = chunk_length != 0; out->val = 31;
    return true;
}
bool latent_http_streaming_chunk_bytes(int chunk, probe_list_u8_t *out, http_error *error) {
    (void)error; assert(chunk == 31 && chunk_length);
    out->ptr = malloc(chunk_length); assert(out->ptr); out->len = chunk_length;
    memcpy(out->ptr, payload + position, chunk_length); position += chunk_length; return true;
}
bool latent_http_streaming_abort_body(int body, http_error *error) {
    (void)error; assert(body == 23); ++aborts; return true;
}
static uint32_t checksum(const char *text) {
    uint32_t value = 0;
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) value = value * 33u + *p;
    return value;
}
static void call(const char *mode, const char *expected, bool succeeds) {
    char text[128]; snprintf(text, sizeof(text), "%s\nhttps://example.test/item", mode);
    probe_string_t input = {(uint8_t *)strdup(text), strlen(text)}, result = {0}, error = {0};
    assert(input.ptr);
    assert(exports_examples_libfetch_api_run(&input, &result, &error) == succeeds);
    probe_string_t *out = succeeds ? &result : &error;
    assert(out->len == strlen(expected) && !memcmp(out->ptr, expected, out->len));
    probe_string_free(&result); probe_string_free(&error);
}
int main(void) {
    char expected[128];
    status = 206; payload = "fghij"; position = aborts = 0; deny = false;
    snprintf(expected, sizeof(expected), "5:5:10:5:%u", (unsigned)checksum(payload));
    call("range", expected, true); assert(aborts == 1);
    status = 200; payload = "abcdefghij"; position = aborts = 0;
    snprintf(expected, sizeof(expected), "0:10:10:10:%u", (unsigned)checksum(payload));
    call("range-ignored", expected, true); assert(aborts == 1);
    deny = true; position = aborts = 0;
    call("range-denied", "permission-denied", false); assert(aborts == 0);
    puts("C signed Range fixture source controls passed (fake HTTP ports)");
}
