#!/usr/bin/env python3
"""Renderiza um pan cinematográfico animado a partir de um panorama equirectangular.

Sem IA: reprojecção gnomónica pura (mesma matemática de pano_views.py), pelo
que a geometria do imóvel fica perfeitamente rígida — nada de artefactos ou
"alucinações" de um gerador de vídeo. Interpola yaw/fov (e opcionalmente
pitch) com easing smoothstep ao longo dos frames, escreve cada frame para um
directório temporário e monta o clip final com ffmpeg (libx264, crf 18,
yuv420p).

Uso:
    python3 pipeline/pano_pan.py projects/<proj>/renders/sala.png \
        --out projects/<proj>/clips/sala.mp4 \
        --yaw-start -25 --yaw-end 20 --fov-start 72 --fov-end 66 \
        --pitch 0 --dur 5 --fps 30 --width 1920 --height 1080

Se --out for um directório (não terminar em .mp4), os frames PNG ficam lá e
não é feita montagem ffmpeg (útil para inspecção/debug).

Dependências: pip install numpy pillow; requer $FFMPEG (ver pipeline/env.sh).
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

# --- import de perspective_view a partir de pano_views.py (mesma pasta) ---
# Via importlib + caminho do ficheiro para funcionar independentemente do cwd
# ou de pano_views.py estar ou não num pacote instalado.
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("pano_views", _HERE / "pano_views.py")
_pano_views = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pano_views)
perspective_view = _pano_views.perspective_view


def smoothstep(t):
    """Ease-in-out clássico: 3t² - 2t³, t em [0, 1]."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def interp(start, end, t_eased):
    return start + (end - start) * t_eased


def render_frames(pano, out_dir, yaw_start, yaw_end, fov_start, fov_end,
                   pitch_start, pitch_end, width, height, n_frames):
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for i in range(n_frames):
        # n_frames-1 no denominador para que o último frame atinja exactamente o valor "end"
        t = i / max(n_frames - 1, 1)
        te = smoothstep(t)
        yaw = interp(yaw_start, yaw_end, te)
        fov = interp(fov_start, fov_end, te)
        pitch = interp(pitch_start, pitch_end, te)
        frame = perspective_view(pano, yaw, pitch, fov, width, height)
        Image.fromarray(frame).save(out_dir / f"frame_{i:04d}.png")
    elapsed = time.time() - t0
    print(f"[pano_pan] {n_frames} frames em {elapsed:.1f}s "
          f"({elapsed / n_frames:.2f}s/frame)", file=sys.stderr)


def assemble_mp4(frame_dir, out_path, fps, ffmpeg):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-framerate", str(fps),
        "-i", str(frame_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    print(f"[pano_pan] clip -> {out_path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pano", help="panorama equirectangular (PNG/JPG, 2:1)")
    ap.add_argument("--out", required=True,
                    help="ficheiro .mp4 de saída, ou directório para despejar frames PNG")
    ap.add_argument("--yaw-start", type=float, required=True)
    ap.add_argument("--yaw-end", type=float, required=True)
    ap.add_argument("--fov-start", type=float, default=70.0)
    ap.add_argument("--fov-end", type=float, default=64.0)
    ap.add_argument("--pitch", type=float, default=0.0,
                    help="pitch constante (graus); ignorado se --pitch-end for dado")
    ap.add_argument("--pitch-end", type=float, default=None,
                    help="se dado, interpola pitch de --pitch até este valor")
    ap.add_argument("--dur", type=float, default=5.0, help="duração em segundos")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--keep-frames", action="store_true",
                    help="não apagar o directório temporário de frames após montar o mp4")
    args = ap.parse_args()

    pitch_start = args.pitch
    pitch_end = args.pitch_end if args.pitch_end is not None else args.pitch

    pano = np.asarray(Image.open(args.pano).convert("RGB"))
    n_frames = max(int(round(args.dur * args.fps)), 2)

    out = Path(args.out)
    is_mp4 = out.suffix.lower() == ".mp4"

    if is_mp4:
        tmp_dir = Path(tempfile.mkdtemp(prefix="pano_pan_"))
        try:
            render_frames(pano, tmp_dir, args.yaw_start, args.yaw_end,
                          args.fov_start, args.fov_end, pitch_start, pitch_end,
                          args.width, args.height, n_frames)
            ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
            assemble_mp4(tmp_dir, out, args.fps, ffmpeg)
        finally:
            if args.keep_frames:
                dest = out.with_suffix("").parent / f"{out.stem}_frames"
                shutil.copytree(tmp_dir, dest, dirs_exist_ok=True)
                print(f"[pano_pan] frames preservados em {dest}", file=sys.stderr)
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        render_frames(pano, out, args.yaw_start, args.yaw_end,
                      args.fov_start, args.fov_end, pitch_start, pitch_end,
                      args.width, args.height, n_frames)


if __name__ == "__main__":
    main()
