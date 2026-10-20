#ifndef LSF_C_CLOSED_STDIO_H
#define LSF_C_CLOSED_STDIO_H

#include_next <stdio.h>

#if defined(__wasi__)
#include <errno.h>
#include <string.h>

/* The pinned libc checks the initial mode before attempting an open. */
static inline FILE *lsf_closed_fopen(const char *restrict path,
                                   const char *restrict mode) {
    (void)path;
    if (!strchr("rwa", *mode)) {
        errno = EINVAL;
        return NULL;
    }
    errno = ENOTSUP;
    return NULL;
}

static inline FILE *lsf_closed_tmpfile(void) {
    errno = ENOTSUP;
    return NULL;
}

#undef fopen
#undef tmpfile
#define fopen lsf_closed_fopen
#define tmpfile lsf_closed_tmpfile
#endif

#endif
