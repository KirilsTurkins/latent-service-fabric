#!/usr/bin/env python3
"""Generate animated SVG sources and GitHub-compatible GIF previews for the LSF Wiki."""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Sequence

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pages" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

BG = "#07111f"
PANEL = "#0d1c30"
PANEL_2 = "#102540"
GRID = "#17324d"
TEXT = "#e9f5ff"
MUTED = "#92a9bd"
CYAN = "#40e0ff"
BLUE = "#5b8cff"
MAGENTA = "#c66cff"
GREEN = "#58f0ae"
AMBER = "#ffca6a"
RED = "#ff718d"


def esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def defs(animated: bool) -> str:
    motion_css = """
      @keyframes dash { to { stroke-dashoffset: -38; } }
      @keyframes pulse { 0%,100% { opacity:.48; transform:scale(.96); } 50% { opacity:1; transform:scale(1.04); } }
      @keyframes glow { 0%,100% { opacity:.30; } 50% { opacity:.92; } }
      @keyframes scan { from { transform:translateX(-220px); } to { transform:translateX(1320px); } }
      .flow { stroke-dasharray: 10 12; animation: dash 1.6s linear infinite; }
      .pulse { transform-box: fill-box; transform-origin: center; animation: pulse 2.4s ease-in-out infinite; }
      .glow { animation: glow 1.8s ease-in-out infinite; }
      .scan { animation: scan 7s linear infinite; }
      .cell-a { animation: glow 3.2s ease-in-out infinite; }
      .cell-b { animation: glow 3.2s .8s ease-in-out infinite; }
      .cell-c { animation: glow 3.2s 1.6s ease-in-out infinite; }
      .cell-d { animation: glow 3.2s 2.4s ease-in-out infinite; }
      @media (prefers-reduced-motion: reduce) {
        .flow,.pulse,.glow,.scan,.cell-a,.cell-b,.cell-c,.cell-d { animation:none !important; }
      }
    """ if animated else ""
    return f"""
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#06101d"/><stop offset=".55" stop-color="#0a1830"/><stop offset="1" stop-color="#11152d"/>
      </linearGradient>
      <linearGradient id="cyanBlue" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{BLUE}"/>
      </linearGradient>
      <linearGradient id="purplePink" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="{MAGENTA}"/><stop offset="1" stop-color="{RED}"/>
      </linearGradient>
      <linearGradient id="greenAmber" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="{GREEN}"/><stop offset="1" stop-color="{AMBER}"/>
      </linearGradient>
      <radialGradient id="halo"><stop offset="0" stop-color="{CYAN}" stop-opacity=".55"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></radialGradient>
      <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
        <path d="M 28 0 L 0 0 0 28" fill="none" stroke="{GRID}" stroke-width="1" opacity=".42"/>
      </pattern>
      <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%">
        <feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" flood-opacity=".42"/>
      </filter>
      <filter id="softGlow" x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="6" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <marker id="arrowCyan" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="{CYAN}"/>
      </marker>
      <marker id="arrowMagenta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="{MAGENTA}"/>
      </marker>
      <style>
        text {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
        .title {{ fill:{TEXT}; font-size:28px; font-weight:750; letter-spacing:.2px; }}
        .subtitle {{ fill:{MUTED}; font-size:14px; }}
        .label {{ fill:{TEXT}; font-size:14px; font-weight:700; }}
        .small {{ fill:{MUTED}; font-size:11px; }}
        .tiny {{ fill:{MUTED}; font-size:10px; }}
        .box {{ fill:{PANEL}; stroke:#264966; stroke-width:1.4; }}
        .box2 {{ fill:{PANEL_2}; stroke:#315a7d; stroke-width:1.4; }}
        .edge {{ fill:none; stroke:{CYAN}; stroke-width:2.5; stroke-linecap:round; stroke-linejoin:round; }}
        .edge2 {{ fill:none; stroke:{MAGENTA}; stroke-width:2.3; stroke-linecap:round; stroke-linejoin:round; }}
        {motion_css}
      </style>
    </defs>
    """


