/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP included in actual lib/kobject_uevent.c after its original headers.
 * No generic kobject_get_path allocator override, callback substitution,
 * retries or external path-address certificate is introduced. This single
 * source-bound path belongs to the actual emitting PCI parent callback. */
static char *lsf_prepaid_device_uevent_path(struct lsf_device_registration_source source,
    const struct kobject *kobj)
{
    const struct kobject *parent;
    const char *name;
    unsigned long length = 1, remaining, size;
    unsigned int depth = 0;
    char *path;
    if (lsf_factory_device_uevent_current(source) != 1)
        return NULL;
    for (parent = kobj; parent; parent = parent->parent) {
        if (++depth > LSF_DEVICE_UEVENT_MAX_ANCESTORS ||
            !(name = kobject_name(parent)))
            return NULL;
        size = strnlen(name, NAME_MAX + 1);
        if (!size || size > NAME_MAX || length > PATH_MAX - size - 1)
            return NULL;
        length += size + 1;
    }
    path = lsf_factory_device_uevent_allocate(source, length, LSF_DEVICE_UEVENT_KIND_PATH);
    if (!path)
        return NULL;
    /* Preserve original trailing NUL, reverse ancestor order and separators.
     * A changed chain/length is a closed failure, never another allocation or
     * an unbounded retry. Existing actual parent references protect lifetime;
     * this function does not turn a snapshot into device currentness. */
    remaining = length - 1;
    depth = 0;
    for (parent = kobj; parent; parent = parent->parent) {
        if (++depth > LSF_DEVICE_UEVENT_MAX_ANCESTORS ||
            !(name = kobject_name(parent)))
            goto changed;
        size = strnlen(name, NAME_MAX + 1);
        if (!size || size > NAME_MAX || size >= remaining)
            goto changed;
        remaining -= size;
        memcpy(path + remaining, name, size);
        path[--remaining] = '/';
    }
    if (remaining)
        goto changed;
    pr_debug("'%s' (%p): %s: path = '%s'\n", kobject_name(kobj),
        kobj, __func__, path);
    return path;
changed:
    (void)lsf_factory_device_uevent_return(path, LSF_DEVICE_UEVENT_KIND_PATH);
    return NULL;
}
