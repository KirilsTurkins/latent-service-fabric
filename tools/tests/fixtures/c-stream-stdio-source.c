/* Actual combined stdio/stream sources with finite provider and libc doubles.
 * This is not a signed component or real-provider qualification. */
#include "c-stream-descriptor-source.c"
#include <stdio.h>
#include <wasi/api.h>

FILE *const stdout = (FILE *)(uintptr_t)1;
FILE *const stderr = (FILE *)(uintptr_t)2;
static unsigned setvbuf_calls, log_calls, accepted_logs;
static bool log_allowed;
static latent_log_log_level_t last_level;

int setvbuf(FILE *stream, char *buffer, int mode, size_t size) {
    if ((stream != stdout && stream != stderr) || buffer || mode != _IONBF || size) __builtin_trap();
    ++setvbuf_calls;
    return 0;
}

bool latent_log_log_write(latent_log_log_level_t level, probe_string_t *message,
                         latent_log_log_list_field_t *fields, bool *accepted,
                         latent_log_log_log_error_t *error) {
    if (!message || !message->ptr || message->len != 3 || fields->len) __builtin_trap();
    ++log_calls;
    last_level = level;
    if (!log_allowed) {
        *error = (latent_log_log_log_error_t){.tag = LATENT_LOG_LOG_LOG_ERROR_UNAVAILABLE};
        return false;
    }
    ++accepted_logs;
    *accepted = true;
    return true;
}

void latent_log_log_log_error_free(latent_log_log_log_error_t *error) {
    if (error->tag != LATENT_LOG_LOG_LOG_ERROR_UNAVAILABLE) __builtin_trap();
}

extern int32_t __imported_wasi_snapshot_preview1_fd_write(int32_t, int32_t, int32_t, int32_t);
extern void __lsf_c_stdio_initialize(void);

/* The real selected source calls libc write; this double passes its one
 * iovec to the actual locally linked fd_write implementation. */
ssize_t fake_libc_write(int fd, const void *buffer, size_t length) __asm__("write");
ssize_t fake_libc_write(int fd, const void *buffer, size_t length) {
    __wasi_ciovec_t vector = {.buf = buffer, .buf_len = length};
    __wasi_size_t written = 99;
    int32_t error = __imported_wasi_snapshot_preview1_fd_write(
        fd, (int32_t)(uintptr_t)&vector, 1, (int32_t)(uintptr_t)&written);
    if (error) { lsf_test_errno = error == __WASI_ERRNO_BADF ? EBADF : EIO; return -1; }
    return (ssize_t)written;
}

int actual_libc_close(int fd) __asm__("close");

__attribute__((export_name("stdio_stream_controls"))) int stdio_stream_controls(void) {
    __lsf_c_stdio_initialize();
    __lsf_c_stdio_initialize();
    CHECK(setvbuf_calls == 2);
    log_allowed = true;
    CHECK(__lsf_c_net_write(1, "out", 3) == 3 && last_level == LATENT_LOG_LOG_LEVEL_INFO);
    CHECK(__lsf_c_net_write(2, "err", 3) == 3 && last_level == LATENT_LOG_LOG_LEVEL_ERROR);
    CHECK(log_calls == 2 && accepted_logs == 2 && host_calls == 0);
    CHECK(__lsf_c_net_write(0, "in!", 3) == -1 && lsf_test_errno == EBADF);
    char byte = 0;
    CHECK(__lsf_c_net_read(0, &byte, 1) == -1 && lsf_test_errno == EBADF);
    CHECK(actual_libc_close(1) == -1 && lsf_test_errno == ENOTSUP);
    CHECK(actual_libc_close(2) == -1 && lsf_test_errno == ENOTSUP);
    CHECK(actual_libc_close(0) == -1 && lsf_test_errno == EBADF);
    current_fd = __lsf_c_net_socket(AF_INET, SOCK_STREAM, 0);
    CHECK(current_fd == 3);
    struct sockaddr_in peer = address();
    allow_host = 1;
    CHECK(__lsf_c_net_connect(current_fd, (struct sockaddr *)&peer, sizeof(peer)) == 0);
    int before = host_calls;
    CHECK(__lsf_c_net_write(current_fd, "xyz", 3) == 2 && host_calls == before + 1);
    CHECK(log_calls == 2 && accepted_logs == 2);
    CHECK(actual_libc_close(current_fd) == 0 && close_calls == 1);
    CHECK(__lsf_c_net_write(current_fd, "xyz", 3) == -1 && lsf_test_errno == EBADF);
    return 0;
}

__attribute__((export_name("stdio_missing_log_authority"))) int stdio_missing_log_authority(void) {
    __lsf_c_stdio_initialize();
    log_allowed = false;
    CHECK(__lsf_c_net_write(1, "out", 3) == -1 && lsf_test_errno == EIO);
    CHECK(log_calls == 1 && accepted_logs == 0 && host_calls == 0);
    CHECK(__lsf_c_net_write(2, "err", 3) == -1 && lsf_test_errno == EIO);
    CHECK(log_calls == 2 && accepted_logs == 0 && host_calls == 0);
    return 0;
}