def shell(width: int, height: int, title: str, subtitle: str, body: str, animated: bool) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
      <title id="title">{esc(title)}</title>
      <desc id="desc">{esc(subtitle)}</desc>
      {defs(animated)}
      <rect width="{width}" height="{height}" rx="24" fill="url(#bg)"/>
      <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="23" fill="none" stroke="#274461"/>
      <rect width="{width}" height="{height}" rx="24" fill="url(#grid)" opacity=".43"/>
      <rect class="scan" x="-220" y="0" width="180" height="{height}" fill="url(#cyanBlue)" opacity=".035" transform="skewX(-14)"/>
      <text class="title" x="42" y="48">{esc(title)}</text>
      <text class="subtitle" x="42" y="73">{esc(subtitle)}</text>
      {body}
    </svg>"""


def rounded_box(x: float, y: float, w: float, h: float, title: str, subtitle: str = "", accent: str = CYAN, klass: str = "box") -> str:
    subtitle_svg = f'<text class="small" x="{x+16}" y="{y+49}">{esc(subtitle)}</text>' if subtitle else ""
    return f"""
      <g filter="url(#shadow)">
        <rect class="{klass}" x="{x}" y="{y}" width="{w}" height="{h}" rx="14"/>
        <rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="{accent}"/>
        <circle cx="{x+w-18}" cy="{y+18}" r="4" fill="{accent}" opacity=".85"/>
        <text class="label" x="{x+16}" y="{y+28}">{esc(title)}</text>
        {subtitle_svg}
      </g>
    """


def path(points: Sequence[tuple[float, float]], color: str = CYAN, marker: str = "arrowCyan", animated: bool = True, dash: bool = True) -> str:
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
    cls = "edge flow" if color == CYAN and animated and dash else "edge2 flow" if animated and dash else "edge" if color == CYAN else "edge2"
    return f'<path class="{cls}" d="{d}" marker-end="url(#{marker})" opacity=".82"/>'


def poly_point(points: Sequence[tuple[float, float]], t: float) -> tuple[float, float]:
    segments = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        segments.append((a, b, length))
        total += length
    target = (t % 1.0) * total
    for a, b, length in segments:
        if target <= length:
            q = target / max(length, 1e-9)
            return a[0] + (b[0]-a[0])*q, a[1] + (b[1]-a[1])*q
        target -= length
    return points[-1]


def particle(points: Sequence[tuple[float, float]], color: str, phase: float, delay: float = 0.0, animated: bool = False, duration: float = 3.2) -> str:
    if animated:
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
        return f"""<circle r="5" fill="{color}" filter="url(#softGlow)">
          <animateMotion dur="{duration}s" begin="{delay}s" repeatCount="indefinite" path="{d}"/>
        </circle>"""
    x, y = poly_point(points, phase + delay / duration)
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" filter="url(#softGlow)"/>'


def home_svg(animated: bool = True, phase: float = 0.0) -> str:
    edges = {
        "dev_registry": [(205,150),(270,150),(270,236),(328,236)],
        "mgmt_control": [(205,236),(328,236)],
        "control_snapshot": [(518,236),(580,236),(580,145),(645,145)],
        "ingress_resolve": [(205,388),(328,388)],
        "snapshot_resolve": [(740,178),(740,208),(422,208),(422,351)],
        "resolve_pool": [(518,388),(584,388)],
        "pool_activation": [(754,388),(812,388)],
        "activation_caps": [(902,428),(902,452)],
        "activation_result": [(915,504),(915,520)],
        "caps_state": [(820,478),(670,478),(670,520)],
        "caps_effects": [(1010,478),(1100,478),(1100,520)],
    }
    parts = []
    parts.append('<rect x="38" y="90" width="292" height="28" rx="14" fill="#0b2b25" stroke="#2a7a61"/>')
    parts.append('<text x="52" y="109" fill="#58f0ae" font-size="10.5" font-weight="800" letter-spacing=".35">DORMANT RELEASES · ZERO EXECUTION ALLOCATION</text>')
    parts.append(rounded_box(42,126,163,52,"Developer tooling","build + sign",GREEN))
    parts.append(rounded_box(42,210,163,52,"Management client","desired state",MAGENTA))
    parts.append(rounded_box(42,362,163,52,"Shared ingress","HTTP · RPC · events",CYAN))
    parts.append(rounded_box(328,210,190,52,"Control plane","policy · routes · audit",MAGENTA,"box2"))
    parts.append(rounded_box(328,362,190,52,"Resolve + admit","snapshot · quota · deadline",CYAN,"box2"))
    parts.append(rounded_box(328,126,190,52,"OCI registry","immutable capsules",GREEN))
    parts.append(rounded_box(645,119,190,58,"Route snapshot","immutable generation",AMBER))
    parts.append(rounded_box(584,348,170,80,"Reusable cell pool","fixed node capacity",CYAN,"box2"))
    for i, x in enumerate([605,641,677,713]):
        active = (int(phase*4) % 4 == i) if not animated else False
        opacity = 1.0 if active else .38
        klass = f"cell-{chr(97+i)}" if animated else ""
        parts.append(f'<rect class="{klass}" x="{x}" y="386" width="24" height="24" rx="6" fill="{CYAN}" opacity="{opacity}" filter="url(#softGlow)"/>')
    parts.append(rounded_box(812,348,180,80,"Temporary activation","fresh store + budget",MAGENTA,"box2"))
    parts.append('<circle class="pulse" cx="970" cy="368" r="8" fill="#ff718d" filter="url(#softGlow)"/>')
    parts.append(rounded_box(820,452,190,52,"Capability broker","scoped handles",GREEN))
    parts.append(rounded_box(810,520,190,52,"Result + accounting","output · trace · usage",AMBER))
    parts.append(rounded_box(580,520,180,52,"State backend","transactional commit",BLUE))
    parts.append(rounded_box(1020,520,160,52,"Effect providers","durable intents",RED))

    for key, pts in edges.items():
        c = MAGENTA if key in {"mgmt_control","control_snapshot","activation_caps"} else CYAN
        marker = "arrowMagenta" if c == MAGENTA else "arrowCyan"
        parts.append(path(pts,c,marker,animated=animated))
    particle_keys = ["dev_registry","mgmt_control","control_snapshot","ingress_resolve","resolve_pool","pool_activation","activation_caps","activation_result","caps_state","caps_effects"]
    for idx,key in enumerate(particle_keys):
        c = MAGENTA if key in {"mgmt_control","control_snapshot","activation_caps"} else CYAN
        parts.append(particle(edges[key],c,phase,delay=idx*.24,animated=animated,duration=3.8))
    parts.append('<text class="tiny" x="602" y="442">lease → run → scrub → reuse</text>')
    return shell(1200,610,"LSF architecture at a glance","Immutable releases become temporary, capability-scoped activations in a fixed pool.","".join(parts),animated)


def architecture_svg(animated: bool = True, phase: float = 0.0) -> str:
    parts = []
    planes = [
        (34,96,1132,148,"DEVELOPER PLANE",GREEN,"build, attest, sign, publish",220),
        (34,264,1132,164,"CONTROL PLANE",MAGENTA,"compile desired state into immutable snapshots",180),
        (34,448,1132,212,"DATA PLANE · INVOCATION HOT PATH",CYAN,"resolve locally, admit, schedule, execute, commit",330),
    ]
    for x,y,w,h,label,accent,desc,desc_x in planes:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{PANEL}" stroke="{accent}" stroke-opacity=".42"/>')
        parts.append(f'<text x="{x+18}" y="{y+28}" fill="{accent}" font-size="12" font-weight="850" letter-spacing="1.2">{label}</text>')
        parts.append(f'<text class="tiny" x="{desc_x}" y="{y+27}">{esc(desc)}</text>')

    parts.append(rounded_box(78,146,210,62,"WIT + component build","polyglot guest boundary",GREEN))
    parts.append(rounded_box(366,146,210,62,"Supply-chain evidence","SBOM · provenance · signature",GREEN))
    parts.append(rounded_box(876,146,210,62,"OCI registry","content-addressed releases",GREEN))
    dev1=[(288,177),(366,177)]; dev2=[(576,177),(876,177)]
    parts += [path(dev1,CYAN,"arrowCyan",animated),path(dev2,CYAN,"arrowCyan",animated)]

    parts.append(rounded_box(78,318,188,64,"Release + contracts","digests · WIT graph",MAGENTA))
    parts.append(rounded_box(320,318,188,64,"Policy + bindings","grants · modes · quotas",MAGENTA))
    parts.append(rounded_box(562,318,188,64,"Route compiler","revision selection",MAGENTA))
    parts.append(rounded_box(804,294,160,50,"Desired state","generation checks",AMBER))
    parts.append(rounded_box(804,356,160,50,"Node inventory","capacity · locality",AMBER))
    parts.append(rounded_box(1008,318,126,64,"Snapshot","digest + generation",MAGENTA,"box2"))
    ctl1=[(266,350),(320,350)]; ctl2=[(508,350),(562,350)]; ctl3=[(750,350),(1008,350)]
    parts += [path(ctl1,MAGENTA,"arrowMagenta",animated),path(ctl2,MAGENTA,"arrowMagenta",animated),path(ctl3,MAGENTA,"arrowMagenta",animated)]
    parts.append('<path d="M 884 344 L 884 350" stroke="#ffca6a" stroke-width="2"/>')
    parts.append('<path d="M 964 381 L 990 381 L 990 350" fill="none" stroke="#ffca6a" stroke-width="2"/>')

    hot = [
        (58,520,120,"Ingress"),(198,520,120,"Resolver"),(338,520,120,"Admission"),(478,520,120,"Scheduler"),
        (618,520,136,"Materializer"),(774,520,120,"Binder"),(914,504,126,"Cell pool"),(1060,520,86,"Commit"),
    ]
    for x,y,w,label in hot:
        h=72 if label=="Cell pool" else 56
        parts.append(rounded_box(x,y,w,h,label,"",CYAN,"box2"))
    for a,b in zip(hot,hot[1:]):
        ax,ay,aw,_=a; bx,by,bw,_=b
        p=[(ax+aw,548),(bx,548)]
        parts.append(path(p,CYAN,"arrowCyan",animated))
    for i,x in enumerate([932,956,980,1004]):
        active=(int(phase*4)%4==i) if not animated else False
        opacity=1 if active else .32
        klass=f"cell-{chr(97+i)}" if animated else ""
        parts.append(f'<rect class="{klass}" x="{x}" y="548" width="15" height="15" rx="4" fill="{CYAN}" opacity="{opacity}" filter="url(#softGlow)"/>')
    snap=[(1070,382),(1070,492),(258,492),(258,520)]
    art=[(980,208),(980,238),(686,238),(686,520)]
    parts.append(path(snap,MAGENTA,"arrowMagenta",animated))
    parts.append(path(art,CYAN,"arrowCyan",animated))
    parts.append('<text class="tiny" x="650" y="486" fill="#c66cff">immutable route snapshot</text>')
    parts.append('<text class="tiny" x="704" y="230" fill="#40e0ff">verified capsule / AOT derivative</text>')
    parts.append(rounded_box(664,596,164,42,"State backend","",BLUE))
    parts.append(rounded_box(846,596,164,42,"Effect outbox","",RED))
    parts.append(rounded_box(1028,596,118,42,"Telemetry","",AMBER))
    parts.append(path([(1103,576),(1103,596)],CYAN,"arrowCyan",animated=False,dash=False))
    parts.append(path([(1103,576),(928,596)],MAGENTA,"arrowMagenta",animated=False,dash=False))
    parts.append(path([(1103,576),(746,596)],CYAN,"arrowCyan",animated=False,dash=False))

    flows=[dev1,dev2,ctl1,ctl2,ctl3,snap,art]
    for idx,p in enumerate(flows):
        color=MAGENTA if idx in {2,3,4,5} else CYAN
        parts.append(particle(p,color,phase,delay=idx*.38,animated=animated,duration=4.2))
    for idx,(a,b) in enumerate(zip(hot,hot[1:])):
        ax,ay,aw,_=a; bx,by,bw,_=b
        p=[(ax+aw,548),(bx,548)]
        parts.append(particle(p,CYAN,phase,delay=idx*.32,animated=animated,duration=3.4))
    parts.append('<rect x="50" y="486" width="1098" height="104" rx="16" fill="none" stroke="#40e0ff" stroke-width="1.2" stroke-dasharray="5 8" opacity=".38"/>')
    parts.append('<text x="58" y="684" fill="#58f0ae" font-size="11" font-weight="800">CONTROL PLANE OUTAGE TOLERANCE</text>')
    parts.append('<text class="small" x="300" y="684">valid local snapshots keep existing routes invokable.</text>')
    return shell(1200,710,"LSF system decomposition","The control plane compiles metadata; the data plane executes from local immutable snapshots.","".join(parts),animated)


def write_gif(svg_factory, output: Path, width: int, height: int, frames: int = 20, duration_ms: int = 140) -> None:
    rendered: list[Image.Image] = []
    for i in range(frames):
        phase = i / frames
        svg = svg_factory(False, phase)
        png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=width, output_height=height)
        img = Image.open(io.BytesIO(png)).convert("RGBA")
        base = Image.new("RGBA", img.size, BG)
        base.alpha_composite(img)
        rendered.append(base.convert("RGB"))
    palette_source = rendered[0].quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    palette = palette_source.getpalette()
    paletted = []
    for frame in rendered:
        q = frame.quantize(palette=palette_source, dither=Image.Dither.NONE)
        q.putpalette(palette)
        paletted.append(q)
    paletted[0].save(
        output,
        save_all=True,
        append_images=paletted[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    home = home_svg(True, 0)
    architecture = architecture_svg(True, 0)
    (OUT / "architecture-at-a-glance.svg").write_text(home, encoding="utf-8")
    (OUT / "system-decomposition.svg").write_text(architecture, encoding="utf-8")
    write_gif(home_svg, OUT / "architecture-at-a-glance.gif", 760, 386)
    write_gif(architecture_svg, OUT / "system-decomposition.gif", 760, 450)
    for asset in sorted(OUT.iterdir()):
        print(f"{asset.relative_to(ROOT)}\t{asset.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
