"""Exact source/predicate controls, not Linux execution or PTE readiness proof."""
import ast
import hashlib
import re
import unittest

from tools import host_stream_kernel_vmap_extent as previous
from tools import host_stream_kernel_vmap_fit as source
from tools.host_stream_kernel_cleanup_native import function
from tools.tests.test_host_stream_kernel_stack_alignment import arithmetic, selected


def inputs():
    return previous.transform(selected())


def actual_fit(body, start, end, lower=0x100000, upper=0x200000):
    """Interpret every actual pure C arithmetic statement through final admission.

    The shared control interpreter accepts only closed integer/boolean syntax.
    Unknown tokens refuse; there is no executable-source evaluation.
    """
    text = body[body.index('    unsigned long start = area->va_start;\n'):
                body.index('    if (reservation_size)\n')]
    token = re.compile(r'\s*(?:if \((.*?)\)\s*return (\d+)u;'
        r'|(?:unsigned long )?([a-z]+) (\+?=) ([^;]+);'
        r'|unsigned long aligned, padding, size = (THREAD_SIZE \+ PAGE_SIZE);)', re.S)
    context = {'area_start':start, 'area_end':end, 'PAGE_SIZE':4096,
        'THREAD_SIZE':16384, 'THREAD_ALIGN':16384, 'VMALLOC_START':lower,
        'VMALLOC_END':upper, 'MAXIMUM':2**64-1,
        'IS_ALIGNED':lambda value, align:value % align == 0,
        'ALIGN':lambda value, align:(value+align-1) & ~(align-1)}
    position = 0
    for row in token.finditer(text):
        if text[position:row.start()].strip():
            raise ValueError('unknown-fit-source')
        position = row.end()
        expression = row[1] or row[5] or row[6]
        expression = expression.replace('area->va_start','area_start').replace('area->va_end','area_end')
        expression = expression.replace('~0UL','MAXIMUM')
        # These two divisions are exact fixed profile constants, not arbitrary syntax.
        expression = expression.replace('THREAD_SIZE / PAGE_SIZE','4').replace('THREAD_ALIGN / PAGE_SIZE','4')
        expression = re.sub(r'\b(\d+)u\b',r'\1',expression)
        expression = expression.replace('||',' or ').replace('&&',' and ')
        expression = re.sub(r'!(?!=)',' not ',expression).strip()
        value = arithmetic(ast.parse(expression,mode='eval'),context)
        if row[1]:
            if value:
                return int(row[2]),None
        elif row[6]:
            context['size'] = value
        elif row[4] == '+=':
            context[row[3]] += value
        else:
            context[row[3]] = value
    if text[position:].strip():
        raise ValueError('unknown-fit-source')
    return 0,context['size']


def lookup(body, fit, nodes, node, lower=0x100000, upper=0x200000):
    """Source-bound scalar traversal model; does not model actual Linux metadata.

    Exact current C body must match the reviewed traversal before modeling it.
    The predicate itself is interpreted from the actual generated C above.
    """
    if body != function(source.SELECTOR,'static struct vmap_area *lsf_cleanup_stack_extent('):
        raise ValueError('unknown-fit-walk-source')
    previous_node = None;work = 0
    def maximum(index):
        return 0 if index is None else nodes[index]['max']
    while node is not None and work < 64:
        area = nodes[node];parent = area['parent'];consider = False;work += 1
        if previous_node == parent:
            if area['max'] <= 20480:
                previous_node,node = node,parent;continue
            if area['start'] < lower:
                next_node = area['right'] if maximum(area['right']) > 20480 else parent
                previous_node,node = node,next_node;continue
            if maximum(area['left']) > 20480:
                previous_node,node = node,area['left'];continue
            consider = True
        elif previous_node == area['left']:
            consider = True
        elif previous_node != area['right']:
            return None,work
        if consider and area['start'] < upper:
            if work == 64:
                return None,work
            work += 1
            if actual_fit(fit,area['start'],area['end'],lower,upper)[0] == 0:
                return node,work
            if maximum(area['right']) > 20480:
                previous_node,node = node,area['right'];continue
        previous_node,node = node,parent
    return None,work


def row(start,end,*,parent=None,left=None,right=None,maximum=None):
    return dict(start=start,end=end,parent=parent,left=left,right=right,
                max=end-start if maximum is None else maximum)


