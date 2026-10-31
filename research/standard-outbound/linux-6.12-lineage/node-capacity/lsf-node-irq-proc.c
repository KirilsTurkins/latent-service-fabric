/* SPDX-License-Identifier: GPL-2.0-only */
/* Included at the END of real fs/proc/generic.c. All seven clones below retain
 * the complete native bodies and error/rundown contracts; their exact inverses
 * are bound in native-clone-inverses.json. No private inode/opener is admitted. */
#include <net/lsf_node_capacity_private.h>

int lsf_node_irq_proc_layout(struct lsf_node_capacity_extent *out)
{
    if (!SIZEOF_PDE || !SIZEOF_PDE_INLINE_NAME || SIZEOF_PDE > PAGE_SIZE ||
        __alignof__(struct proc_dir_entry) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out[LSF_NODE_PROC_PDE] = (struct lsf_node_capacity_extent){
        SIZEOF_PDE, __alignof__(struct proc_dir_entry)};
    return 0;
}

int lsf_node_irq_proc_free(struct proc_dir_entry *pde)
{
    int selected = lsf_node_irq_proc_classify(pde);
    if (selected != 1)
        return selected;
    /* A failed __proc_create may reach here before mode/refcnt init, including
     * a NULL out-of-line-name allocation. Actual last pde_put owns normal free.
     * Readers are refused before pde_get/new_inode; no pretend reader capacity. */
    if (pde->mode && !S_ISDIR(pde->mode) && !S_ISREG(pde->mode)) {
        lsf_factory_stream_constructor_retain_unknown();
        return -EOPNOTSUPP;
    }
    if (pde->name && pde->name != pde->inline_name) {
        if (lsf_node_irq_proc_name_pair(pde, pde->name) != 1 ||
            lsf_node_capacity_native_free(pde->name, LSF_NODE_PROC_NAME) != 1)
            return -EIO;
    }
    return lsf_node_capacity_native_free(pde, LSF_NODE_PROC_PDE);
}

static int lsf_node_proc_alloc_inum(unsigned int *inum)
{
	int i;

	i = lsf_prepaid_stream_ida_alloc_existing(&proc_inum_ida, 0, UINT_MAX - PROC_DYNAMIC_FIRST);
	if (i < 0)
		return i;

	*inum = PROC_DYNAMIC_FIRST + (unsigned int)i;
	return 0;
}

static struct proc_dir_entry *lsf_node_proc_create(struct lsf_node_capacity *owner, struct irq_desc *desc, unsigned int position, struct proc_dir_entry **parent,
					  const char *name,
					  umode_t mode,
					  nlink_t nlink)
{
	struct proc_dir_entry *ent = NULL;
	const char *fn;
	struct qstr qstr;

	if (xlate_proc_name(name, parent, &fn) != 0)
		goto out;
	qstr.name = fn;
	qstr.len = strlen(fn);
	if (qstr.len == 0 || qstr.len >= 256) {
		WARN(1, "name len %u\n", qstr.len);
		return NULL;
	}
	if (qstr.len == 1 && fn[0] == '.') {
		WARN(1, "name '.'\n");
		return NULL;
	}
	if (qstr.len == 2 && fn[0] == '.' && fn[1] == '.') {
		WARN(1, "name '..'\n");
		return NULL;
	}
	if (*parent == &proc_root && name_to_int(&qstr) != ~0U) {
		WARN(1, "create '/proc/%s' by hand\n", qstr.name);
		return NULL;
	}
	if (is_empty_pde(*parent)) {
		WARN(1, "attempt to add to permanently empty directory");
		return NULL;
	}

	ent = lsf_node_irq_proc_allocate(owner, desc, position, false);
	if (!ent)
		goto out;

	if (qstr.len + 1 <= SIZEOF_PDE_INLINE_NAME) {
		ent->name = ent->inline_name;
	} else {
		ent->name = position == 8u && qstr.len + 1u <= owner->extent[LSF_NODE_PROC_NAME].bytes
			? lsf_node_irq_proc_allocate(owner, desc, position, true) : NULL;
		if (!ent->name) {
			pde_free(ent);
			return NULL;
		}
	}

	memcpy(ent->name, fn, qstr.len + 1);
	ent->namelen = qstr.len;
	ent->mode = mode;
	ent->nlink = nlink;
	ent->subdir = RB_ROOT;
	refcount_set(&ent->refcnt, 1);
	spin_lock_init(&ent->pde_unload_lock);
	INIT_LIST_HEAD(&ent->pde_openers);
	proc_set_user(ent, (*parent)->uid, (*parent)->gid);

	ent->proc_dops = &proc_misc_dentry_ops;
	/* Revalidate everything under /proc/${pid}/net */
	if ((*parent)->proc_dops == &proc_net_dentry_ops)
		pde_force_lookup(ent);

out:
	return ent;
}

static struct proc_dir_entry *lsf_node_proc_register(struct proc_dir_entry *dir,
		struct proc_dir_entry *dp)
{
	if (lsf_node_proc_alloc_inum(&dp->low_ino))
		goto out_free_entry;

	if (!S_ISDIR(dp->mode))
		pde_set_flags(dp);

	write_lock(&proc_subdir_lock);
	dp->parent = dir;
	if (pde_subdir_insert(dir, dp) == false) {
		WARN(1, "proc_dir_entry '%s/%s' already registered\n",
		     dir->name, dp->name);
		write_unlock(&proc_subdir_lock);
		goto out_free_inum;
	}
	write_unlock(&proc_subdir_lock);

	return dp;
out_free_inum:
	proc_free_inum(dp->low_ino);
out_free_entry:
	pde_free(dp);
	return NULL;
}

static struct proc_dir_entry *lsf_node_proc_create_reg(struct lsf_node_capacity *owner, struct irq_desc *desc, unsigned int position, const char *name, umode_t mode,
		struct proc_dir_entry **parent, void *data)
{
	struct proc_dir_entry *p;

	if ((mode & S_IFMT) == 0)
		mode |= S_IFREG;
	if ((mode & S_IALLUGO) == 0)
		mode |= S_IRUGO;
	if (WARN_ON_ONCE(!S_ISREG(mode)))
		return NULL;

	p = lsf_node_proc_create(owner, desc, position, parent, name, mode, 1);
	if (p) {
		p->proc_iops = &proc_file_inode_operations;
		p->data = data;
	}
	return p;
}

static struct proc_dir_entry *lsf_node_proc_mkdir(struct lsf_node_capacity *owner, struct irq_desc *desc, unsigned int position, const char *name, umode_t mode,
		struct proc_dir_entry *parent, void *data, bool force_lookup)
{
	struct proc_dir_entry *ent;

	if (mode == 0)
		mode = S_IRUGO | S_IXUGO;

	ent = lsf_node_proc_create(owner, desc, position, &parent, name, S_IFDIR | mode, 2);
	if (ent) {
		ent->data = data;
		ent->proc_dir_ops = &proc_dir_operations;
		ent->proc_iops = &proc_dir_inode_operations;
		if (force_lookup) {
			pde_force_lookup(ent);
		}
		ent = lsf_node_proc_register(parent, ent);
	}
	return ent;
}

static struct proc_dir_entry *lsf_node_proc_create_data(struct lsf_node_capacity *owner, struct irq_desc *desc, unsigned int position, const char *name, umode_t mode,
		struct proc_dir_entry *parent,
		const struct proc_ops *proc_ops, void *data)
{
	struct proc_dir_entry *p;

	p = lsf_node_proc_create_reg(owner, desc, position, name, mode, &parent, data);
	if (!p)
		return NULL;
	p->proc_ops = proc_ops;
	return lsf_node_proc_register(parent, p);
}

static struct proc_dir_entry *lsf_node_proc_create_single_data(struct lsf_node_capacity *owner, struct irq_desc *desc, unsigned int position, const char *name, umode_t mode,
		struct proc_dir_entry *parent,
		int (*show)(struct seq_file *, void *), void *data)
{
	struct proc_dir_entry *p;

	p = lsf_node_proc_create_reg(owner, desc, position, name, mode, &parent, data);
	if (!p)
		return NULL;
	p->proc_ops = &proc_single_ops;
	p->single_show = show;
	return lsf_node_proc_register(parent, p);
}

struct proc_dir_entry *lsf_node_irq_proc_mkdir(struct irq_desc *desc,
    unsigned int position, const char *name, struct proc_dir_entry *parent)
{
    struct lsf_node_capacity *owner;
    if ((position != 0u && position != 8u) ||
        lsf_node_irq_device_owner(desc, &owner) != 1)
        return NULL;
    return lsf_node_proc_mkdir(owner, desc, position, name, 0, parent, NULL, false);
}

struct proc_dir_entry *lsf_node_irq_proc_create_data(struct irq_desc *desc,
    unsigned int position, const char *name, umode_t mode,
    struct proc_dir_entry *parent, const struct proc_ops *ops, void *data)
{
    struct lsf_node_capacity *owner;
    if ((position != 1u && position != 3u) ||
        lsf_node_irq_device_owner(desc, &owner) != 1)
        return NULL;
    return lsf_node_proc_create_data(owner, desc, position, name, mode, parent, ops, data);
}

struct proc_dir_entry *lsf_node_irq_proc_create_single_data(struct irq_desc *desc,
    unsigned int position, const char *name, umode_t mode,
    struct proc_dir_entry *parent, int (*show)(struct seq_file *, void *), void *data)
{
    struct lsf_node_capacity *owner;
    if ((position != 2u && (position < 4u || position > 7u)) ||
        lsf_node_irq_device_owner(desc, &owner) != 1)
        return NULL;
    return lsf_node_proc_create_single_data(owner, desc, position, name, mode,
        parent, show, data);
}
