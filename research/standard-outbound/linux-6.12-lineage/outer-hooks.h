/* SPDX-License-Identifier: GPL-2.0-only */
/* Private explicit outer-object path. No registration or qualification ABI. */
#ifndef LSF_STREAM_OUTER_H
#define LSF_STREAM_OUTER_H
#include <linux/types.h>
struct inode;
struct socket;
struct super_block;
struct lsf_factory_context;
#ifdef CONFIG_LSF_STREAM_FACTORY
#ifdef CONFIG_SECURITY
bool lsf_outer_security_supported(void);
#else
/* No alternate unreviewed security configuration is a closure certificate. */
static inline bool lsf_outer_security_supported(void) { return false; }
#endif
bool lsf_outer_superblock_supported(struct super_block *);
struct inode *lsf_outer_alloc_inode(struct super_block *, struct lsf_factory_context *);
struct inode *lsf_prepaid_new_inode(struct super_block *, struct lsf_factory_context *);
struct socket *lsf_outer_sock_alloc(struct lsf_factory_context *);
int lsf_outer_socket_begin(int, int, int, struct lsf_factory_context *, struct socket **);
int lsf_outer_socket_post_create(struct socket *, int, int, int, struct lsf_factory_context *);
void lsf_outer_inode_queue(struct inode *);
#else
static inline void lsf_outer_inode_queue(struct inode *inode) { (void)inode; }
#endif
#endif
