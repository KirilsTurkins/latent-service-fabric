"""Tiny synthetic cold observations; never executed workload evidence."""
import copy
import json

from tools.tests.test_optimization_backend_revision_suite import Fixture as WarmFixture
from tools.tests.phase1_measurement_fixtures import sample
from tools.optimization_backend_revision import model as warm_model
from tools.optimization_backend_revision.cold import model
from tools.optimization_backend_revision.cold.observer import STAGES
from tools.optimization_revision_runner.backend import COLD_CONTROLS
from tools.optimization_evidence.attempts import CONSUMPTION
from tools.optimization_evidence.common import sha256
from tools.phase1_compiler_shutdown import FIELDS
from tools.phase1_paired.common import INPUT, TIMINGS


def compiler(final=False):
    value = {name:"0" for name in FIELDS}
    value.update(maximum_jobs="4",maximum_workers="2",maximum_queued_jobs="2",maximum_waiters="68",
                 maximum_waiters_per_job="68",maximum_ready_preparations="68",maximum_document_bytes="21233664",
                 workers_live="0" if final else "2",workers_quiescent="2" if final else "0",
                 workers_joined="2" if final else "0",accepting=not final,failed=False)
    return value


class Fixture(WarmFixture):
    def __init__(self,root):
        super().__init__(root)
        builds = json.loads((root/self.suite["builds"]["path"]).read_bytes())
        for label,build in (*builds["builds"].items(),("harness",builds["harness"])):
            for name in COLD_CONTROLS:
                build["inputs"][name] = self.write(f"builds/{label}/source/{name}",name.encode())
        self.suite["builds"] = self.write("backend-builds.json",builds)
        self.suite.update(schema="latent.optimization.cold-suite.v1",plan=model.plan("smoke"),elapsed_nanos="10000000000")
        for ordinal,row in enumerate(self.suite["runs"]):
            variant = row["variant"]
            row["command"][2] = model.COLLECTOR
            host = dict(row["host_before"],clock_ticks_per_second=100)
            row["host_before"] = row["host_after"] = host
            identity = warm_model.identity(builds,variant,host)
            prefix = f"runs/pair-01-{variant}/"
            row["identity"] = self.write(prefix+"identity.json",identity)
            selected = model.plan("smoke",1,variant)
            row["plan"] = self.write(prefix+"plan.json",selected)
            old = json.loads((root/row["raw"]["path"]).read_bytes())
            owner = json.loads((root/row["process"]["path"]).read_bytes())
            row["raw"] = self.write(prefix+"cold.json",self.raw(prefix,selected,identity,old,owner,builds))
            row.update(started_micros=str(ordinal*5_000_000),finished_micros=str((ordinal+1)*5_000_000))
        self.save()

    def raw(self,prefix,selected,identity,old,owner,builds):
        variant = "control" if selected["compiler_workers"] is None else "candidate"
        config = copy.deepcopy(old["configuration"])
        config.update(nodeId="cold-comparison",workers={"runtime":2,"control":4},shutdownGraceMillis=1000,
                      cells=[{"class":"standard","capacity":4,"queueCapacity":64,"maximumMemoryBytes":67_108_864}],
                      cache={"entries":8,"sourceBytes":134_217_728,"metadataBytes":67_108_864,
                             "compiledImageBytes":536_870_912,"preparations":4},
                      retention={"terminalEntries":2048,"terminalTtlMillis":60_000,"bytes":536_870_912})
        config["execution"]["maximumWallTimeMillis"] = 5000
        if variant == "candidate":
            config["cache"]["compilerWorkers"] = 2
        options = dict(old["effective_options"],pool_capacity="4",queue_capacity="64",control_workers="4",prepared_cache_maximum_entries="8")
        fixtures,releases = [],[]
        contracts = json.loads((self.root/builds["harness"]["echo"]["contracts"]["path"]).read_bytes())
        budget = {"cpuFuel":10_000_000_000,"memoryBytes":16_777_216,"logBytes":16384,"wallTimeLimitMillis":1000}
        for key in range(8):
            directory = f"fixtures/key-{key}"
            data = b"candidate"+(bytes([0,2,0,key]) if key else b"")
            release = sha256(data)
            releases.append(release)
            def retain(name,value):
                return dict(self.write(prefix+directory+"/"+name,value),path=name)
            metadata = {"tenant":"examples","name":f"cold-key-{key}"}
            documents = {
                "capsule":{"metadata":metadata,"component":{"digest":release},"exports":["examples:echo/api@0.1.0"],"execution":{"limits":budget}},
                "contracts":contracts,
                "deployment":{"metadata":metadata,"spec":{"release":release,"service":f"cold-key-{key}","resources":budget}}}
            artifact = {role:retain(f"echo-{role}.json",value) for role,value in documents.items()}
            artifact.update(component_sha256=release,component_bytes=str(len(data)),stored_descriptor_reference="local:release:"+release)
            fixtures.append({"key":str(key),"directory":directory,"component":retain("echo-component.wasm",data),"artifact":artifact,
                             "publication":{"release_digest":release,"deployment_id":f"cold-key-{key}","object_generation":"1","catalog_generation":str(key+1)},
                             "target":{"tenant":"examples","service":f"cold-key-{key}","contract":"examples:echo/api@0.1.0","function":"echo"}})
        records=[]
        now=10_000_000
        completed=0
        def compile_key(key,when):
            digest=[str(value) for value in bytes.fromhex(releases[key][7:])]
            thread={"process_id":str(owner["process_id"]),"thread_id":str(owner["process_id"]),"start_time_ticks":owner["start_time_ticks"]}
            for stage in STAGES[:-1]:
                cpu={"before":{"identity":thread,"user_ticks":"10","system_ticks":"1"},
                     "after":{"identity":thread,"user_ticks":"11","system_ticks":"1"}}
                records.append({"sequence":str(len(records)),"job_id":str(key),"component_digest":digest,"stage":stage,
                                "started_nanos":str(when),"finished_nanos":str(when+1000),"succeeded":True,
                                "thread_cpu":None if variant == "candidate" and stage == "whole_job" else cpu})
        def observer(when,final=False):
            totals=[]
            for stage in STAGES:
                rows=[item for item in records if item["stage"] == stage]
                cpu_count=sum(item["thread_cpu"] is not None for item in rows)
                totals.append({"stage":stage,"started":str(len(rows)),"completed":str(len(rows)),"failed":"0",
                               "elapsed_nanos":str(len(rows)*1000),"thread_cpu_samples":str(cpu_count),"thread_cpu_unavailable":str(len(rows)-cpu_count),
                               "thread_cpu_user_ticks":str(cpu_count),"thread_cpu_system_ticks":"0"})
            return {"collector_started_nanos":str(when),"collector_finished_nanos":str(when),
                    "snapshot":{"enabled":True,"revision":str(len(records)),"observed_nanos":str(when),"maximum_running_entries":"4",
                                "maximum_stage_observations":"256","active_jobs":"0","dropped_running_entries":"0",
                                "dropped_stage_observations":"0","compiler":compiler(final) if variant == "candidate" else None,
                                "stages":totals,"running":[],"recent_stages":copy.deepcopy(records)}}
        def node(label,when):
            value=sample(label)
            value.update(started_micros=str(when//1000),finished_micros=str(when//1000))
            value["resources"]["identity"]={"processId":owner["process_id"],"startTimeTicks":owner["start_time_ticks"]}
            value["resources"]["process"]["processId"]=owner["process_id"]
            value["inventory"]["cellCapacity"][0].update(total=4,available=4,queueCapacity=64)
            value["inventory"]["cacheSummary"].update(maximumEntries="8",maximumConcurrentPreparations="4",entries=str(len(records)//6))
            value["backend"]["stores_created"]=str(completed)
            return value
        rows=[]
        def checkpoint(label):
            rows.append({"kind":"checkpoint","label":label,"node":node(label,now),"observer":observer(now)})
        origin_unix=1_000_000_000_000
        def invoke(phase,index,key,due,label):
            nonlocal completed
            completed+=1
            activation=f"cold-{phase}-{label}{index:04}"
            consumption={name:"0" for name in CONSUMPTION.split()}
            consumption.update(cpu_fuel="100",peak_memory_bytes="1024",wall_time_micros="3",log_bytes="10")
            payload=('[{"ok":"'+INPUT+'"}]').encode()
            response={"activation_id":activation,"release_digest":releases[key],"revision_id":f"revision-{key}","route_generation":"8",
                      "code":None,"payload":{"sha256":sha256(payload),"bytes":str(len(payload)),"media_type":"application/vnd.latent.wit-values.v1+json"},"consumption":consumption}
            deadline=due+1_000_000_000
            absolute=(origin_unix+deadline+999999)//1_000_000
            return {"kind":"invoke","phase":phase,"index":str(index),"key":str(key),"activation_id":activation,"release_digest":releases[key],
                    "scheduled_nanos":str(due),"deadline_nanos":str(deadline),"deadline_unix_millis":str(absolute),
                    "absolute_deadline_quantization_nanos":str(absolute*1_000_000-origin_unix-deadline),"dispatch_nanos":str(due+100),
                    "dispatch_lag_nanos":"100","grpc_timeout_header":"999999u","rpc_received":True,"response":response,
                    "outcome":"success","completed_nanos":str(due+10_000),"overshoot_nanos":"0","valid_response":True,
                    "retained_status":{"grpc_code":0,"activation_id":activation,"phase":"terminal","terminal_state":"completed",
                        "outcome":"success","code":None,"metadata":{"release":releases[key],"revision":f"revision-{key}","route-generation":"8"},
                        "consumption":consumption},"retained_observed_nanos":str(due+20_000),
                    "backend_timing":{key:"1" for key in TIMINGS},"retained_valid":True}
        initial=observer(now)
        checkpoint("empty")
        compile_key(0,now+101_000)
        for phase,count in (("warmup",2),("baseline",4)):
            for index in range(count):
                now+=100_000
                rows.append(invoke(phase,index,0,now,""))
            now+=100_000
            checkpoint("after-"+phase)
        for phase,keys in (("same-key",[1]*8),("distinct",list(range(2,7))),("cancel",[7]*8)):
            now+=100_000
            rows.append({"kind":"phase-start","phase":phase,"observer":observer(now),"node":node(phase,now)})
            anchor=now+100_000
            first=anchor+10_000_000
            cold_due=first+4_000_000
            rows.append({"kind":"phase-anchor","phase":phase,"recorded_nanos":str(anchor),"offer_lead_nanos":"10000000",
                         "origin_nanos":str(first),"cold_due_nanos":str(cold_due)})
            for key in dict.fromkeys(keys):
                compile_key(key,cold_due+1000)
            for index in range(16):
                rows.append(invoke(phase,index,0,first+2_000_000*index,"warm-"))
            for index,key in enumerate(keys):
                rows.append(invoke(phase,index,key,cold_due,"cold-"))
            rows.append({"kind":"status-probe","phase":phase,"activation_id":f"cold-{phase}-cold-0000",
                         "started_nanos":str(cold_due+2_000_000),"finished_nanos":str(cold_due+2_010_000),
                         "response":{"grpc_code":5},"retained_valid":True})
            if phase == "cancel":
                capture=observer(cold_due+100_000)
                commands=[{"activation_id":f"cold-cancel-cold-{index:04}","started_nanos":str(cold_due+200_000+index*20_000),
                           "finished_nanos":str(cold_due+210_000+index*20_000),
                           "response":{"grpc_code":0,"disposition":3,"terminal_state":"completed"}} for index in range(4)]
                rows.append({"kind":"cancellation","phase":"cancel","trigger":{"running_when_observed":False,"observation":capture},
                             "commands":commands,"retained_valid":True})
            now=first+32_000_000
            rows.append({"kind":"phase-end","phase":phase,"finished_nanos":str(now),"observer":observer(now),"node":node(phase,now)})
        for index in range(2):
            now+=100_000
            rows.append(invoke("healthy",index,0,now,""))
        now+=100_000
        checkpoint("after-healthy")
        result={"schema":"latent.optimization.cold-arm.v1","plan":selected,"identity":identity,"configuration":config,"effective_options":options,
                "semantic_input":old["semantic_input"],"clock":{"unix_origin_nanos":str(origin_unix),"clock_anchor_uncertainty_nanos":"0"},
                "startup":old["startup"],"fixtures":fixtures,"initial_observer":initial,"configured_runtimes":{"invocation":2,"control":4,"client":2},
                "population":{"attempts":"77","commands":"177"},"samples":rows,"status":"passed","reason":None,
                "elapsed_micros":str(now//1000+1000),"work":{"invoke_attempts":"77","commands":"177","budget_exhausted":False},
                "before_shutdown":node("before-shutdown",now+1000),"shutdown":old["shutdown"],"data_cleanup":{"removed":True},
                "runtime_threads_after_join":{"invocation":0,"control":0,"client":0},"final_observer":observer(now+100_000,True)}
        if variant == "candidate":
            result["shutdown"]["compiler"]={key:item if type(item) is bool else int(item) for key,item in compiler(True).items()}
        return result
