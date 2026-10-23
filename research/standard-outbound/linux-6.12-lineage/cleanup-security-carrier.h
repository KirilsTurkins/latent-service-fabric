/* SPDX-License-Identifier: GPL-2.0-only */
/* Typed original NodeFixed ancestry, distinct from both application and PCI. */
#ifndef LSF_STREAM_CLEANUP_SECURITY_CARRIER_H
#define LSF_STREAM_CLEANUP_SECURITY_CARRIER_H
#define LSF_ROOT_SECURITY_TASK_BIRTH 0x11fu
#define LSF_ROOT_SECURITY_AVC_NODE 0x140u
#define LSF_ROOT_SECURITY_AVC_XPERMS 0x141u
#define LSF_ROOT_SECURITY_AVC_DECISION 0x142u
#define LSF_ROOT_SECURITY_AVC_DATA 0x143u
#define LSF_ROOT_SECURITY_SIDCACHE 0x144u
#define LSF_ROOT_SECURITY_AUDIT_STRING 0x145u
#define LSF_ROOT_SECURITY_AUDIT_BUFFER 0x146u
#define LSF_ROOT_SECURITY_AUDIT_SKB 0x147u
#define LSF_ROOT_SECURITY_AUDIT_HEAD 0x148u

struct lsf_cleanup_security_source {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket root, allocation;
    const void *address;
    unsigned int kind;
};

static inline int lsf_root_security_kind(unsigned int kind)
{
    return kind == LSF_ROOT_SECURITY_AVC_NODE || kind == LSF_ROOT_SECURITY_AVC_XPERMS ||
        kind == LSF_ROOT_SECURITY_AVC_DECISION || kind == LSF_ROOT_SECURITY_AVC_DATA ||
        kind == LSF_ROOT_SECURITY_SIDCACHE || kind == LSF_ROOT_SECURITY_AUDIT_STRING ||
        kind == LSF_ROOT_SECURITY_AUDIT_BUFFER || kind == LSF_ROOT_SECURITY_AUDIT_SKB ||
        kind == LSF_ROOT_SECURITY_AUDIT_HEAD;
}
static inline int lsf_root_security_shape(struct lsf_cleanup_security_source source)
{
    return source.owner.slot < LSF_OWNER_SLOTS && source.owner.generation &&
        source.root.slot && source.root.slot < LSF_ALLOCATION_SLOTS && source.root.generation &&
        source.allocation.slot && source.allocation.slot < LSF_ALLOCATION_SLOTS &&
        source.allocation.generation && source.address &&
        (source.kind == LSF_ROOT_SECURITY_TASK_BIRTH || lsf_root_security_kind(source.kind));
}
struct lsf_factory_blob;
struct task_struct;
struct sidtab;
int lsf_factory_cleanup_task_constructor_blob(const struct task_struct *, struct lsf_factory_blob *);
int lsf_factory_cleanup_security_candidate(unsigned int, unsigned int,
    struct lsf_cleanup_security_source *, unsigned int *, lsf_u64 *);
int lsf_factory_cleanup_security_current(struct lsf_cleanup_security_source,
    unsigned int, lsf_u64, void **);
void lsf_prepaid_cleanup_avc_drain(void);
void lsf_prepaid_cleanup_sidcache_drain(void);
void lsf_prepaid_cleanup_sidcache_detach(struct sidtab *, struct lsf_cleanup_security_source);
#endif
