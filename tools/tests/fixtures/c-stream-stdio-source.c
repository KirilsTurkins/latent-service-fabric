/* Actual combined stdio/stream sources with finite provider and libc doubles.
 * This is not a signed component or real-provider qualification. */
#include "c-stream-descriptor-source.c"
#include <stdio.h>
#include <wasi/api.h>

FILE *const stdout = (FILE *)(uintptr_t)1;
FILE *const stderr = (FILE *)(uintptr_t)2;
static unsigned setvbuf_calls, log_calls, accepted_logs;
static bool log_allowed, capture_logs, refuse_budget;
static latent_log_log_level_t last_level;
static uint8_t captured_logs[2048];
static size_t captured_bytes;

int setvbuf(FILE *stream, char *buffer, int mode, size_t size) {
    if ((stream != stdout && stream != stderr) || buffer || mode != _IONBF || size) __builtin_trap();
    ++setvbuf_calls;
    return 0;
}

bool latent_log_log_write(latent_log_log_level_t level, probe_string_t *message,
                         latent_log_log_list_field_t *fields, bool *accepted,
                         latent_log_log_log_error_t *error) {
    if (!message || !message->ptr || fields->len) __builtin_trap();
    ++log_calls;
    last_level = level;
    /* Match the real host's per-message limit, not the adapter's buffer. */
    if (message->len > 256) {
        *error = (latent_log_log_log_error_t){.tag = LATENT_LOG_LOG_LOG_ERROR_INVALID_FIELD};
        return false;
    }
    if (!log_allowed) {
        *error = (latent_log_log_log_error_t){.tag = LATENT_LOG_LOG_LOG_ERROR_UNAVAILABLE};
        return false;
    }
    if (refuse_budget) {
        *error = (latent_log_log_log_error_t){.tag = LATENT_LOG_LOG_LOG_ERROR_BUDGET_EXHAUSTED};
        return false;
    }
    if (capture_logs) {
        if (message->len > sizeof(captured_logs) - captured_bytes) __builtin_trap();
        memcpy(captured_logs + captured_bytes, message->ptr, message->len);
        captured_bytes += message->len;
    }
    ++accepted_logs;
    *accepted = true;
    return true;
}

