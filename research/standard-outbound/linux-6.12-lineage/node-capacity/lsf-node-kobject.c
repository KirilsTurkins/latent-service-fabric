/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after native lib/kobject.c. Exact original namespace/last-release
 * ordering; only the paid IRQ name final-return replaces ordinary kfree_const.
 * Identity is captured BEFORE native release can retire the descriptor view.
 */
#include <net/lsf_node_capacity_private.h>

static void lsf_node_irq_cleanup_body(struct kobject *kobj,
    struct lsf_node_irq_name original_name)
{
	struct kobject *parent = kobj->parent;
	const struct kobj_type *t = get_ktype(kobj);
	const char *name = kobj->name;

	pr_debug("'%s' (%p): %s, parent %p\n",
		 kobject_name(kobj), kobj, __func__, kobj->parent);

	if (t && !t->release)
		pr_debug("'%s' (%p): does not have a release() function, it is broken and must be fixed. See Documentation/core-api/kobject.rst.\n",
			 kobject_name(kobj), kobj);

	/* remove from sysfs if the caller did not do it */
	if (kobj->state_in_sysfs) {
		pr_debug("'%s' (%p): auto cleanup kobject_del\n",
			 kobject_name(kobj), kobj);
		__kobject_del(kobj);
	} else {
		/* avoid dropping the parent reference unnecessarily */
		parent = NULL;
	}

	if (t && t->release) {
		pr_debug("'%s' (%p): calling ktype release\n",
			 kobject_name(kobj), kobj);
		t->release(kobj);
	}

	/* free name if we allocated it */
	if (name) {
		pr_debug("'%s': free name\n", name);
		(void)lsf_node_irq_name_finish(original_name, name);
	}

	kobject_put(parent);
}

int lsf_node_irq_kobject_cleanup(struct kobject *object)
{
    struct lsf_node_irq_name name;
    int owned = lsf_node_irq_kobject_owned(object);

    if (owned <= 0)
        return owned;
    if (lsf_node_irq_kobject_type_known(object) != 1 ||
        lsf_node_irq_name_capture(object, object->name, &name) != 1)
        return lsf_node_irq_kobject_retain(object);
    lsf_node_irq_cleanup_body(object, name);
    return 1;
}
