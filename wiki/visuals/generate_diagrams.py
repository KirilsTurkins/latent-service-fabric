#!/usr/bin/env python3
"""Render current Phase 1 SVG diagrams and static GitHub-compatible GIF previews."""
from __future__ import annotations
import io
from pathlib import Path
from xml.sax.saxutils import escape
import cairosvg
from PIL import Image

OUT=Path(__file__).resolve().parents[1]/'pages'/'assets'
W,H=1440,760

def text(x,y,value,size=18,color='#e0e7ff',weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'

def card(x,y,w,h,title,lines,later=False):
    fill,stroke=('#1e293b','#64748b') if later else ('#312e81','#818cf8')
    result=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="24" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
    result+=text(x+22,y+37,title,21,'#f8fafc',700)
    for i,line in enumerate(lines): result+=text(x+22,y+70+i*26,line,16,'#cbd5e1' if later else '#e0e7ff')
    return result

def arrow(prefix,x1,x2,y):
    return f'<path d="M{x1} {y} H{x2}" stroke="#bfdbfe" stroke-width="3" fill="none" marker-end="url(#{prefix}-arrow)"/>'

def shell(prefix,title,description,body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 760" role="img" aria-labelledby="{prefix}-title {prefix}-description">
<title id="{prefix}-title">{escape(title)}</title>
<desc id="{prefix}-description">{escape(description)}</desc>
<defs><linearGradient id="{prefix}-background" x2="1" y2="1"><stop stop-color="#1b102d"/><stop offset="1" stop-color="#1e3a5f"/></linearGradient>
<marker id="{prefix}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10Z" fill="#bfdbfe"/></marker></defs>
<rect width="1440" height="760" rx="24" fill="url(#{prefix}-background)"/>
<g font-family="system-ui, sans-serif">{text(72,82,title,34,'#faf5ff',700)}{text(72,117,description,18)}{body}</g></svg>'''

def home_svg():
    prefix='architecture-at-a-glance'
    body=card(72,155,392,130,'Publish and deploy',['Validated local release bytes','Durable catalogs and object versions'])
    body+=card(524,155,392,130,'Immutable route snapshot',['Tenant-scoped deterministic selection','Generation pinned by each activation'])
    body+=card(976,155,392,130,'Fixed node resources',['Configured workers and class pools','Bounded metadata and prepared caches'])
    body+=arrow(prefix,468,516,220)+arrow(prefix,920,968,220)
    labels=[('Loopback RPC',['Explicit credentials','Invoke / status / cancel']),('Resolve / admit',['Pin revision + budget','Finite running / queue']),('Prepare / queue',['Prepare before cell lease','Fair bounded queues']),('Fresh Store',['Generic WIT values','Context / logs / clocks']),('Account / reclaim',['Owned deadline cleanup','Reuse or quarantine'])]
    for i,(title,lines) in enumerate(labels):
        x=72+i*264
        body+=card(x,335,240,145,title,lines)
        if i<4: body+=arrow(prefix,x+242,x+258,410)
    body+=text(72,518,'Dormant services own metadata and artifacts; no dedicated guest heap, process or listener.',18)
    body+=card(72,552,1296,135,'Later phases remain separate',['Phase 2: OCI, signatures, provenance, SBOM and trusted AOT distribution','Phase 3+: general capabilities/HTTP ingress, state/effects, cluster control and durable workflows'],True)
    body+=text(72,722,'Phase 1 + extension complete. Fixed execution topology does not mean constant catalog RSS.',16,'#d1fae5',600)
    return shell(prefix,'Phase 1: the delivered local invocation path','One Linux node; stateless execution; explicit admission, ownership and cleanup.',body)

def architecture_svg():
    prefix='system-decomposition'
    groups=[('Management and client',['latent: generated gRPC client','Durable release/deployment catalogs','Scoped management + inventory','No automatic retries or pagination']),('Bounded execution',['Pinned local route snapshots','Budget ledger + tenant scheduling','Bounded preparation and code cache','Fresh activation Store and host state']),('Lifecycle and telemetry',['Caller/server activation identity','Bounded status and explicit cancel','Fixed disconnect cleanup supervisor','Redacted logs and final accounting'])]
    body=''
    for i,(title,lines) in enumerate(groups): body+=card(72+i*440,166,416,212,title,lines)
    body+=text(72,420,'Six SDK language interfaces have fixtures; they do not yet ship transports, serializers or retries.',18)
    future=[('Phase 2: next',['OCI + signed supply chain','Trusted AOT + rollout orchestration']),('Phase 3 / 4',['General capabilities + HTTP ingress','Transactional state + effect outbox']),('Phase 5 / 6',['Cluster control + mTLS + placement','Durable workflow state machines'])]
    for i,(title,lines) in enumerate(future): body+=card(72+i*440,462,416,155,title,lines,True)
    body+=text(72,664,'Actual Docker/Kubernetes comparisons are evidence, not clustered LSF feature delivery.',18)
    body+=text(72,702,'Native warm calls were faster; LSF reduced dense-cohort leaf memory and startup costs.',18)
    return shell(prefix,'Delivered features and the Phase 2 handoff','The Phase 1 completion and extension retain their original evidence and measured limits.',body)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for name,factory in [('architecture-at-a-glance',home_svg),('system-decomposition',architecture_svg)]:
        svg=factory()
        (OUT/f'{name}.svg').write_text(svg,encoding='utf-8',newline='\n')
        png=cairosvg.svg2png(bytestring=svg.encode(),output_width=W,output_height=H)
        with Image.open(io.BytesIO(png)) as image:
            image.convert('RGB').quantize(colors=128).save(OUT/f'{name}.gif',format='GIF')
        print(name, 'SVG and static GIF generated')
if __name__=='__main__': main()
