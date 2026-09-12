#!/usr/bin/env python3
"""Render Phase 2 delivery SVG diagrams and static GitHub-compatible GIF previews."""
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
    body=card(72,155,392,130,'Package and verify',['Exact content and signed evidence','Current trust + lifecycle authority'])
    body+=card(524,155,392,130,'Immutable route snapshot',['Tenant-scoped deterministic selection','Generation pinned by each activation'])
    body+=card(976,155,392,130,'Fixed node resources',['Configured workers and class pools','Bounded metadata and prepared caches'])
    body+=arrow(prefix,468,516,220)+arrow(prefix,920,968,220)
    labels=[('Loopback RPC',['Explicit credentials','Invoke / status / cancel']),('Resolve / admit',['Pin revision + budget','Finite running / queue']),('Prepare / queue',['Checked code reuse','Current start eligibility']),('Fresh Store',['Generic WIT values','Context / logs / clocks']),('Account / reclaim',['Owned terminal sample','Reuse or quarantine'])]
    for i,(title,lines) in enumerate(labels):
        x=72+i*264
        body+=card(x,335,240,145,title,lines)
        if i<4: body+=arrow(prefix,x+242,x+258,410)
    body+=text(72,518,'Dormant services own metadata and artifacts; no dedicated guest heap, process or listener.',18)
    body+=card(72,552,1296,135,'Delivery boundary',['Phase 2 implemented: packages, trust, local AOT reuse, audit, rollouts, canaries and rollback. Gate #158 pending.','Phase 3: 41 planned tickets for capability providers, HTTP/web hosting, SDK delivery and gates.'],True)
    body+=text(72,722,'Current authority: development until release publication. Fixed topology does not mean constant catalog RSS.',16,'#d1fae5',600)
    return shell(prefix,'Phase 2: package, control and invocation','One Linux node; current eligibility and explicit ownership from publication through cleanup.',body)

def architecture_svg():
    prefix='system-decomposition'
    groups=[('Packages and trust',['Portable packages + OCI evidence','Publisher and builder authorization','Current policy + lifecycle capabilities','Raw cache is storage, not authority']),('Bounded execution',['Pinned revision + fresh Store','Budget ledger + tenant scheduling','Isolated approved compiler jobs','Authenticated local native reuse']),('Durable operator control',['Atomic deployment operation receipts','Explicit rollout and canary promotion','Eligible-target rollback + new routes','Bounded audit and exact recovery'])]
    body=''
    for i,(title,lines) in enumerate(groups): body+=card(72+i*440,166,416,212,title,lines)
    body+=text(72,420,'Six SDK language interfaces have fixtures; they do not yet ship transports, serializers or retries.',18)
    future=[('Phase 3: 41 planned tickets',['Capability providers + HTTP/web','SDKs + operator/security gates']),('Phase 4',['Transactional guest state','Explicit effect handling / outbox']),('Phase 5 / 6',['Cluster control + mTLS + placement','Durable workflow state machines'])]
    for i,(title,lines) in enumerate(future): body+=card(72+i*440,462,416,155,title,lines,True)
    body+=text(72,664,'Phase 2 gate #158 pending. Historical Phase 1 measurements keep their original source and scope.',18)
    body+=text(72,702,'Control durability does not create guest transactions, general provider access or a clustered runtime.',18)
    return shell(prefix,'Phase 2 owners and planned capabilities','Shared bounded owners; explicit operator actions; no worker or heap per dormant service.',body)

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
