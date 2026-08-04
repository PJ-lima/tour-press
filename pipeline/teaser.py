#!/usr/bin/env python3
"""Monta o teaser do projecto a partir dos panoramas 6K, em 16:9 e 9:16.

    python3 pipeline/teaser.py projects/demo-t2 [--only 16x9|9x16]

Cada plano é um pan gnomónico sobre um equirectangular (pipeline/pano_pan.py): a geometria
fica rígida, sem geração por IA e sem custo por segundo. Esta receita vivia espalhada por
notas de sessão e por um script em /tmp; passa a estar aqui, que é o que permite refazer o
teaser depois de cada re-render sem redescobrir yaws e durações.

Dependências: numpy, pillow e $FFMPEG (ver pipeline/env.sh).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FPS = 30
XFADE = 0.7          # sobreposição entre planos, em segundos

# Planos, por ordem. O pitch negativo é o que faz a diferença entre "fotografia de imóvel"
# e "fotografia de tecto": a câmara está a 1,55 m e o que interessa (mobiliário, soalho,
# mar) está abaixo da horizontal.
#
# Os yaws são rumos de bússola e o Norte é a fachada envidraçada: arcos centrados em 0
# apontam ao vidro em todas as divisões e o teaser saía a mostrar janelas em vez de casa.
# Cada arco abaixo começa e acaba em conteúdo verificado plano a plano no equirectangular.
SHOTS = [
    # cena       yaw0   yaw1  fov0  fov1  pitch0 pitch1  dur
    ("sala",    245.0, 330.0, 76.0, 68.0, -13.0,  -8.0, 4.6),   # sofá+quadro > mesa+mar
    ("cozinha", 130.0,  85.0, 72.0, 68.0, -12.0, -16.0, 4.0),   # bancada > placa e lava-loiça
    ("quarto",  148.0, 192.0, 72.0, 64.0, -10.0,  -6.0, 4.2),   # porta > cama
    # a suite levava o mesmo arco do quarto e os dois planos liam-se como o mesmo quarto:
    # aqui vai ao contrário (da cama para o corredor) e mais fechado
    ("suite",   205.0, 152.0, 68.0, 60.0,  -9.0,  -5.0, 4.4),
    ("varanda", 215.0, 285.0, 78.0, 70.0,  -6.0,  -2.0, 4.4),   # suite pelo vidro > deque+mar
]

FORMATS = {
    "16x9": {"w": 1920, "h": 1080, "fov_mult": 1.00, "title_pt": 96, "sub_pt": 40},
    "9x16": {"w": 1080, "h": 1920, "fov_mult": 0.66, "title_pt": 88, "sub_pt": 38},
}

CARD_BG = (24, 26, 28)
CARD_FG = (247, 245, 241)
CARD_ACCENT = (200, 86, 43)


def font(size, bold=False):
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),):
        for base in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/TTF/"):
            p = Path(base) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def endcard(path, w, h, title, lines, title_pt, sub_pt):
    """Cartão final. O texto vai sobre fundo sólido e não sobre o render: por cima de uma
    imagem clara o título branco desaparecia, que era o defeito do teaser anterior."""
    img = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(img)

    def fit(text, size, bold, limit):
        """Encolhe até caber na largura útil — o mesmo título tem de servir 1920 e 1080."""
        f = font(size, bold=bold)
        while size > 12 and d.textlength(text, font=f) > limit:
            size -= 2
            f = font(size, bold=bold)
        return f, size

    ft, title_pt = fit(title, title_pt, True, w * 0.86)
    sub_pt = min([sub_pt] + [fit(t, sub_pt, False, w * 0.86)[1] for t in lines])
    fs = font(sub_pt)

    def centre(text, f, y, fill):
        box = d.textbbox((0, 0), text, font=f)
        d.text(((w - (box[2] - box[0])) / 2 - box[0], y), text, font=f, fill=fill)
        return box[3] - box[1]

    total = title_pt * 1.35 + len(lines) * sub_pt * 1.7
    y = (h - total) / 2
    y += centre(title, ft, y, CARD_FG) + title_pt * 0.65
    d.line([(w * 0.38, y), (w * 0.62, y)], fill=CARD_ACCENT, width=max(2, h // 540))
    y += sub_pt * 0.9
    for line in lines:
        y += centre(line, fs, y, CARD_FG) + sub_pt * 0.9
    img.save(path)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def build(project: Path, fmt: str, title: str, lines) -> Path:
    spec = FORMATS[fmt]
    renders = project / "renders"
    work = Path(tempfile.mkdtemp(prefix="teaser_"))
    clips = []
    try:
        for scene, y0, y1, f0, f1, p0, p1, dur in SHOTS:
            pano = renders / f"{scene}.png"
            if not pano.exists():
                print(f"[teaser] falta {pano.name} — plano saltado")
                continue
            out = work / f"{scene}.mp4"
            run([sys.executable, str(HERE / "pano_pan.py"), str(pano), "--out", str(out),
                 "--yaw-start", str(y0), "--yaw-end", str(y1),
                 "--fov-start", str(f0 * spec["fov_mult"]),
                 "--fov-end", str(f1 * spec["fov_mult"]),
                 "--pitch", str(p0), "--pitch-end", str(p1),
                 "--dur", str(dur), "--fps", str(FPS),
                 "--width", str(spec["w"]), "--height", str(spec["h"])])
            clips.append((out, dur))
            print(f"[teaser] {fmt} plano {scene} ({dur:.1f}s)")

        if not clips:
            raise SystemExit("[teaser] nenhum panorama encontrado em " + str(renders))

        card_png = work / "endcard.png"
        endcard(card_png, spec["w"], spec["h"], title, lines,
                spec["title_pt"], spec["sub_pt"])
        card_mp4 = work / "endcard.mp4"
        run([FFMPEG, "-y", "-loop", "1", "-t", "2.6", "-i", str(card_png),
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "18",
             str(card_mp4)])
        clips.append((card_mp4, 2.6))

        # xfade encadeado: cada corte come XFADE segundos, daí o offset acumulado
        args, filters, prev, offset = [], [], "0:v", 0.0
        for i, (path, _) in enumerate(clips):
            args += ["-i", str(path)]
        for i in range(1, len(clips)):
            offset += clips[i - 1][1] - XFADE
            label = f"x{i}"
            filters.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XFADE}:"
                           f"offset={offset:.3f}[{label}]")
            prev = label
        out = project / (f"teaser_{fmt}.mp4" if fmt != "16x9" else "teaser.mp4")
        run([FFMPEG, "-y"] + args + ["-filter_complex", ";".join(filters),
             "-map", f"[{prev}]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
             "-r", str(FPS), str(out)])
        total = sum(d for _, d in clips) - XFADE * (len(clips) - 1)
        print(f"[teaser] {out} — {spec['w']}×{spec['h']}, {total:.1f}s")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--only", choices=sorted(FORMATS), default=None)
    ap.add_argument("--title", default=None)
    a = ap.parse_args()

    project = Path(a.project).resolve()
    import json
    cfg = json.loads((project / "tour.json").read_text(encoding="utf-8"))
    title = a.title or cfg.get("title", project.name).split("—")[0].strip()
    lines = ["Tour virtual 360° · planta interactiva", "Visita todas as divisões online"]
    for fmt in ([a.only] if a.only else list(FORMATS)):
        build(project, fmt, title, lines)
