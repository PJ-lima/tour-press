#!/usr/bin/env python3
"""Desenha a planta do projecto em SVG, a partir do módulo `geometry.py` do projecto.

O SVG é a base do minimapa do viewer: um `<circle data-scene="...">` por câmara, para o
`index.html` poder ligar cada ponto à cena correspondente do Pannellum.

É geometria nossa (a mesma que constrói a cena no Blender), não a planta do promotor —
nada com copyright de terceiros vai para o site.

Uso:
    python3 pipeline/plan_svg.py projects/<projecto>      # escreve o SVG no stdout
"""

import importlib.util
import sys
from pathlib import Path

# Espessura (em metros) da linha que "corta" a parede num vão. Tem de cobrir as duas
# faces de uma divisória interior (0.12) com folga, senão fica um risco de parede no meio
# da porta.
CUT_W = 0.22

STYLE = """
  .room  { fill: #f2ede5; stroke: #3c3a36; stroke-width: .07; }
  .outdoor { fill: #e4ecf1; stroke: #3c3a36; stroke-width: .07; stroke-dasharray: .18 .12; }
  .cut   { stroke: #f2ede5; stroke-linecap: butt; }
  .cut-out { stroke: #e4ecf1; }
  /* halo branco: o rótulo continua legível se um ponto de câmara passar por baixo */
  .label { fill: #6b665e; font: .32px system-ui, sans-serif; text-anchor: middle;
           stroke: #f2ede5; stroke-width: .13; paint-order: stroke; }
  .north { fill: #6b665e; font: .42px system-ui, sans-serif; text-anchor: middle; }
"""

# Rótulos das divisões no minimapa (ROOMS usa chaves internas).
ROOM_LABELS = {
    "suite": "Suite", "closet": "Closet", "is_suite": "I.S.", "quarto": "Quarto",
    "hall": "Distrib.", "is_social": "I.S.", "arrumo": "Arrumo", "sala": "Sala",
    "varanda": "Varanda",
}


def load_geometry(project_dir: Path):
    """Importa o geometry.py do projecto (cada projecto tem o seu)."""
    path = project_dir / "geometry.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"geometry_{project_dir.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_svg(g) -> str:
    """SVG da planta em coordenadas do mundo (metros), com Y invertido — norte para cima."""
    x0, x1, y0, y1 = g.BOUNDS
    w, h = x1 - x0, y1 - y0

    def X(x):
        return round(x - x0, 3)

    def Y(y):
        return round(y1 - y, 3)     # inverte: mundo cresce para norte, SVG para baixo

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" '
        f'class="plan" role="img" aria-label="Planta do apartamento">',
        f"<style>{STYLE}</style>",
    ]

    # divisões
    for name, (rx0, rx1, ry0, ry1) in g.ROOMS.items():
        cls = "outdoor" if name == "varanda" else "room"
        out.append(f'<rect class="{cls}" x="{X(rx0)}" y="{Y(ry1)}" '
                   f'width="{round(rx1 - rx0, 3)}" height="{round(ry1 - ry0, 3)}"/>')

    # vãos: linha da cor do preenchimento por cima da parede, a abrir a passagem
    for a, b, *_ in g.DOORS:
        seg = g.opening_segment(a, b)
        if seg:
            (ax, ay), (bx, by) = seg
            out.append(f'<line class="cut" x1="{X(ax)}" y1="{Y(ay)}" x2="{X(bx)}" '
                       f'y2="{Y(by)}" stroke-width="{CUT_W}"/>')

    # envidraçados da fachada: cortam a parede exterior e ficam a azul (é vidro, não porta)
    for room, gx0, gx1 in g.GLAZING:
        seg = g.opening_segment(room, "varanda")
        (ax, ay), (bx, by) = seg
        out.append(f'<line class="cut cut-out" x1="{X(ax)}" y1="{Y(ay)}" x2="{X(bx)}" '
                   f'y2="{Y(by)}" stroke-width="{CUT_W}"/>')

    # porta de entrada (parede sul da sala)
    room, ex0, ex1, _ = g.ENTRANCE
    _, _, ery0, _ = g.ROOMS[room]
    out.append(f'<line class="cut" x1="{X(ex0)}" y1="{Y(ery0)}" x2="{X(ex1)}" '
               f'y2="{Y(ery0)}" stroke-width="{CUT_W}"/>')

    # rótulos: encostados ao topo da divisão, para não caírem em cima do ponto de câmara
    # (que está sensivelmente ao centro). Nas divisões baixas a folga é menor, daí o min().
    for name, (rx0, rx1, ry0, ry1) in g.ROOMS.items():
        label = ROOM_LABELS.get(name, name)
        if name == "varanda":
            # a varanda toca o topo do viewBox: encostar ao topo punha o rótulo em cima
            # do próprio contorno. Fica a meia altura e desviado do ponto de câmara.
            cx, ty = rx0 + (rx1 - rx0) * 0.22, (ry0 + ry1) / 2 - 0.1
        else:
            cx = (rx0 + rx1) / 2
            ty = ry1 - min(0.32, (ry1 - ry0) * 0.28)
        out.append(f'<text class="label" x="{X(cx)}" y="{Y(ty):.3f}">{label}</text>')

    # rosa-dos-ventos: o norte é +Y do mundo, logo o topo do SVG
    out.append(f'<text class="north" x="{round(w - 0.45, 2)}" y="0.55">N ↑</text>')

    # pontos de câmara — um por cena do tour; `data-scene` liga ao Pannellum
    for scene, spot in sorted(_scene_spots(g).items()):
        sx, sy = g.CAM_SPOTS[spot]
        out.append(f'<g class="cam" data-scene="{scene}" tabindex="0" role="button">'
                   f'<title>{scene}</title>'
                   f'<path class="cone" d=""/>'
                   f'<circle class="dot" cx="{X(sx)}" cy="{Y(sy)}" r="0.19"/></g>')

    out.append("</svg>")
    return "\n".join(out)


def _scene_spots(g):
    """cena do tour → chave em CAM_SPOTS (a cena `is` mora no ponto `is_suite`)."""
    return {cam.removeprefix("360_"): spot for cam, spot in g.CAM_ROOM.items()}


def cam_points(g):
    """{cena: [x_svg, y_svg]} — o viewer precisa disto para desenhar o cone de visão."""
    x0, _, _, y1 = g.BOUNDS
    return {scene: [round(g.CAM_SPOTS[spot][0] - x0, 3),
                    round(y1 - g.CAM_SPOTS[spot][1], 3)]
            for scene, spot in _scene_spots(g).items()}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    geom = load_geometry(Path(sys.argv[1]))
    if geom is None:
        sys.exit(f"ERRO: {sys.argv[1]}/geometry.py não existe")
    print(build_svg(geom))
