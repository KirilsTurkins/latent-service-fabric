"""Finite late-task controller and real host-JDK future reference controls."""
import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import java_http_late_fixture as fixture
from tools import java_http_late_node as node
from tools.build_observation import build_environment
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT


class JavaHttpLate(unittest.TestCase):
    def test_marker_requires_real_matching_post_after_the_held_body_event(self):
        from types import SimpleNamespace
        gate = SimpleNamespace(request=1, phase='body')
        for mode in (0, 1):
            marker=(node.KINDS[mode]+':cancelled:results:1').encode()
            observed={'requests':[{'request':2,'role':'primary','vector':'method-bytes','method':'POST',
                'bodyBytes':len(marker),'bodySha256':'sha256:'+hashlib.sha256(marker).hexdigest(),
                'closeReason':'response-write-complete'}], 'events':[
                {'kind':'gate-pending','request':1,'phase':'body','sequence':4},
                {'kind':'response-write-complete','request':2,'sequence':5}]}
            self.assertTrue(node.marker_after_cancel(observed,0,gate,mode))
            for changed in ('wrong-body','zero-results','get','prior','not-complete'):
                value=copy.deepcopy(observed)
                if changed=='wrong-body':value['requests'][0]['bodySha256']='sha256:'+'0'*64
                elif changed=='zero-results':value['requests'][0]['bodyBytes']-=1
                elif changed=='get':value['requests'][0]['method']='GET'
                elif changed=='prior':value['events'][1]['sequence']=3
                else:value['requests'][0].pop('closeReason')
                self.assertFalse(node.marker_after_cancel(value,0,gate,mode))

    def test_cancelled_result_cannot_be_replaced_by_late_success_or_foreign_revision(self):
        selected={'revisionId':'revision:owned'}
        for mode in (0,1,2):
            row={'processReaped':True,'exitCode':0,'decoded':[node.expected(mode)],'response':{
                'outcomeKnown':True,'data':{'resolvedRevision':selected,'consumption':{
                    'outboundRequests':'1' if mode==2 else '2'}}}}
            node.validate_result(row,mode,selected)
            for changed in ('success-value','unreaped','foreign','unknown','replay'):
                value=copy.deepcopy(row)
                if changed=='success-value':value['decoded']=['late-http-result']
                elif changed=='unreaped':value['processReaped']=False
                elif changed=='foreign':value['response']['data']['resolvedRevision']={}
                elif changed=='unknown':value['response']['outcomeKnown']=False
                else:value['response']['data']['consumption']['outboundRequests']='3'
                with self.assertRaises(WorkflowError):node.validate_result(value,mode,selected)

    def test_app_uses_only_readonly_sdk_observation_and_original_public_default_constructors(self):
        source=(ROOT/fixture.SOURCE).read_text()
        self.assertEqual(source.count('Bindings.LatentRuntimeActivation.'),1)
        self.assertIn('Bindings.LatentRuntimeActivation.observe()',source)
        for value in ('Executors.newSingleThreadExecutor()', 'CompletableFuture.supplyAsync(',
                'future.cancel(false)', 'future.get()', 'retained != 1', 'after != 0', 'attempt < 64'):
            self.assertIn(value,source)
        for excluded in ('setConnectionFactory(', 'new Connection(', 'Thread.sleep(', 'new Socket('):
            self.assertNotIn(excluded,source)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'Installed JDK required for reference controls')
    def test_real_jdk_late_running_task_cannot_overwrite_cancelled_future(self):
        source='''import java.util.concurrent.*;
        public final class LateReference {
            static void cancelled(Future<String> future) throws Exception {
                if (!future.isCancelled() || !future.isDone()) throw new AssertionError();
                try { future.get(); throw new AssertionError(); } catch (CancellationException expected) {}
            }
            public static void main(String[] args) throws Exception {
                for (int kind=0;kind<2;kind++) {
                    CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),returned=new CountDownLatch(1);
                    ExecutorService pool=kind==0?Executors.newSingleThreadExecutor():null;
                    java.util.concurrent.Callable<String> work=()->{ entered.countDown();
                        if(!release.await(3,TimeUnit.SECONDS)) throw new AssertionError();
                        returned.countDown();return "late-value";};
                    Future<String> future=kind==0?pool.submit(work):CompletableFuture.supplyAsync(()->{
                        try{return work.call();}catch(Exception error){throw new RuntimeException(error);}});
                    try {
                        if(!entered.await(3,TimeUnit.SECONDS)||!future.cancel(false)) throw new AssertionError();
                        cancelled(future);if(returned.getCount()!=1)throw new AssertionError();
                        release.countDown();if(!returned.await(3,TimeUnit.SECONDS))throw new AssertionError();
                        cancelled(future);
                    } finally {release.countDown();if(pool!=null){pool.shutdown();if(!pool.awaitTermination(3,TimeUnit.SECONDS))throw new AssertionError();}}
                }
                System.out.println("late-reference:2");
            }
        }'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'LateReference.java').write_text(source)
            env=build_environment(root)
            for command in ([shutil.which('javac'),'-J-Xmx128m','--release','17','-d',str(root),str(root/'LateReference.java')],
                    [shutil.which('java'),'-Xmx64m','-cp',str(root),'LateReference']):
                result=subprocess.run(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
                self.assertLessEqual(len(result.stdout),262144)
                self.assertEqual(result.returncode,0,result.stdout.decode('utf-8','replace'))
            self.assertEqual(result.stdout.decode().strip(),'late-reference:2')

    @unittest.skipUnless(shutil.which('javac'), 'Installed JDK required for checked source signatures')
    def test_actual_fixture_compiles_against_observe_record_and_public_http_signatures(self):
        sources={'dev/latent/generated/Bindings.java':'''package dev.latent.generated;public final class Bindings {
            public interface Exports{String run(Long mode,String endpoint);}
            public record Observation(Long results){}public record Observed(Observation value){public boolean isError(){return false;}}
            public static final class LatentRuntimeActivation{public static Observed observe(){return new Observed(new Observation(1L));}}}''',
            'com/github/kevinsawicki/http/HttpRequest.java':'''package com.github.kevinsawicki.http;
            public final class HttpRequest{public static HttpRequest get(String url){return new HttpRequest();}
            public int code(){return 200;}public void disconnect(){}public HttpRequest receive(java.io.OutputStream output){return this;}}'''}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);files=[]
            for name,source in sources.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source);files.append(str(path))
            result=subprocess.run([shutil.which('javac'),'-J-Xmx128m','--release','17','-encoding','UTF-8',
                '-d',str(root/'classes'),*files,str(ROOT/fixture.SOURCE)],cwd=root,env=build_environment(root),
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
            self.assertLessEqual(len(result.stdout),262144)
            self.assertEqual(result.returncode,0,result.stdout.decode('utf-8','replace'))


if __name__=='__main__':unittest.main()
