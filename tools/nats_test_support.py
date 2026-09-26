#!/usr/bin/env python3
"""Finite TLS-only fixture provisioning for the owned public NATS test server."""
from __future__ import annotations
import json
from pathlib import Path
import socket
import ssl
import sys
import time

PASSWORD = "lsf-public-nats-password"
class Client:
    def __init__(self, port, ca):
        self.port, self.ca = int(port), Path(ca)
        if not 0 < self.port < 65536: raise ValueError("invalid test port")
        self.count = 0
    def request(self, subject, value):
        self.count += 1
        if self.count > 512 or not (subject.startswith("$JS.API.") or subject in ("lsf.trigger.a","lsf.trigger.b")) or len(subject)>128:
            raise RuntimeError("fixture control limit exceeded")
        encoded=json.dumps(value,separators=(",",":")).encode()
        if len(encoded)>8192: raise RuntimeError("fixture request too large")
        context=ssl.create_default_context(cafile=str(self.ca))
        with socket.create_connection(("127.0.0.1",self.port),timeout=2) as raw:
            with context.wrap_socket(raw,server_hostname="127.0.0.1") as stream:
                with stream.makefile("rb") as reader:
                    def line():
                        data=reader.readline(8193)
                        if len(data)>8192 or not data.endswith(b"\r\n"): raise RuntimeError("invalid fixture frame")
                        return data[:-2]
                    if not line().startswith(b"INFO "): raise RuntimeError("fixture INFO missing")
                    connect=json.dumps({"verbose":False,"pedantic":True,"tls_required":True,"headers":True,
                        "user":"operator","pass":PASSWORD}).encode()
                    stream.sendall(b"CONNECT "+connect+b"\r\nSUB _INBOX.ADMIN.LSF 1\r\nPING\r\n")
                    for _ in range(8):
                        response=line()
                        if response==b"PONG": break
                        if response==b"PING": stream.sendall(b"PONG\r\n")
                        else: raise RuntimeError("fixture authentication failed")
                    else: raise RuntimeError("fixture handshake exhausted")
                    stream.sendall(f"PUB {subject} _INBOX.ADMIN.LSF {len(encoded)}\r\n".encode()+encoded+b"\r\n")
                    for _ in range(8):
                        response=line()
                        if response==b"PING": stream.sendall(b"PONG\r\n"); continue
                        parts=response.split(b" ")
                        if len(parts)!=4 or parts[:3]!=[b"MSG",b"_INBOX.ADMIN.LSF",b"1"]: raise RuntimeError("fixture receipt mismatch")
                        size=int(parts[3])
                        if not 0<size<=32768: raise RuntimeError("fixture receipt too large")
                        body=reader.read(size+2)
                        if len(body)!=size+2 or not body.endswith(b"\r\n"): raise RuntimeError("fixture receipt truncated")
                        return json.loads(body[:-2])
                    raise RuntimeError("fixture response exhausted")
    def prepare(self):
        deadline=time.monotonic()+20
        while True:
            try:
                answer=self.request("$JS.API.INFO",{})
                if "error" in answer: raise RuntimeError("fixture account unavailable")
                break
            except (OSError,RuntimeError):
                if time.monotonic()>=deadline: raise RuntimeError("NATS TLS bootstrap failed") from None
                time.sleep(.2)
        self.reset()
    def reset(self):
        for stream,subjects in [("ORDERS",["lsf.tests.allowed","lsf.tests.denied"]),("OTHER",["lsf.other.allowed"])]:
            self.request("$JS.API.STREAM.DELETE."+stream,{})
            response=self.request("$JS.API.STREAM.CREATE."+stream,{"name":stream,"subjects":subjects,"storage":"memory",
                "num_replicas":1,"retention":"limits","max_msgs":32,"max_bytes":1048576,"max_msg_size":65536,"duplicate_window":1000000000})
            if "error" in response: raise RuntimeError("bounded fixture stream creation failed")
    def run(self,operation):
        if operation=="setup": self.prepare(); return
        if operation=="reset-fixture": self.reset(); return
        if operation in ("reset-triggers", "reset-many-triggers"):
            self.reset_triggers(128 if operation=="reset-many-triggers" else 1); return
        if operation in ("publish-triggers", "publish-poison"):
            for name in ("a", "b"):
                response=self.request("lsf.trigger."+name, [] if operation=="publish-triggers" else ["invalid-arity"])
                if "error" in response: raise RuntimeError("trigger publication failed")
            return
        if operation=="trigger-info":
            print(json.dumps([self.request("$JS.API.CONSUMER.INFO.TRIGGER"+name+".PROCESS",{}) for name in ("A","B")])); return
        if operation=="info":
            info=self.request("$JS.API.STREAM.INFO.ORDERS",{})
            print(json.dumps({"messages":info["state"]["messages"]})); return
        raise RuntimeError("unapproved fixture control operation")
    def reset_triggers(self,count):
        for name in ("a","b"):
            stream="TRIGGER"+name.upper()
            self.request("$JS.API.STREAM.DELETE."+stream,{})
            response=self.request("$JS.API.STREAM.CREATE."+stream,{"name":stream,"subjects":["lsf.trigger."+name],
                "storage":"memory","num_replicas":1,"retention":"limits","max_msgs":32,"max_bytes":1048576,"max_msg_size":1024})
            if "error" in response: raise RuntimeError("trigger stream setup failed")
            for index in range(count):
                consumer="PROCESS" if index==0 else "PROCESS"+str(index)
                response=self.request("$JS.API.CONSUMER.DURABLE.CREATE."+stream+"."+consumer,{
                    "stream_name":stream,"config":{"name":consumer,"durable_name":consumer,"filter_subject":"lsf.trigger."+name,
                    "ack_policy":"explicit","replay_policy":"instant","deliver_policy":"all","ack_wait":3500000000,
                    "max_deliver":3,"max_waiting":1,"max_ack_pending":1,"max_batch":1,"max_bytes":10240,"max_expires":100000000}})
                if "error" in response: raise RuntimeError("trigger consumer setup failed: "+str(response["error"]))
if __name__=="__main__": Client(int(sys.argv[1]),Path(sys.argv[2])).run(sys.argv[3])