class VmapFitSource(unittest.TestCase):
    def setUp(self):
        self.before = inputs()
        self.text = source.transform(self.before)[source.NAME].decode()
        self.fit = function(self.text,'static unsigned int lsf_cleanup_stack_fit(')
        self.walk = function(self.text,'static struct vmap_area *lsf_cleanup_stack_extent(')

    def test_exact_e518_preimage_shared_predicate_and_unchanged_mapping_retirement(self):
        raw = self.before[source.NAME]
        self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),source.PREIMAGE)
        after = source.transform({**self.before,'unrelated-source':b'unchanged'})
        self.assertEqual([n for n in self.before if after[n] != self.before[n]],[source.NAME])
        self.assertEqual(after['unrelated-source'],b'unchanged')
        for wrong in ({}, {**self.before,source.NAME:raw+b'\n'}, after):
            with self.assertRaisesRegex(ValueError,'compiled-e518-preimage'):
                source.transform(wrong)
        old = raw.decode()
        for signature in ('static int lsf_cleanup_stack_restore(',
                'static void lsf_cleanup_stack_busy(', 'static int lsf_cleanup_stack_unmap(',
                'static pte_t *lsf_cleanup_existing_pte_observed(',
                'int lsf_prepaid_cleanup_stack_foreign_unmap('):
            self.assertEqual(function(old.split('\n#else\n',1)[0],signature),
                             function(self.text.split('\n#else\n',1)[0],signature))
        self.assertEqual(old.split('int lsf_prepaid_cleanup_stack_create_observed(',1)[1],
                         self.text.split('int lsf_prepaid_cleanup_stack_create_observed(',1)[1])
        carve = function(self.text,'static int lsf_cleanup_stack_carve(')
        self.assertEqual(carve.count('lsf_cleanup_stack_extent()'),1)
        self.assertEqual(carve.count('lsf_cleanup_stack_fit(free, &size)'),1)
        self.assertIn('LSF_FAILURE_CARVE_EXTENT, detail, result',carve)
        self.assertLess(carve.index('lsf_cleanup_stack_fit('),carve.index('stack->area.va_start ='))
        self.assertIn('free->va_start += size;',carve)
        self.assertNotIn('free->va_end =',carve)
        self.assertEqual(self.walk.count('lsf_cleanup_stack_fit(area, NULL)'),1)
        for forbidden in ('rb_next(', 'kmem_cache_', 'va_clip(', 'purge_', 'pte_', 'alloc('):
            self.assertNotIn(forbidden,self.walk)

    def test_actual_shared_arithmetic_all_residues_tail_window_exact_fit_and_overflow(self):
        for residue in range(4):
            start = 0x100000+residue*4096
            size = ((start+16383) & ~16383)-start+20480
            with self.subTest(residue=residue):
                self.assertEqual(actual_fit(self.fit,start,start+size+4096),(0,size))
                self.assertEqual(actual_fit(self.fit,start,start+size),(5,None))
                self.assertEqual(actual_fit(self.fit,start,start+size-4096),(5,None))
                # Actual original tail metadata may extend to ULONG_MAX, unchanged.
                self.assertEqual(actual_fit(self.fit,start,2**64-1,upper=start+size),(0,size))
                self.assertEqual(actual_fit(self.fit,start,2**64-1,upper=start+size-1),(3,None))
        for start,end,detail in ((0x100001,0x180000,1),(0xff000,0x180000,2),
                (0x200000,2**64-1,3),(0x104000,0x104000,4)):
            self.assertEqual(actual_fit(self.fit,start,end),(detail,None))
        self.assertEqual(actual_fit(self.fit,2**64-4096,2**64-1,lower=0,upper=2**64-1),(6,None))
        with self.assertRaisesRegex(ValueError,'unknown-carve-expression'):
            actual_fit(self.fit.replace('size += padding;','size = unknown(padding);'),0x100000,0x180000)

    def test_augmented_walk_skips_padding_gaps_chooses_one_eligible_original_left_edge(self):
        nodes = {'gap':row(0x104000,0x108000,left='outside',right='tail',maximum=2**64-1),
            'outside':row(1,0x102000,parent='gap'),
            'tail':row(0x120000,2**64-1,parent='gap')}
        self.assertEqual(lookup(self.walk,self.fit,nodes,'gap'),('tail',6))
        # A large but near-window-end extent cannot consume its required prefix.
        nodes['tail'] = row(0x1ff000,2**64-1,parent='gap')
        self.assertIsNone(lookup(self.walk,self.fit,nodes,'gap')[0])
        # Subtree maximum equal to minimum cannot leave a strict right remainder.
        self.assertEqual(lookup(self.walk,self.fit,{0:row(0x100000,0x105000)},0),(None,1))
        # In-order selection returns the lower eligible left edge, never a later one.
        nodes = {'root':row(0x140000,0x180000,left='left',right='right',maximum=2**64-1),
            'left':row(0x100000,0x140000,parent='root'),
            'right':row(0x180000,2**64-1,parent='root')}
        self.assertEqual(lookup(self.walk,self.fit,nodes,'root'),('left',3))
        # Earlier return is before any PTE test: the search has no mapping fallback.
        self.assertNotIn('lsf_cleanup_existing_pte',self.walk)

    def test_one_combined_64_unit_budget_counts_predicates_and_refuses_cycles(self):
        for below,expected in ((62,'fit'),(63,None)):
            nodes={i:row(i+1,i+2,parent=i-1 if i else None,
                right=i+1 if i+1<below else 'fit',maximum=2**64-1) for i in range(below)}
            nodes['fit']=row(0x100000,2**64-1,parent=below-1)
            with self.subTest(below=below):
                self.assertEqual(lookup(self.walk,self.fit,nodes,0),(expected,64))
        cycle={0:row(1,2,parent=0,right=0,maximum=2**64-1)}
        self.assertEqual(lookup(self.walk,self.fit,cycle,0),(None,64))
        self.assertEqual(lookup(self.walk,self.fit,{},None),(None,0))
        with self.assertRaisesRegex(ValueError,'unknown-fit-walk-source'):
            lookup(self.walk.replace('++work;','work += 0;',1),self.fit,{},None)


if __name__ == '__main__':
    unittest.main()
