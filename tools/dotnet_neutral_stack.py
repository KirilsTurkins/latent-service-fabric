"""Data-only reversible stack access experiment, NOT a thread or GC implementation."""
import argparse,hashlib,json,sys
from pathlib import Path
if __package__ in {None, ''}:
 sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dotnet_guest.internal_io import core_modules,integer,encoded_integer
from tools import guest_emitted_code as w
CORE=b'\0asm\x01\0\0\0'
COMP=b'\0asm\x0d\0\x01\0'
EXPECTED='d3e8dab0c62188465bcdbab9a6a0a3845887190dd44affd48e54acfe6db5bff6'
ZERO5=b'\x80\x80\x80\x80\0'
GET_BODY=b'\0\x23'+ZERO5+b'\x0b'
SET_BODY=b'\0\x20\0\x24'+ZERO5+b'\x0b'
def sha(b):return hashlib.sha256(b).hexdigest()
def padded5(n):
 if not 0<=n<2**32:raise ValueError('u32')
 return bytes([((n>>(7*i))&127)|128 for i in range(4)]+[(n>>28)&15])
def parts(data,magic):
 if not data.startswith(magic):raise ValueError('header')
 at=len(magic)
 while at<len(data):
  start=at;kind=data[at];n,pos=integer(data,at+1);end=pos+n
  if end>len(data) or data[at+1:pos]!=encoded_integer(n):raise ValueError('section-encoding')
  yield kind,data[pos:end],data[start:end]
  at=end
 if at!=len(data):raise ValueError('section-end')
def section(kind,payload):return bytes([kind])+encoded_integer(len(payload))+payload
def vector(payload):
 n,pos=integer(payload,0)
 if payload[:pos]!=encoded_integer(n):raise ValueError('vector-encoding')
 return n,pos
def type_indexes(raw):
 payload=next(p for k,p,_ in parts(raw,CORE) if k==1)
 r=w.Reader(payload,w.Budget());n=r.count(65536);matches={}
 for idx in range(n):
  if r.byte()!=0x60:raise ValueError('not-function-type')
  pn=r.count(32);params=tuple(r.byte() for _ in range(pn))
  rn=r.count(32);results=tuple(r.byte() for _ in range(rn))
  if any(x not in (0x7f,0x7e,0x7d,0x7c,0x7b,0x70,0x6f) for x in params+results):raise ValueError('unsupported-value-type')
  if (params,results) in (((),(0x7f,)),((0x7f,),())):
   if (params,results) in matches:raise ValueError('ambiguous-helper-type')
   matches[(params,results)]=idx
 r.done()
 if len(matches)!=2:raise ValueError('missing-helper-type')
 return matches[((),(0x7f,))],matches[((0x7f,),())]
def imports(raw):
 payload=next(p for k,p,_ in parts(raw,CORE) if k==2)
 r=w.Reader(payload,w.Budget());n=r.count(65536);count=0
 for _ in range(n):
  r.name();r.name();kind=r.byte()
  if kind!=0:raise ValueError('nonfunction-import')
  r.leb();count+=1
 r.done();return count
def stack_global(raw):
 payload=next(p for k,p,_ in parts(raw,CORE) if k==6)
 n,at=vector(payload)
 if n<1 or payload[at:at+3]!=b'\x7f\x01\x41':raise ValueError('stack-global-shape')
 _v,end=integer(payload,at+3)
 if end>=len(payload) or payload[end]!=0x0b:raise ValueError('stack-global-init')
class Trace(w.Reader):
 def __init__(self,data,budget):
  super().__init__(data,budget);self.pending=None;self.in_leb=False;self.sites=[]
 def byte(self):
  start=self.at;x=super().byte()
  if not self.in_leb:self.pending=(x,start) if x in (0x10,0x23,0x24) else None
  return x
 def leb(self,bits=32,signed=False):
  pending=self.pending;start=self.at;self.in_leb=True
  try:value=super().leb(bits,signed)
  finally:self.in_leb=False
  if pending:
   self.sites.append((pending[0],value,pending[1],start,self.at))
   self.pending=None
  return value
