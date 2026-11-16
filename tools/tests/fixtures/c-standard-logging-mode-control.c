/* Exercise the current signed fixture against the actual stdio adapter.
 * Only the log provider and unrelated libc entry points are finite doubles. */
#include "probe.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wasi/api.h>

FILE *const stdout = (FILE *)(uintptr_t)1;
FILE *const stderr = (FILE *)(uintptr_t)2;
int lsf_test_errno;
static unsigned accepted_records, accepted_bytes;

void *memcpy(void *out, const void *in, size_t size) {
    unsigned char *destination = out;
    const unsigned char *source = in;
    for (size_t i = 0; i < size; ++i) destination[i] = source[i];
    return out;
}
void *memset(void *out, int value, size_t size) {
    unsigned char *destination = out;
    for (size_t i = 0; i < size; ++i) destination[i] = (unsigned char)value;
    return out;
}
int setvbuf(FILE *stream, char *buffer, int mode, size_t size) {
    if ((stream != stdout && stream != stderr) || buffer || mode != _IONBF || size) __builtin_trap();
    return 0;
}
/* The fixture's initializer must run; its unrelated formatting is not this control. */
int printf(const char *restrict format, ...) { (void)format; return 1; }
int fprintf(FILE *restrict stream, const char *restrict format, ...) {
    (void)stream; (void)format; return 1;
}

bool latent_log_log_write(latent_log_log_level_t level, probe_string_t *message,
                          latent_log_log_list_field_t *fields, bool *accepted,
                          latent_log_log_log_error_t *error) {
    if (!message || !message->ptr || fields->len || level != LATENT_LOG_LOG_LEVEL_INFO) __builtin_trap();
    if (message->len > 256) {
        *error = (latent_log_log_log_error_t){.tag = LATENT_LOG_LOG_LOG_ERROR_INVALID_FIELD};
        return false;
    }
    if (message->len != 256) __builtin_trap();
    for (size_t i = 0; i < message->len; ++i) if (message->ptr[i] != 'a') __builtin_trap();
    ++accepted_records; accepted_bytes += (unsigned)message->len; *accepted = true;
    return true;
}
void latent_log_log_log_error_free(latent_log_log_log_error_t *error) {
    if (error->tag != LATENT_LOG_LOG_LOG_ERROR_INVALID_FIELD) __builtin_trap();
}

extern int32_t lsf_c_stdio_fd_write(int32_t,int32_t,int32_t,int32_t);
extern int32_t lsf_c_stdio_fd_seek(int32_t,int64_t,int32_t,int32_t);
extern int32_t lsf_c_stdio_fd_fdstat_get(int32_t,int32_t);
int32_t __imported_wasi_snapshot_preview1_fd_write(int32_t fd,int32_t vectors,int32_t count,int32_t written) {
    return lsf_c_stdio_fd_write(fd,vectors,count,written);
}
__wasi_errno_t __wasi_fd_write(__wasi_fd_t fd,const __wasi_ciovec_t *vectors,size_t count,__wasi_size_t *written) {
    return (__wasi_errno_t)lsf_c_stdio_fd_write((int32_t)fd,(int32_t)(uintptr_t)vectors,
                                               (int32_t)count,(int32_t)(uintptr_t)written);
}
__wasi_errno_t __wasi_fd_seek(__wasi_fd_t fd,__wasi_filedelta_t offset,__wasi_whence_t whence,
                              __wasi_filesize_t *result) {
    return (__wasi_errno_t)lsf_c_stdio_fd_seek((int32_t)fd,offset,(int32_t)whence,(int32_t)(uintptr_t)result);
}
__wasi_errno_t __wasi_fd_fdstat_get(__wasi_fd_t fd,__wasi_fdstat_t *result) {
    return (__wasi_errno_t)lsf_c_stdio_fd_fdstat_get((int32_t)fd,(int32_t)(uintptr_t)result);
}

extern void __wasm_call_ctors(void);
extern int standard_log_probe(unsigned);
__attribute__((export_name("signed_logging_mode_control"))) int signed_logging_mode_control(void) {
    __wasm_call_ctors();
    if (!standard_log_probe(4)) return __LINE__;
    if (accepted_records != 2 || accepted_bytes != 512) return __LINE__;
    return 0;
}
