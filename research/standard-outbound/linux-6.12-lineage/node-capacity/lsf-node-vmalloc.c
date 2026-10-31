/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in real mm/vmalloc.c after its native functions. Native scan,
 * clipping, publication, recovery, KASAN and mapping order remain explicit.
 * Physical extents were reserved from the original Node before allocation.
 */
#include <net/lsf_node_capacity_private.h>
#include <asm/pgalloc.h>

int lsf_node_vm_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || IS_ENABLED(CONFIG_KASAN) || IS_ENABLED(CONFIG_KMSAN) || ALLOC_SPLIT_PTLOCKS)
        return -EOPNOTSUPP;
    out[LSF_NODE_VM_POINTERS] = (struct lsf_node_capacity_extent){
        sizeof(struct vm_struct *), __alignof__(struct vm_struct *)};
    out[LSF_NODE_VA_POINTERS] = (struct lsf_node_capacity_extent){
        sizeof(struct vmap_area *), __alignof__(struct vmap_area *)};
    out[LSF_NODE_VM_STRUCT] = (struct lsf_node_capacity_extent){
        sizeof(struct vm_struct), __alignof__(struct vm_struct)};
    out[LSF_NODE_VMAP_AREA] = (struct lsf_node_capacity_extent){
        sizeof(struct vmap_area), __alignof__(struct vmap_area)};
    out[LSF_NODE_P4D_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    out[LSF_NODE_PUD_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    out[LSF_NODE_PMD_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    out[LSF_NODE_PTE_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    return 0;
}

/* All Node VA carriers have this same actual native type. A split carrier can
 * stay in a shared free-space tree after this allocation; its ORIGINAL Node
 * remains owner until a real native free reaches this classifier.
 */
void lsf_node_vmap_cache_free(struct vmap_area *area)
{
    if (!lsf_node_capacity_native_free(area, LSF_NODE_VMAP_AREA))
        kmem_cache_free(vmap_area_cachep, area);
}

static int lsf_node_vmap_splits_prepare(struct lsf_node_capacity *owner)
{
    unsigned int index;

    /* One actual group and one admitted scan: a fit can split its selected
     * free interval once. No global purge/notifier retry is admitted. The real
     * typed object is allocated BEFORE free_vmap_area_lock, never GFP_KERNEL
     * beneath that native spinlock and never borrowed from an ordinary cache.
     */
    for (index = 0; index < 1; ++index) {
        owner->vmap_splits[index] = lsf_node_capacity_take(owner, LSF_NODE_VMAP_AREA,
            sizeof(struct vmap_area), __alignof__(struct vmap_area));
        if (!owner->vmap_splits[index])
            return 0;
    }
    return 1;
}

static struct vmap_area *lsf_node_vmap_split_take(struct lsf_node_capacity *owner)
{
    if (owner->vmap_split_used >= 1)
        return NULL;
    if (lsf_node_capacity_publish(owner->vmap_splits[owner->vmap_split_used],
            LSF_NODE_VMAP_AREA) != 1)
        return NULL;
    return owner->vmap_splits[owner->vmap_split_used++];
}

static __always_inline int
lsf_node_va_clip(struct lsf_node_capacity *owner,
		struct rb_root *root, struct list_head *head,
		struct vmap_area *va, unsigned long nva_start_addr,
		unsigned long size)
{
	struct vmap_area *lva = NULL;
	enum fit_type type = classify_va_fit_type(va, nva_start_addr, size);

	if (type == FL_FIT_TYPE) {
		/*
		 * No need to split VA, it fully fits.
		 *
		 * |               |
		 * V      NVA      V
		 * |---------------|
		 */
		unlink_va_augment(va, root);
		lsf_node_vmap_cache_free(va);
	} else if (type == LE_FIT_TYPE) {
		/*
		 * Split left edge of fit VA.
		 *
		 * |       |
		 * V  NVA  V   R
		 * |-------|-------|
		 */
		va->va_start += size;
	} else if (type == RE_FIT_TYPE) {
		/*
		 * Split right edge of fit VA.
		 *
		 *         |       |
		 *     L   V  NVA  V
		 * |-------|-------|
		 */
		va->va_end = nva_start_addr;
	} else if (type == NE_FIT_TYPE) {
		/*
		 * Split no edge of fit VA.
		 *
		 *     |       |
		 *   L V  NVA  V R
		 * |---|-------|---|
		 */
		lva = lsf_node_vmap_split_take(owner);
		if (!lva)
			return -1;

		/*
		 * Build the remainder.
		 */
		lva->va_start = va->va_start;
		lva->va_end = nva_start_addr;

		/*
		 * Shrink this VA to remaining size.
		 */
		va->va_start = nva_start_addr + size;
	} else {
		return -1;
	}

	if (type != FL_FIT_TYPE) {
		augment_tree_propagate_from(va);

		if (lva)	/* type == NE_FIT_TYPE */
			insert_vmap_area_augment(lva, &va->rb_node, root, head);
	}

	return 0;
}

struct vm_struct **lsf_node_pcpu_vm_areas(struct lsf_node_capacity *owner,
				     const unsigned long *offsets,
				     const size_t *sizes, int nr_vms,
				     size_t align)
{
	const unsigned long vmalloc_start = ALIGN(VMALLOC_START, align);
	const unsigned long vmalloc_end = VMALLOC_END & ~(align - 1);
	struct vmap_area **vas, *va;
	struct vm_struct **vms;
	int area, area2, last_area, term_area;
	unsigned long base, start, size, end, last_end, orig_start, orig_end;

	if (lsf_node_capacity_checkpoint(owner) || IS_ENABLED(CONFIG_KASAN) ||
	    IS_ENABLED(CONFIG_KMSAN) || nr_vms != 1 || !offsets || !sizes ||
	    offsets[0] != owner->group_offset || sizes[0] != owner->group_bytes ||
	    align != owner->atom_bytes || !lsf_node_vmap_splits_prepare(owner))
		return NULL;

	/* verify parameters and allocate data structures */
	BUG_ON(offset_in_page(align) || !is_power_of_2(align));
	for (last_area = 0, area = 0; area < nr_vms; area++) {
		start = offsets[area];
		end = start + sizes[area];

		/* is everything aligned properly? */
		BUG_ON(!IS_ALIGNED(offsets[area], align));
		BUG_ON(!IS_ALIGNED(sizes[area], align));

		/* detect the area with the highest address */
		if (start > offsets[last_area])
			last_area = area;

		for (area2 = area + 1; area2 < nr_vms; area2++) {
			unsigned long start2 = offsets[area2];
			unsigned long end2 = start2 + sizes[area2];

			BUG_ON(start2 < end && start < end2);
		}
	}
	last_end = offsets[last_area] + sizes[last_area];

	if (vmalloc_end - vmalloc_start < last_end) {
		WARN_ON(true);
		return NULL;
	}

	vms = lsf_node_capacity_take(owner, LSF_NODE_VM_POINTERS,
		nr_vms * sizeof(vms[0]), __alignof__(*vms));
	vas = lsf_node_capacity_take(owner, LSF_NODE_VA_POINTERS,
		nr_vms * sizeof(vas[0]), __alignof__(*vas));
	if (!vas || !vms)
		goto err_free2;

	for (area = 0; area < nr_vms; area++) {
		vas[area] = lsf_node_capacity_take(owner, LSF_NODE_VMAP_AREA,
			sizeof(struct vmap_area), __alignof__(struct vmap_area));
		vms[area] = lsf_node_capacity_take(owner, LSF_NODE_VM_STRUCT,
			sizeof(struct vm_struct), __alignof__(struct vm_struct));
		if (!vas[area] || !vms[area])
			goto err_free;
	}
	if (lsf_node_capacity_checkpoint(owner))
		goto err_free;
	spin_lock(&free_vmap_area_lock);

	/* start scanning - we scan from the top, begin with the last area */
	area = term_area = last_area;
	start = offsets[area];
	end = start + sizes[area];

	va = pvm_find_va_enclose_addr(vmalloc_end);
	base = pvm_determine_end_from_reverse(&va, align) - end;

	while (true) {
		if (lsf_node_capacity_checkpoint(owner))
			goto expired;
		/*
		 * base might have underflowed, add last_end before
		 * comparing.
		 */
		if (base + last_end < vmalloc_start + last_end)
			goto overflow;

		/*
		 * Fitting base has not been found.
		 */
		if (va == NULL)
			goto overflow;

		/*
		 * If required width exceeds current VA block, move
		 * base downwards and then recheck.
		 */
		if (base + end > va->va_end) {
			base = pvm_determine_end_from_reverse(&va, align) - end;
			term_area = area;
			continue;
		}

		/*
		 * If this VA does not fit, move base downwards and recheck.
		 */
		if (base + start < va->va_start) {
			va = node_to_va(rb_prev(&va->rb_node));
			base = pvm_determine_end_from_reverse(&va, align) - end;
			term_area = area;
			continue;
		}

		/*
		 * This area fits, move on to the previous one.  If
		 * the previous one is the terminal one, we're done.
		 */
		area = (area + nr_vms - 1) % nr_vms;
		if (area == term_area)
			break;

		start = offsets[area];
		end = start + sizes[area];
		va = pvm_find_va_enclose_addr(base + end);
	}

	/* we've found a fitting base, insert all va's */
	for (area = 0; area < nr_vms; area++) {
		int ret;

		start = base + offsets[area];
		size = sizes[area];

		va = pvm_find_va_enclose_addr(start);
		if (WARN_ON_ONCE(va == NULL))
			/* It is a BUG(), but trigger recovery instead. */
			goto recovery;

		if (lsf_node_capacity_checkpoint(owner))
			goto expired;
		ret = lsf_node_va_clip(owner, &free_vmap_area_root,
			&free_vmap_area_list, va, start, size);
		if (WARN_ON_ONCE(unlikely(ret)))
			/* It is a BUG(), but trigger recovery instead. */
			goto recovery;

		/* Allocated area. */
		va = vas[area];
		va->va_start = start;
		va->va_end = start + size;
	}

	spin_unlock(&free_vmap_area_lock);

	/* populate the kasan shadow space */
	for (area = 0; area < nr_vms; area++) {
		if (kasan_populate_vmalloc(vas[area]->va_start, sizes[area]))
			goto err_free_shadow;
	}

	/* insert all vm's */
	for (area = 0; area < nr_vms; area++) {
		struct vmap_node *vn = addr_to_node(vas[area]->va_start);

		if (lsf_node_capacity_publish(vas[area], LSF_NODE_VMAP_AREA) != 1)
			goto err_free_shadow;
		spin_lock(&vn->busy.lock);
		if (lsf_node_capacity_checkpoint(owner)) {
			spin_unlock(&vn->busy.lock);
			goto err_free_shadow;
		}
		insert_vmap_area(vas[area], &vn->busy.root, &vn->busy.head);
		setup_vmalloc_vm(vms[area], vas[area], VM_ALLOC,
				 lsf_node_pcpu_vm_areas);
		spin_unlock(&vn->busy.lock);
	}

	/*
	 * Mark allocated areas as accessible. Do it now as a best-effort
	 * approach, as they can be mapped outside of vmalloc code.
	 * With hardware tag-based KASAN, marking is skipped for
	 * non-VM_ALLOC mappings, see __kasan_unpoison_vmalloc().
	 */
	kasan_unpoison_vmap_areas(vms, nr_vms, KASAN_VMALLOC_PROT_NORMAL);

	lsf_node_capacity_native_free(vas, LSF_NODE_VA_POINTERS);
	return vms;

recovery:
	/*
	 * Remove previously allocated areas. There is no
	 * need in removing these areas from the busy tree,
	 * because they are inserted only on the final step
	 * and when pcpu_get_vm_areas() is success.
	 */
	while (area--) {
		orig_start = vas[area]->va_start;
		orig_end = vas[area]->va_end;
		va = merge_or_add_vmap_area_augment(vas[area], &free_vmap_area_root,
				&free_vmap_area_list);
		if (va)
			kasan_release_vmalloc(orig_start, orig_end,
				va->va_start, va->va_end,
				KASAN_VMALLOC_PAGE_RANGE | KASAN_VMALLOC_TLB_FLUSH);
		vas[area] = NULL;
	}

expired:
	spin_unlock(&free_vmap_area_lock);
	goto err_free;

overflow:
	spin_unlock(&free_vmap_area_lock);
	/* No admitted Node origin exists for global purge notifiers. Fail before
	 * publication and retain the original partial allocation instead. */
	goto err_free;

err_free:
	for (area = 0; area < nr_vms; area++) {
		if (vas[area])
			lsf_node_vmap_cache_free(vas[area]);

		lsf_node_capacity_native_free(vms[area], LSF_NODE_VM_STRUCT);
	}
err_free2:
	lsf_node_capacity_native_free(vas, LSF_NODE_VA_POINTERS);
	lsf_node_capacity_native_free(vms, LSF_NODE_VM_POINTERS);
	return NULL;

err_free_shadow:
	spin_lock(&free_vmap_area_lock);
	/*
	 * We release all the vmalloc shadows, even the ones for regions that
	 * hadn't been successfully added. This relies on kasan_release_vmalloc
	 * being able to tolerate this case.
	 */
	for (area = 0; area < nr_vms; area++) {
		orig_start = vas[area]->va_start;
		orig_end = vas[area]->va_end;
		va = merge_or_add_vmap_area_augment(vas[area], &free_vmap_area_root,
				&free_vmap_area_list);
		if (va)
			kasan_release_vmalloc(orig_start, orig_end,
				va->va_start, va->va_end,
				KASAN_VMALLOC_PAGE_RANGE | KASAN_VMALLOC_TLB_FLUSH);
		vas[area] = NULL;
		lsf_node_capacity_native_free(vms[area], LSF_NODE_VM_STRUCT);
	}
	spin_unlock(&free_vmap_area_lock);
	lsf_node_capacity_native_free(vas, LSF_NODE_VA_POINTERS);
	lsf_node_capacity_native_free(vms, LSF_NODE_VM_POINTERS);
	return NULL;
}

/* Native page-table constructor and mapping variants. The ordinary functions
 * above are untouched; all allocator contexts are explicit, not thread-local.
 * The selected profile requires native x86 paging without paravirt allocation
 * callbacks or an out-of-line split page-table lock allocator.
 */
#if !defined(CONFIG_X86_64) || CONFIG_PGTABLE_LEVELS != 5 || defined(CONFIG_PARAVIRT_XXL)
#error "Node native mapping requires the selected x86-64 paging profile"
#endif
#include <asm/pgalloc.h>

static int lsf_node_p4d_alloc(struct lsf_node_capacity *owner, struct mm_struct *mm, pgd_t *pgd, unsigned long address)
{
	struct lsf_node_native_ticket ticket;
	p4d_t *new;
	int error;

	if (mm != &init_mm)
		return -EOPNOTSUPP;
	error = lsf_node_capacity_reserve(owner, LSF_NODE_P4D_PAGE, &ticket);
	if (error)
		return error;
	if (ticket.bytes != PAGE_SIZE) {
		lsf_node_capacity_commit(owner, &ticket, NULL);
		return -EOPNOTSUPP;
	}
	new = p4d_alloc_one(mm, address);
	error = lsf_node_capacity_commit(owner, &ticket, new);
	if (error)
		return error;
	if (!new)
		return -ENOMEM;

	if (lsf_node_capacity_publish(new, LSF_NODE_P4D_PAGE) != 1)
		return -EOPNOTSUPP;

	spin_lock(&mm->page_table_lock);
	if (lsf_node_capacity_checkpoint(owner)) {
		spin_unlock(&mm->page_table_lock);
		return -EOPNOTSUPP;
	}
	if (pgd_present(*pgd)) {	/* Another has populated it */
		p4d_free(mm, new);
	} else {
		smp_wmb(); /* See comment in pmd_install() */
		pgd_populate(mm, pgd, new);
	}
	spin_unlock(&mm->page_table_lock);
	return 0;
}

static int lsf_node_pud_alloc(struct lsf_node_capacity *owner, struct mm_struct *mm, p4d_t *p4d, unsigned long address)
{
	struct lsf_node_native_ticket ticket;
	pud_t *new;
	int error;

	if (mm != &init_mm)
		return -EOPNOTSUPP;
	error = lsf_node_capacity_reserve(owner, LSF_NODE_PUD_PAGE, &ticket);
	if (error)
		return error;
	if (ticket.bytes != PAGE_SIZE) {
		lsf_node_capacity_commit(owner, &ticket, NULL);
		return -EOPNOTSUPP;
	}
	new = pud_alloc_one(mm, address);
	error = lsf_node_capacity_commit(owner, &ticket, new);
	if (error)
		return error;
	if (!new)
		return -ENOMEM;

	if (lsf_node_capacity_publish(new, LSF_NODE_PUD_PAGE) != 1)
		return -EOPNOTSUPP;

	spin_lock(&mm->page_table_lock);
	if (lsf_node_capacity_checkpoint(owner)) {
		spin_unlock(&mm->page_table_lock);
		return -EOPNOTSUPP;
	}
	if (!p4d_present(*p4d)) {
		mm_inc_nr_puds(mm);
		smp_wmb(); /* See comment in pmd_install() */
		p4d_populate(mm, p4d, new);
	} else	/* Another has populated it */
		pud_free(mm, new);
	spin_unlock(&mm->page_table_lock);
	return 0;
}

static int lsf_node_pmd_alloc(struct lsf_node_capacity *owner, struct mm_struct *mm, pud_t *pud, unsigned long address)
{
	spinlock_t *ptl;
	struct lsf_node_native_ticket ticket;
	pmd_t *new;
	int error;

	if (mm != &init_mm)
		return -EOPNOTSUPP;
	error = lsf_node_capacity_reserve(owner, LSF_NODE_PMD_PAGE, &ticket);
	if (error)
		return error;
	if (ticket.bytes != PAGE_SIZE) {
		lsf_node_capacity_commit(owner, &ticket, NULL);
		return -EOPNOTSUPP;
	}
	new = pmd_alloc_one(mm, address);
	error = lsf_node_capacity_commit(owner, &ticket, new);
	if (error)
		return error;
	if (!new)
		return -ENOMEM;

	if (lsf_node_capacity_publish(new, LSF_NODE_PMD_PAGE) != 1)
		return -EOPNOTSUPP;

	ptl = pud_lock(mm, pud);
	if (lsf_node_capacity_checkpoint(owner)) {
		spin_unlock(ptl);
		return -EOPNOTSUPP;
	}
	if (!pud_present(*pud)) {
		mm_inc_nr_pmds(mm);
		smp_wmb(); /* See comment in pmd_install() */
		pud_populate(mm, pud, new);
	} else {	/* Another has populated it */
		pmd_free(mm, new);
	}
	spin_unlock(ptl);
	return 0;
}

static int lsf_node_pte_alloc(struct lsf_node_capacity *owner, pmd_t *pmd)
{
	struct lsf_node_native_ticket ticket;
	pte_t *new;
	int error;
	error = lsf_node_capacity_reserve(owner, LSF_NODE_PTE_PAGE, &ticket);
	if (error)
		return error;
	if (ticket.bytes != PAGE_SIZE) {
		lsf_node_capacity_commit(owner, &ticket, NULL);
		return -EOPNOTSUPP;
	}
	new = pte_alloc_one_kernel(&init_mm);
	error = lsf_node_capacity_commit(owner, &ticket, new);
	if (error)
		return error;
	if (!new)
		return -ENOMEM;

	if (lsf_node_capacity_publish(new, LSF_NODE_PTE_PAGE) != 1)
		return -EOPNOTSUPP;

	spin_lock(&init_mm.page_table_lock);
	if (lsf_node_capacity_checkpoint(owner)) {
		spin_unlock(&init_mm.page_table_lock);
		return -EOPNOTSUPP;
	}
	if (likely(pmd_none(*pmd))) {	/* Has another populated it ? */
		smp_wmb(); /* See comment in pmd_install() */
		pmd_populate_kernel(&init_mm, pmd, new);
		new = NULL;
	}
	spin_unlock(&init_mm.page_table_lock);
	if (new)
		pte_free_kernel(&init_mm, new);
	return 0;
}

static inline p4d_t *lsf_node_p4d_alloc_track(struct lsf_node_capacity *owner,
				     struct mm_struct *mm, pgd_t *pgd,
				     unsigned long address,
				     pgtbl_mod_mask *mod_mask)
{
	if (unlikely(pgd_none(*pgd))) {
		if (lsf_node_p4d_alloc(owner, mm, pgd, address))
			return NULL;
		*mod_mask |= PGTBL_PGD_MODIFIED;
	}

	return p4d_offset(pgd, address);
}

static inline pud_t *lsf_node_pud_alloc_track(struct lsf_node_capacity *owner,
				     struct mm_struct *mm, p4d_t *p4d,
				     unsigned long address,
				     pgtbl_mod_mask *mod_mask)
{
	if (unlikely(p4d_none(*p4d))) {
		if (lsf_node_pud_alloc(owner, mm, p4d, address))
			return NULL;
		*mod_mask |= PGTBL_P4D_MODIFIED;
	}

	return pud_offset(p4d, address);
}

static inline pmd_t *lsf_node_pmd_alloc_track(struct lsf_node_capacity *owner,
				     struct mm_struct *mm, pud_t *pud,
				     unsigned long address,
				     pgtbl_mod_mask *mod_mask)
{
	if (unlikely(pud_none(*pud))) {
		if (lsf_node_pmd_alloc(owner, mm, pud, address))
			return NULL;
		*mod_mask |= PGTBL_PUD_MODIFIED;
	}

	return pmd_offset(pud, address);
}

static pte_t *lsf_node_pte_alloc_track(struct lsf_node_capacity *owner,
    pmd_t *pmd, unsigned long address, pgtbl_mod_mask *mask)
{
    if (unlikely(pmd_none(*pmd))) {
        if (lsf_node_pte_alloc(owner, pmd))
            return NULL;
        *mask |= PGTBL_PMD_MODIFIED;
    }
    return pte_offset_kernel(pmd, address);
}

static int lsf_node_vmap_pages_pte_range(struct lsf_node_capacity *owner, pmd_t *pmd, unsigned long addr,
		unsigned long end, pgprot_t prot, struct page **pages, int *nr,
		pgtbl_mod_mask *mask)
{
	int err = 0;
	pte_t *pte;

	/*
	 * nr is a running index into the array which helps higher level
	 * callers keep track of where we're up to.
	 */

	pte = lsf_node_pte_alloc_track(owner, pmd, addr, mask);
	if (!pte)
		return -ENOMEM;
	do {
		struct page *page = pages[*nr];

		if (WARN_ON(!pte_none(ptep_get(pte)))) {
			err = -EBUSY;
			break;
		}
		if (WARN_ON(!page)) {
			err = -ENOMEM;
			break;
		}
		if (WARN_ON(!pfn_valid(page_to_pfn(page)))) {
			err = -EINVAL;
			break;
		}

		if (lsf_node_capacity_checkpoint(owner)) {
			err = -EOPNOTSUPP;
			break;
		}
		set_pte_at(&init_mm, addr, pte, mk_pte(page, prot));
		(*nr)++;
	} while (pte++, addr += PAGE_SIZE, addr != end);
	*mask |= PGTBL_PTE_MODIFIED;

	return err;
}

static int lsf_node_vmap_pages_pmd_range(struct lsf_node_capacity *owner, pud_t *pud, unsigned long addr,
		unsigned long end, pgprot_t prot, struct page **pages, int *nr,
		pgtbl_mod_mask *mask)
{
	pmd_t *pmd;
	unsigned long next;

	pmd = lsf_node_pmd_alloc_track(owner, &init_mm, pud, addr, mask);
	if (!pmd)
		return -ENOMEM;
	do {
		next = pmd_addr_end(addr, end);
		if (lsf_node_vmap_pages_pte_range(owner, pmd, addr, next, prot, pages, nr, mask))
			return -ENOMEM;
	} while (pmd++, addr = next, addr != end);
	return 0;
}

static int lsf_node_vmap_pages_pud_range(struct lsf_node_capacity *owner, p4d_t *p4d, unsigned long addr,
		unsigned long end, pgprot_t prot, struct page **pages, int *nr,
		pgtbl_mod_mask *mask)
{
	pud_t *pud;
	unsigned long next;

	pud = lsf_node_pud_alloc_track(owner, &init_mm, p4d, addr, mask);
	if (!pud)
		return -ENOMEM;
	do {
		next = pud_addr_end(addr, end);
		if (lsf_node_vmap_pages_pmd_range(owner, pud, addr, next, prot, pages, nr, mask))
			return -ENOMEM;
	} while (pud++, addr = next, addr != end);
	return 0;
}

static int lsf_node_vmap_pages_p4d_range(struct lsf_node_capacity *owner, pgd_t *pgd, unsigned long addr,
		unsigned long end, pgprot_t prot, struct page **pages, int *nr,
		pgtbl_mod_mask *mask)
{
	p4d_t *p4d;
	unsigned long next;

	p4d = lsf_node_p4d_alloc_track(owner, &init_mm, pgd, addr, mask);
	if (!p4d)
		return -ENOMEM;
	do {
		next = p4d_addr_end(addr, end);
		if (lsf_node_vmap_pages_pud_range(owner, p4d, addr, next, prot, pages, nr, mask))
			return -ENOMEM;
	} while (p4d++, addr = next, addr != end);
	return 0;
}

static int lsf_node_vmap_small_pages_range_noflush(struct lsf_node_capacity *owner, unsigned long addr, unsigned long end,
		pgprot_t prot, struct page **pages)
{
	unsigned long start = addr;
	pgd_t *pgd;
	unsigned long next;
	int err = 0;
	int nr = 0;
	pgtbl_mod_mask mask = 0;

	BUG_ON(addr >= end);
	pgd = pgd_offset_k(addr);
	do {
		next = pgd_addr_end(addr, end);
		if (pgd_bad(*pgd))
			mask |= PGTBL_PGD_MODIFIED;
		err = lsf_node_vmap_pages_p4d_range(owner, pgd, addr, next, prot, pages, &nr, &mask);
		if (err)
			break;
	} while (pgd++, addr = next, addr != end);

	if (mask & ARCH_PAGE_TABLE_SYNC_MASK)
		arch_sync_kernel_mappings(start, end);

	return err;
}

int lsf_node_pcpu_map(struct lsf_node_capacity *owner, unsigned long address,
    struct page **pages, unsigned int count)
{
    struct lsf_node_capacity *actual;
    struct vm_struct **vms;
    unsigned long start, base, expected, end;

    if (lsf_node_capacity_checkpoint(owner) || count != 1 || !pages ||
        !pages[0] || !IS_ALIGNED(address, PAGE_SIZE) ||
        check_add_overflow(address, PAGE_SIZE, &end) ||
        lsf_node_capacity_native_owned(owner->pcpu_vms, LSF_NODE_VM_POINTERS,
            &actual) != 1 || actual != owner)
        return -EOPNOTSUPP;
    vms = owner->pcpu_vms;
    if (lsf_node_capacity_native_owned(vms[0], LSF_NODE_VM_STRUCT, &actual) != 1 ||
        actual != owner || lsf_node_capacity_native_owned(page_address(pages[0]),
            LSF_NODE_PCPU_DATA, &actual) != 1 || actual != owner)
        return -EOPNOTSUPP;
    start = (unsigned long)vms[0]->addr;
    if (vms[0]->size != owner->group_bytes ||
        check_sub_overflow(start, owner->group_offset, &base) ||
        check_add_overflow(base, owner->unit_offset, &expected) ||
        address != expected || address < start ||
        vms[0]->size < PAGE_SIZE || address - start > vms[0]->size - PAGE_SIZE)
        return -EOPNOTSUPP;
    /* This is the real native small-page walker, with explicit prepaid
     * directory/leaf allocation and the original architecture sync path.
     */
    return lsf_node_vmap_small_pages_range_noflush(owner, address, end,
        PAGE_KERNEL, pages);
}
