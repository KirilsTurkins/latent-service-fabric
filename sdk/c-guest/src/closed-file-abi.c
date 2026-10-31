/* SPDX-License-Identifier: Apache-2.0 AND MIT
 * Shared selected HTTP profile: ordinary file APIs are explicitly unsupported.
 * The exact musl match layout/globfree body below is retained from Zig 0.16.0;
 * see libfetch/upstream/musl-COPYRIGHT and libfetch/UPSTREAM.json.
 */
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <stddef.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static int file_unsupported(void) {
    errno = ENOTSUP;
    return -1;
}

int open(const char *path, int flags, ...) {
    (void)path; (void)flags;
    return file_unsupported();
}

int close(int fd) {
    (void)fd;
    return file_unsupported();
}

int fstat(int fd, struct stat *output) {
    (void)fd; (void)output;
    return file_unsupported();
}

void *mmap(void *address, size_t length, int protection, int flags, int fd, off_t offset) {
    (void)address; (void)length; (void)protection;
    (void)flags; (void)fd; (void)offset;
    file_unsupported();
    return MAP_FAILED;
}

int munmap(void *address, size_t length) {
    (void)address; (void)length;
    return file_unsupported();
}

char *realpath(const char *restrict path, char *restrict output) {
    (void)path; (void)output;
    file_unsupported();
    return NULL;
}

char *getcwd(char *output, size_t length) {
    (void)output; (void)length;
    file_unsupported();
    return NULL;
}

int glob(const char *restrict pattern, int flags,
         int (*error_callback)(const char *, int), glob_t *restrict output) {
    (void)pattern; (void)flags; (void)error_callback; (void)output;
    errno = ENOSYS;
    return GLOB_NOSYS;
}

struct match
{
	struct match *next;
	char name[];
};

void globfree(glob_t *g)
{
	size_t i;
	for (i=0; i<g->gl_pathc; i++)
		free(g->gl_pathv[g->gl_offs + i] - offsetof(struct match, name));
	free(g->gl_pathv);
	g->gl_pathc = 0;
	g->gl_pathv = NULL;
}
