/* Explicit host doubles for the generated HTTP binding. Not guest evidence. */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stddef.h>

typedef struct { uint8_t *ptr; size_t len; } probe_string_t, probe_list_u8_t;
typedef struct { uint8_t tag; } http_error;
typedef int latent_http_streaming_method_t;
enum { LATENT_HTTP_STREAMING_METHOD_GET, LATENT_HTTP_STREAMING_METHOD_HEAD,
       LATENT_HTTP_STREAMING_METHOD_POST, LATENT_HTTP_STREAMING_METHOD_PUT,
       LATENT_HTTP_STREAMING_METHOD_PATCH, LATENT_HTTP_STREAMING_METHOD_DELETE,
       LATENT_HTTP_STREAMING_METHOD_OPTIONS };
enum { LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_URL, LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_REQUEST,
       LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED, LATENT_HTTP_STREAMING_HTTP_ERROR_REQUEST_TOO_LARGE,
       LATENT_HTTP_STREAMING_HTTP_ERROR_RESPONSE_TOO_LARGE, LATENT_HTTP_STREAMING_HTTP_ERROR_DEADLINE_EXCEEDED,
       LATENT_HTTP_STREAMING_HTTP_ERROR_CANCELLED, LATENT_HTTP_STREAMING_HTTP_ERROR_BUDGET_EXHAUSTED,
       LATENT_HTTP_STREAMING_HTTP_ERROR_DNS_FAILED, LATENT_HTTP_STREAMING_HTTP_ERROR_TLS_FAILED,
       LATENT_HTTP_STREAMING_HTTP_ERROR_CONNECTION_FAILED, LATENT_HTTP_STREAMING_HTTP_ERROR_UNAVAILABLE,
       LATENT_HTTP_STREAMING_HTTP_ERROR_UNCERTAIN, LATENT_HTTP_STREAMING_HTTP_ERROR_UNSUPPORTED_ENCODING };
typedef struct { probe_string_t name, value; } latent_http_streaming_header_t;
typedef struct { latent_http_streaming_header_t *ptr; size_t len; } latent_http_streaming_list_header_t;
typedef struct { bool is_some; uint64_t val; } optional_u64;
typedef struct { bool is_some; probe_string_t val; } optional_string;
typedef struct { int method; latent_http_streaming_list_header_t headers; probe_string_t url;
                 optional_u64 body_length, timeout_millis; optional_string body_media_type; } latent_http_streaming_request_t;
typedef struct { uint16_t status; latent_http_streaming_list_header_t headers; int body;
                 optional_string body_media_type; } response;
typedef struct { bool is_some; int val; } optional_chunk;
typedef struct { bool is_err; union { int ok; http_error err; } val; } latent_http_streaming_result_own_upload_http_error_t;
typedef struct { bool is_err; union { response ok; http_error err; } val; } latent_http_streaming_result_response_http_error_t;
typedef struct { bool is_err; union { optional_chunk ok; http_error err; } val; } latent_http_streaming_result_option_own_chunk_http_error_t;
typedef struct { bool is_err; union { probe_list_u8_t ok; http_error err; } val; } latent_http_streaming_result_list_u8_http_error_t;
typedef struct { bool is_err; union { http_error err; } val; } latent_http_streaming_result_void_http_error_t;
typedef struct { bool owned; int value; } lsf_upload_t, lsf_body_t, lsf_http_chunk_t;
#define LSF_LITERAL(s) {(uint8_t *)(s), sizeof(s)-1}
#define OWNER_OPS(prefix) \
 static inline void prefix##_adopt(prefix##_t *p, int value) { p->owned=true; p->value=value; } \
 static inline int prefix##_borrow(prefix##_t *p) { return p->value; } \
 static inline int prefix##_move(prefix##_t *p) { p->owned=false; return p->value; } \
 static inline void prefix##_close(prefix##_t *p) { p->owned=false; }
OWNER_OPS(lsf_upload)
OWNER_OPS(lsf_body)
OWNER_OPS(lsf_http_chunk)
static inline void probe_list_u8_free(probe_list_u8_t *p) { free(p->ptr); }
static inline void lsf_streaming_metadata_close(response *r) {
    for (size_t i=0; i<r->headers.len; i++) { free(r->headers.ptr[i].name.ptr); free(r->headers.ptr[i].value.ptr); }
    free(r->headers.ptr); free(r->body_media_type.is_some ? r->body_media_type.val.ptr : NULL);
}
bool latent_http_streaming_open(const latent_http_streaming_request_t *, int *, http_error *);
bool latent_http_streaming_write(int, const probe_list_u8_t *, http_error *);
bool latent_http_streaming_finish(int, response *, http_error *);
bool latent_http_streaming_read(int, uint32_t, optional_chunk *, http_error *);
bool latent_http_streaming_chunk_bytes(int, probe_list_u8_t *, http_error *);
bool latent_http_streaming_abort_body(int, http_error *);
