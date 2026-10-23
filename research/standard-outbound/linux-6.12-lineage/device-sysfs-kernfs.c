/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the real kernfs dir TU after its original headers. This callback
 * runs at the original RCU point. It does not discharge the bank or pretend an
 * earlier unlink/ID removal returned any retained shared radix-tree object. */
void lsf_prepaid_device_kernfs_free(struct kernfs_node *kn)
{
    struct lsf_device_registration_source source;
    if (lsf_factory_device_sysfs_iattrs(kn, 0) != 1 ||
        lsf_factory_device_registration_return_begin(kn,
            LSF_REGISTRATION_KIND_NODE, &source) != 1)
        return;
    if (lsf_factory_device_sysfs_release(source, kn->name,
            LSF_REGISTRATION_KIND_NAME) != 1)
        return;
    (void)lsf_factory_device_registration_return_finish(source);
}
