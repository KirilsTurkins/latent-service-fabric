"""Decode bounded native observer records under the original Java fiber-I/O limits.

This is a private qualification reader, not a runtime hook or proof of guest
completion. Only the native hook's two fixed public activation IDs are used.
"""
from __future__ import annotations
import re

from tools.go_node_stop_timer_observer import ENVIRONMENT, PREFIX, MAXIMUM_STDERR

LIMITS = {'tasks':8, 'waits':16, 'timers':8}
MODES = {'pending','drain'}
EVENTS = {'start-accepted','next-entered','root-close','wait-pending'}


def observe(stderr):
    result={'formatVersion':1,'qualification':False,'records':[], 'status':'not-observed',
        'invalidMarkerCount':0,'overflow':False,'scope':'two-public-node-stop-fixture-activations-only',
        'javaProfileLimits':dict(LIMITS),'goProgrammeExecutionClaimed':False}
    if type(stderr) is not bytes or len(stderr)>MAXIMUM_STDERR:
        return {**result,'status':'invalid-source'}
    seen=set();counts=dict.fromkeys(MODES,0);markers=0
    for line in stderr.splitlines():
        if not line.startswith(PREFIX):continue
        markers+=1
        if markers>16 or len(line)>128:
            result['invalidMarkerCount']+=1;continue
        if line==PREFIX+b'|overflow':
            if result['overflow']:result['invalidMarkerCount']+=1
            result['overflow']=True;continue
        fields=line.split(b'|')
        if (len(fields)!=7 or fields[0]!=PREFIX or fields[1] not in {b'pending',b'drain'}
            or fields[2] not in {event.encode('ascii') for event in EVENTS}
            or any(re.fullmatch(rb'0|[1-9][0-9]{0,1}',value) is None for value in fields[3:])):
            result['invalidMarkerCount']+=1;continue
        sequence,tasks,waits,timers=map(int,fields[3:]);mode=fields[1].decode('ascii')
        if not (1<=sequence<=15 and sequence not in seen and counts[mode]<8
            and tasks<=LIMITS['tasks'] and waits<=LIMITS['waits'] and timers<=LIMITS['timers']):
            result['invalidMarkerCount']+=1;continue
        seen.add(sequence);counts[mode]+=1
        result['records'].append({'mode':mode,'event':fields[2].decode('ascii'),'sequence':sequence,
            'tasks':tasks,'waits':waits,'timers':timers})
    result['records'].sort(key=lambda row:row['sequence'])
    if result['invalidMarkerCount']:result['status']='invalid-marker'
    elif result['overflow']:result['status']='overflow'
    elif result['records']:result['status']='observed'
    return result