def rewrite_body(body,budget,first,reverse):
 r=Trace(body,budget);calls,refs,_dynamic=w.instructions(r,body=True);r.done()
 out=bytearray(body);get=set_=0
 for op,value,pos,start,end in r.sites:
  if not reverse and op in (0x23,0x24) and value==0:
   if body[start:end]!=ZERO5:raise ValueError('nonpadded-stack-global')
   out[pos]=0x10;out[start:end]=padded5(first+(op==0x24))
   if op==0x23:get+=1
   else:set_+=1
  elif reverse and op==0x10 and value in (first,first+1):
   if body[start:end]!=padded5(value):raise ValueError('nonpadded-helper-call')
   out[pos]=0x23 if value==first else 0x24;out[start:end]=ZERO5
   if value==first:get+=1
   else:set_+=1
  elif reverse and op in (0x23,0x24) and value==0:
   raise ValueError('unreplaced-stack-global')
 if not reverse and any(c>=first for c in calls|refs):raise ValueError('future-function-reference')
 return bytes(out),get,set_
def _derive(raw,reverse=False):
 if len(raw)>8*1024*1024:raise ValueError('core-bound')
 getter,setter=type_indexes(raw); imp=imports(raw);stack_global(raw)
 entries=list(parts(raw,CORE)); fs=[p for k,p,_ in entries if k==3];cs=[p for k,p,_ in entries if k==10]
 if len(fs)!=1 or len(cs)!=1:raise ValueError('section-count')
 n,fpos=vector(fs[0]);cn,cpos=vector(cs[0])
 if n!=cn or n>12002 or (reverse and n<2):raise ValueError('function-count')
 base=n-2 if reverse else n; first=imp+base
 if first+1>=65536:raise ValueError('helper-index-bound')
 r=w.Reader(fs[0][fpos:],w.Budget());indexes=[]
 for _ in range(n):indexes.append(r.leb())
 r.done()
 if reverse and indexes[-2:]!=[getter,setter]:raise ValueError('helper-type-drift')
 original_types=fs[0][fpos:];type_len=len(original_types)
 if reverse:
  # Appended helper type indexes are required to use these exact canonical encodings.
  suffix=encoded_integer(getter)+encoded_integer(setter)
  if not original_types.endswith(suffix):raise ValueError('helper-type-encoding')
  original_types=original_types[:-len(suffix)]
 bodyrows=[];at=cpos
 for _ in range(n):
  start=at;size,pos=integer(cs[0],at);end=pos+size
  if end>len(cs[0]) or cs[0][at:pos]!=encoded_integer(size):raise ValueError('body-encoding')
  bodyrows.append((cs[0][start:pos],cs[0][pos:end]));at=end
 if at!=len(cs[0]):raise ValueError('body-count')
 if reverse and (bodyrows[-2][1]!=GET_BODY or bodyrows[-1][1]!=SET_BODY):raise ValueError('helper-body-drift')
 if reverse:bodyrows=bodyrows[:-2]
 budget=w.Budget();rewritten=[];gets=sets=0
 for prefix,body in bodyrows:
  updated,g,s=rewrite_body(body,budget,first,reverse);gets+=g;sets+=s;rewritten.append(prefix+updated)
 if not gets or not sets:raise ValueError('no-stack-operations')
 if reverse:
  fp=encoded_integer(base)+original_types;cp=encoded_integer(base)+b''.join(rewritten)
 else:
  fp=encoded_integer(base+2)+original_types+encoded_integer(getter)+encoded_integer(setter)
  cp=encoded_integer(base+2)+b''.join(rewritten)+encoded_integer(len(GET_BODY))+GET_BODY+encoded_integer(len(SET_BODY))+SET_BODY
 output=CORE+b''.join(section(k,fp if k==3 else cp) if k in (3,10) else original for k,_payload,original in entries)
 return output,{'importedFunctions':imp,'originalFunctions':base,'getterType':getter,'setterType':setter,
                'helperIndexes':[first,first+1],'getSites':gets,'setSites':sets,'decodedInstructions':budget.instructions}
