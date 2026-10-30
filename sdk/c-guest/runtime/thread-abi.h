/* Compiler-owned memory32 ABI. No ordinary builder selects this runtime yet. */
#ifndef LSF_C_THREAD_ABI_H
#define LSF_C_THREAD_ABI_H
#include <stddef.h>
#include <stdint.h>

enum lsf_c_phase { LSF_C_PREPARED=1, LSF_C_RUNNING=2, LSF_C_FRAMES_EXITED=5 };
enum lsf_c_owner_kind { LSF_C_TASK=0, LSF_C_WAIT=4, LSF_C_RESULT=6, LSF_C_NATIVE=7 };
enum lsf_c_api { LSF_C_ROOT=0, LSF_C_PTHREAD=1, LSF_C_C11=2 };
struct lsf_c_token { uint64_t generation, id; };
struct lsf_c_thread;

/* The original C32 prefix remains byte-for-byte compatible with c_context.rs.
 * Tokens belong to the original activation broker. They are not capabilities,
 * fabricated thread identities, or a second memory/native-stack quota.
 */
struct __attribute__((aligned(16))) lsf_c_thread {
    uint32_t sp, low, high, tls, tls_bytes, phase;
    uint32_t parent, canonical_id;
    struct lsf_c_token task, context_owner, result_owner;
    uint8_t admission[2], creation_started, tls_finished;
    uint32_t api, joined, joiner, closing;
    union { void *(*pthread)(void *); int (*c11)(void *); } start;
    void *argument;
    union { void *pthread; int c11; } result;
    struct lsf_c_thread *root, *next;
    void *stack_allocation, *tls_allocation;
    uint32_t started_count;
    const void *initial_template;
    struct lsf_c_thread *waiting_for;
};

_Static_assert(sizeof(void *)==4, "C threading requires memory32");
_Static_assert(sizeof(struct lsf_c_token)==16, "unsupported runtime token ABI");
_Static_assert(offsetof(struct lsf_c_thread,phase)==20, "original C phase offset");
_Static_assert(offsetof(struct lsf_c_thread,task)==32, "C Task offset");
_Static_assert(offsetof(struct lsf_c_thread,context_owner)==48, "C Native offset");
_Static_assert(offsetof(struct lsf_c_thread,result_owner)==64, "C Result offset");
_Static_assert(offsetof(struct lsf_c_thread,admission)==80, "C admission offset");
_Static_assert(offsetof(struct lsf_c_thread,creation_started)==82, "C one-shot offset");
_Static_assert(offsetof(struct lsf_c_thread,tls_finished)==83, "C TLS-finished offset");
_Static_assert(sizeof(struct lsf_c_thread)==144, "fixed C context bytes");
_Static_assert(_Alignof(struct lsf_c_thread)==16,"C context alignment");

/* These are actual canonical intrinsics, never application callback hooks. */
__attribute__((import_module("$root"),import_name("[context-get-1]")))
struct lsf_c_thread *lsf_c_context_get(void);
__attribute__((import_module("$root"),import_name("[context-set-1]")))
void lsf_c_context_set(struct lsf_c_thread *);
__attribute__((import_module("$root"),import_name("[thread-index]")))
uint32_t lsf_c_thread_index(void);
__attribute__((import_module("$root"),import_name("[thread-new-indirect-v0]")))
uint32_t lsf_c_thread_new(uint32_t table_index,struct lsf_c_thread *context);
__attribute__((import_module("$root"),import_name("[thread-yield-then-promote]")))
uint32_t lsf_c_thread_switch(uint32_t thread);
__attribute__((import_module("$root"),import_name("[thread-yield]")))
uint32_t lsf_c_thread_yield(void);

/* Root entry must be stacklessly attached before calling these ordinary C
 * bodies. The compiler owns the immutable pre-constructor template and exact
 * root/child ranges. No application may initialize or replace this contract.
 */
int __lsf_c_root_initialize(struct lsf_c_thread *,uint32_t);
void __lsf_c_template_copy(void *);
void __lsf_c_thread_body(struct lsf_c_thread *);
void __lsf_c_root_finish(struct lsf_c_thread *);
int lsf_c_tls_finish(void);
#endif
