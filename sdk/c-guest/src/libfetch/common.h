/*-
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Copyright (c) 1998-2014 Dag-Erling Smørgrav
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer
 *    in this position and unchanged.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. The name of the author may not be used to endorse or promote products
 *    derived from this software without specific prior written permission
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 * IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
 * NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 * THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/* SPDX-License-Identifier: BSD-3-Clause
 * Source-port subset of FreeBSD libfetch common.h. The original fetch.c only
 * consumes this error tuple/protocol and the disabled DEBUGF macro. No socket,
 * resolver, TLS connection, environment or proxy implementation is installed.
 */
#ifndef LSF_LIBFETCH_COMMON_H
#define LSF_LIBFETCH_COMMON_H
#ifndef IPPORT_MAX
#define IPPORT_MAX 65535u
#endif
struct fetcherr { const int num; const int cat; const char *string; };
void fetch_seterr(struct fetcherr *, int);
void fetch_syserr(void);
#define url_seterr(n) fetch_seterr(url_errlist, n)
#define DEBUGF(...) do { } while (0)
#endif