def replace_component(component,old,new,depth=0):
 if depth>3:raise ValueError('component-depth')
 hits=0;chunks=[]
 for kind,payload,original in parts(component,COMP):
  replacement=payload
  if kind==1 and sha(payload)==sha(old) and payload==old:
   replacement=new;hits+=1
  elif kind==4:
   replacement,inner=replace_component(payload,old,new,depth+1);hits+=inner
  chunks.append(original if replacement==payload else section(kind,replacement))
 return COMP+b''.join(chunks),hits


ORIGINAL_COMPONENT = '3ab0ae8b54c5ed0469b3f9ea105fd566f308e314bdf3aeeb4529b9ed4085f20a'
DERIVED_COMPONENT = 'f48d42c7c966aa6e87bd2e01f5a90379d2c7b5e6e2e84de26e4581b4391d3f80'
DERIVED_CORE = '6d5c4b64685e15f063cd01ca0cedb470827d1fbd214e267f5887dcc51bd8ebff'
ORIGINAL_BYTES, DERIVED_BYTES = 7542795, 7542817
EXPECTED_COUNTS = {'importedFunctions':49, 'originalFunctions':10670, 'getterType':9, 'setterType':0,
                   'helperIndexes':[10719,10720], 'getSites':1131, 'setSites':2412, 'decodedInstructions':1159801}

def derive(raw, reverse=False):
 previous = w.MAX_INSTRUCTIONS
 w.MAX_INSTRUCTIONS = 1250000
 try: return _derive(raw, reverse)
 finally: w.MAX_INSTRUCTIONS = previous

def produce(component):
 if len(component)!=ORIGINAL_BYTES or sha(component)!=ORIGINAL_COMPONENT: raise ValueError('original-component-identity')
 cores=core_modules(component)
 if len(cores)!=11 or len(cores[7])!=7293062 or sha(cores[7])!=EXPECTED: raise ValueError('original-core-identity')
 raw=cores[7]
 derived,forward=derive(raw)
 if len(derived)!=7293084 or sha(derived)!=DERIVED_CORE or forward!=EXPECTED_COUNTS: raise ValueError('derived-core-identity')
 original,back=derive(derived,True)
 if original!=raw or back!=EXPECTED_COUNTS: raise ValueError('core-roundtrip')
 changed,hits=replace_component(component,raw,derived)
 if hits!=1 or len(changed)!=DERIVED_BYTES or sha(changed)!=DERIVED_COMPONENT: raise ValueError('derived-component-identity')
 restored,hits=replace_component(changed,derived,original)
 if hits!=1 or restored!=component: raise ValueError('component-roundtrip')
 if core_modules(changed)!=cores[:7]+[derived]+cores[8:]: raise ValueError('other-core-changed')
 return changed,{'schemaVersion':'latent.dotnet.neutral-stack-derivation.v1',
   'originalComponent':{'bytes':len(component),'sha256':sha(component)},
   'derivedComponent':{'bytes':len(changed),'sha256':sha(changed)},
   'originalCore':{'bytes':len(raw),'sha256':sha(raw)},
   'derivedCore':{'bytes':len(derived),'sha256':sha(derived)},
   'counts':forward,'coreRoundtripExact':True,'componentRoundtripExact':True,
   'otherCoresUnchanged':True,'guestExecution':False,'productionProfile':False,
   'scope':'neutral shared-global indirection only; additional calls change fuel and stack cost'}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--original',type=Path,required=True)
 parser.add_argument('--derived',type=Path,required=True)
 parser.add_argument('--receipt',type=Path,required=True)
 args=parser.parse_args()
 if args.original.stat().st_size!=ORIGINAL_BYTES: raise ValueError('original-component-size')
 original=args.original.read_bytes()
 changed,record=produce(original)
 with args.derived.open('xb') as output: output.write(changed)
 with args.receipt.open('x',encoding='utf-8') as output: json.dump(record,output,indent=2);output.write('\n')
 print('neutral derivation complete; no guest executed')

if __name__=='__main__': main()
