"""Exact source/guard evidence only; no compiled C, Linux or refund claim."""
import ast
import re
import unittest

from tools import host_stream_kernel_retirement_observation as source
from tools.host_stream_kernel_cleanup_native import function
from tools.tests.test_host_stream_kernel_task_identity_geometry import calculate


def fragment():
    return (source.OWNED/'factory-retirement-observation.c').read_text()


def evaluate(expression, values):
    expression = expression.replace('lsf_factory_actor(file)', 'actor')
    expression = expression.replace('READ_ONCE(factory.uncertain)', 'factory.uncertain')
    expression = re.sub(r'lsf_device_record\(&factory.pool, factory.device->key,\s*'
        r'factory.device->root, LSF_DEVICE_ROOT\)', 'root_record', expression)
    expression = expression.replace('file->private_data == &lsf_retirement', 'private_file')
    expression = expression.replace('task_tgid(current)', 'current_tgid')
    expression = expression.replace('current_cred()', 'current_cred')
    expression = expression.replace('current->nsproxy->net_ns', 'current_net')
    for token in sorted(set(re.findall(r'\b(?:factory|lsf_retirement|actors|current|file)'
            r'(?:(?:\.|->)[a-z0-9_]+)+', expression)), key=len, reverse=True):
        expression = expression.replace(token,token.replace('->','_').replace('.','_'))
    expression = re.sub(r'\b([0-9]+)u\b',r'\1',expression)
    expression = expression.replace('&&',' and ').replace('||',' or ')
    expression = re.sub(r'!(?!=)',' not ',expression)
    return calculate(ast.parse(' '.join(expression.split()),mode='eval'),values)


class RetirementObservationSource(unittest.TestCase):
    def test_whole_authentication_and_inverse_keep_original_release_and_every_unrelated_input(self):
        before=source.original_sources()
        before['unrelated.c']=b'original unrelated whole source\n'
        after=source.transform(before)
        self.assertEqual({name for name in after if after[name]!=before.get(name)},
            {'net/factory.c','net/factory-cleanup-root-final-free.c',source.FRAGMENT})
        self.assertEqual(after['unrelated.c'],before['unrelated.c'])
        for signature in ('static int lsf_factory_release(','static int lsf_factory_actor('):
            self.assertEqual(function(after['net/factory.c'].decode(),signature),
                function(before['net/factory.c'].decode(),signature))
        for name in (*source.preimages()['parentDerived'],*source.preimages()['readOnlyLayouts']):
            for wrong in (None,before[name]+b'\n'):
                changed=dict(before)
                if wrong is None:del changed[name]
                else:changed[name]=wrong
                with self.subTest(name=name,missing=wrong is None),self.assertRaises(ValueError):
                    source.transform(changed)
        with self.assertRaises(ValueError):source.transform(after)

    def test_actual_mint_guard_refuses_every_wrong_original_owner_or_birth_operand(self):
        body=function(fragment(),'static long lsf_factory_retirement_ioctl(')
        guard=re.search(r'if \((!lsf_factory_actor\(file\).*?)\)\n        goto unlock_pool;',body,re.S)[1]
        values=dict(actor=1,factory_opened=1,factory_pages=1,factory_device=1,
            factory_mm=1,factory_tgid=1,factory_cred=1,factory_net=1,
            factory_device_bootstrap_state=2,factory_device_bootstrap_busy=0,
            factory_device_bootstrap_error=0,factory_device_bootstrap_expires_ns=123,
            factory_uncertain=0,factory_pool_poisoned=0,lsf_retirement_phase=0,
            factory_device_key_slot=63,factory_device_key_generation=1,
            factory_device_root_slot=1,factory_device_root_generation=2,root_record=1,
            LSF_DEVICE_OWNER_SLOT=63,LSF_FACTORY_BOOTSTRAP_READY=2,LSF_RETIREMENT_UNUSED=0)
        self.assertFalse(evaluate(guard,values))
        for name,value in values.items():
            if name.isupper():continue
            wrong=0 if value else 1
            with self.subTest(operand=name):
                self.assertTrue(evaluate(guard,{**values,name:wrong}))

    def test_actual_actor_guard_preserves_private_file_mm_tgid_both_creds_and_net(self):
        body=function(fragment(),'static int lsf_retirement_actor_locked(')
        guard=re.search(r'    return (.*?);',body,re.S)[1]
        values=dict(private_file=1,lsf_retirement_phase=2,LSF_RETIREMENT_BOUND=2,
            LSF_RETIREMENT_RETURNED=3,actors_mm=11,actors_tgid=12,actors_cred=13,
            actors_net=14,current_mm=11,current_tgid=12,current_cred=13,file_f_cred=13,
            current_nsproxy=1,current_net=14)
        self.assertTrue(evaluate(guard,values))
        self.assertTrue(evaluate(guard,{**values,'lsf_retirement_phase':3}))
        for name,value in values.items():
            if name.isupper():continue
            wrong=0 if name.startswith('actors_') or name in ('private_file','current_nsproxy') else value+100
            with self.subTest(operand=name):
                self.assertFalse(evaluate(guard,{**values,name:wrong}))

    def test_actual_scalar_publication_and_last_vfs_cutpoint_precede_native_record(self):
        old=source.original_sources();new=source.transform(old)
        text=new['net/factory-cleanup-root-final-free.c'].decode()
        physical=function(text,'static void lsf_cleanup_root_release_physical(')
        operations=('__free_pages(','put_net(','put_cred(','put_pid(','mmdrop(',
            'lsf_retirement_publish_after_physical(')
        locations=[physical.index(operation) for operation in operations]
        self.assertEqual(locations,sorted(locations))
        take=function(text,'static int lsf_cleanup_root_release_take_locked(')
        self.assertLess(take.index('lsf_retirement_capture_locked('),
            take.index('!lsf_device_finish('))
        self.assertNotIn('lsf_retirement',take[take.index('if (!lsf_device_queue('):
            take.index('/* LAST bank payload access')])
        publication=re.search(r'struct lsf_retirement_publication \{(.*?)\n\};',fragment(),re.S)[1]
        self.assertNotIn('*',publication)
        wire=re.search(r'struct lsf_retirement_wire \{(.*?)\n\};',fragment(),re.S)[1]
        fields=re.findall(r'__(le32|le64) ([a-z_, ]+);',wire)
        self.assertEqual(sum((4 if kind=='le32' else 8)*len(names.split(','))
            for kind,names in fields),48)
        mint=function(fragment(),'static long lsf_factory_retirement_ioctl(')
        self.assertLess(mint.index('anon_inode_create_getfile('),
            mint.index('lsf_retirement.phase = LSF_RETIREMENT_BOUND;'))
        self.assertLess(mint.index('lsf_retirement.phase = LSF_RETIREMENT_BOUND;'),
            mint.index('fd_install('))
        self.assertNotIn('lsf_retirement.',mint[mint.index('    fd_install('):
            mint.index('failed:')])
        self.assertNotRegex(fragment(),r'(?:WRITE_ONCE\(factory.uncertain|factory.pool.poisoned)\s*=')


if __name__=='__main__':unittest.main()