void latent_log_log_log_error_free(latent_log_log_log_error_t *error) {
    if (error->tag != LATENT_LOG_LOG_LOG_ERROR_UNAVAILABLE &&
        error->tag != LATENT_LOG_LOG_LOG_ERROR_INVALID_FIELD &&
        error->tag != LATENT_LOG_LOG_LOG_ERROR_BUDGET_EXHAUSTED) __builtin_trap();
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

    /* Source-level writev keeps the combined log sink and its short writes. */
    uint8_t log_bytes[300];memset(log_bytes,'z',sizeof(log_bytes));
    struct iovec log_parts[2]={{.iov_base=log_bytes,.iov_len=150},
                               {.iov_base=log_bytes+150,.iov_len=150}};
    capture_logs=true;unsigned vector_calls=log_calls;
    CHECK(writev(1,log_parts,2)==256 && log_calls==vector_calls+1 && captured_bytes==256);
    log_parts[0]=(struct iovec){.iov_base=log_bytes+256,.iov_len=44};
    CHECK(writev(1,log_parts,1)==44 && log_calls==vector_calls+2 && captured_bytes==300);
    for(size_t i=0;i<sizeof(log_bytes);++i) CHECK(captured_logs[i]=='z');
    log_parts[1]=(struct iovec){.iov_base=NULL,.iov_len=1};vector_calls=log_calls;
    CHECK(writev(1,log_parts,2)==-1 && lsf_test_errno==EFAULT && log_calls==vector_calls);
    capture_logs=false;captured_bytes=0;

    /* A normal write can make bounded progress when a host log record is
     * smaller than the input. Never split a UTF-8 scalar across records. */
    uint8_t large[300];memset(large, 'x', sizeof(large));
    __wasi_ciovec_t vectors[2]={{.buf=large,.buf_len=sizeof(large)}};
    __wasi_size_t written=999;capture_logs=true;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==0 && written==256);
    vectors[0]=(__wasi_ciovec_t){.buf=large+written,.buf_len=sizeof(large)-written};written=999;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==0 && written==44);
    CHECK(captured_bytes==sizeof(large));
    for(size_t i=0;i<sizeof(large);++i) CHECK(captured_logs[i]==large[i]);

    uint8_t first[256];memset(first,'a',sizeof(first));first[255]=0xe2;
    uint8_t rest[]={0x82,0xac};
    vectors[0]=(__wasi_ciovec_t){.buf=first,.buf_len=sizeof(first)};
    vectors[1]=(__wasi_ciovec_t){.buf=rest,.buf_len=sizeof(rest)};written=999;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(2,(int32_t)(uintptr_t)vectors,2,
          (int32_t)(uintptr_t)&written)==0 && written==255);
    vectors[0]=(__wasi_ciovec_t){.buf=first+written,.buf_len=1};written=999;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(2,(int32_t)(uintptr_t)vectors,2,
          (int32_t)(uintptr_t)&written)==0 && written==3);
    CHECK(captured_bytes==sizeof(large)+sizeof(first)+sizeof(rest));
    for(size_t i=0;i<sizeof(first);++i) CHECK(captured_logs[sizeof(large)+i]==first[i]);
    CHECK(captured_logs[captured_bytes-2]==rest[0] && captured_logs[captured_bytes-1]==rest[1]);

    const uint8_t scalars[2][4]={{0xc3,0xa9,0,0},{0xf0,0x9f,0x92,0xa9}};
    const size_t scalar_sizes[2]={2,4};
    for(size_t case_index=0;case_index<2;++case_index) {
        size_t start=captured_bytes;memset(first,'b',sizeof(first));first[255]=scalars[case_index][0];
        vectors[0]=(__wasi_ciovec_t){.buf=first,.buf_len=sizeof(first)};
        vectors[1]=(__wasi_ciovec_t){.buf=scalars[case_index]+1,.buf_len=scalar_sizes[case_index]-1};written=999;
        CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,2,
              (int32_t)(uintptr_t)&written)==0 && written==255);
        vectors[0]=(__wasi_ciovec_t){.buf=first+255,.buf_len=1};written=999;
        CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,2,
              (int32_t)(uintptr_t)&written)==0 && written==scalar_sizes[case_index]);
        CHECK(captured_bytes==start+255+scalar_sizes[case_index]);
        for(size_t i=0;i<255;++i) CHECK(captured_logs[start+i]=='b');
        for(size_t i=0;i<scalar_sizes[case_index];++i) CHECK(captured_logs[start+255+i]==scalars[case_index][i]);
    }

    size_t exact_start=captured_bytes;
    vectors[0]=(__wasi_ciovec_t){.buf=large,.buf_len=256};
    vectors[1]=(__wasi_ciovec_t){.buf=NULL,.buf_len=0};written=999;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,2,
          (int32_t)(uintptr_t)&written)==0 && written==256);
    CHECK(captured_bytes==exact_start+256);
    for(size_t i=0;i<256;++i) CHECK(captured_logs[exact_start+i]==large[i]);
    vectors[0]=vectors[1];written=999;unsigned zero_calls=log_calls;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==0 && written==0 && log_calls==zero_calls);

    uint8_t malformed[]={0xc3,0x20};
    vectors[0]=(__wasi_ciovec_t){.buf=malformed,.buf_len=sizeof(malformed)};written=999;
    unsigned previous_calls=log_calls,previous_accepted=accepted_logs;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==__WASI_ERRNO_ILSEQ && written==999);
    CHECK(log_calls==previous_calls && accepted_logs==previous_accepted);
    vectors[0].buf_len=1;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==__WASI_ERRNO_ILSEQ && written==999);
    CHECK(log_calls==previous_calls && accepted_logs==previous_accepted);
    vectors[0]=(__wasi_ciovec_t){.buf=(const uint8_t *)"out",.buf_len=3};
    refuse_budget=true;written=999;
    CHECK(__imported_wasi_snapshot_preview1_fd_write(1,(int32_t)(uintptr_t)vectors,1,
          (int32_t)(uintptr_t)&written)==__WASI_ERRNO_AGAIN && written==999);
    CHECK(log_calls==previous_calls+1 && accepted_logs==previous_accepted);
    return 0;
}

__attribute__((export_name("stdio_missing_log_authority"))) int stdio_missing_log_authority(void) {
    __lsf_c_stdio_initialize();
    log_allowed = false;
    CHECK(__lsf_c_net_write(1, "out", 3) == -1 && lsf_test_errno == EIO);
    CHECK(log_calls == 1 && accepted_logs == 0 && host_calls == 0);
    CHECK(__lsf_c_net_write(2, "err", 3) == -1 && lsf_test_errno == EIO);
    CHECK(log_calls == 2 && accepted_logs == 0 && host_calls == 0);
    struct iovec denied={.iov_base=(void *)"out",.iov_len=3};
    CHECK(writev(1,&denied,1)==-1 && lsf_test_errno==EIO);
    CHECK(log_calls == 3 && accepted_logs == 0 && host_calls == 0);
    return 0;
}
