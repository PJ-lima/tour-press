#!/usr/bin/env python3
"""Extrai vistas em perspectiva (rectilineares) de um panorama equirectangular.

Gera frames "fotográficos" a partir dos panoramas 360° — input para:
  - geração de vídeo IA (Higgsfield image-to-video, clips do teaser)
  - stills de marketing do empreendimento

Uso:
    python3 pipeline/pano_views.py projects/<proj>/renders/sala.png \
        --out projects/<proj>/views [--yaws 0,90,180,270] [--pitch 0] \
        [--fov 75] [--width 1920] [--height 1080]

Dependências: pip install numpy pillow
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def perspective_view(pano, yaw_deg, pitch_deg, fov_deg, width, height):
    """Projecção gnomónica: recorta uma vista rectilinear do equirect."""
    ph, pw = pano.shape[:2]
    yaw, pitch, fov = map(np.radians, (yaw_deg, pitch_deg, fov_deg))

    f = (width / 2) / np.tan(fov / 2)
    u = np.arange(width) - (width - 1) / 2
    v = (height - 1) / 2 - np.arange(height)
    uu, vv = np.meshgrid(u, v)

    # raios em coords de câmara (X direita, Y cima, Z frente), normalizados
    d = np.stack([uu, vv, np.full_like(uu, f)], axis=-1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)

    # pitch (em torno de X), depois yaw (em torno de Y)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    y, z = y * cp - z * sp, y * sp + z * cp
    x, z = x * cy + z * sy, -x * sy + z * cy

    lon = np.arctan2(x, z)          # [-pi, pi], 0 = frente
    lat = np.arcsin(np.clip(y, -1, 1))

    # coords no panorama (wrap em X, clamp em Y) + amostragem bilinear
    px = (lon / (2 * np.pi) + 0.5) * pw - 0.5
    py = (0.5 - lat / np.pi) * ph - 0.5

    x0 = np.floor(px).astype(int)
    y0 = np.floor(py).astype(int)
    wx = (px - x0)[..., None]
    wy = (py - y0)[..., None]
    x0m, x1m = x0 % pw, (x0 + 1) % pw
    y0c = np.clip(y0, 0, ph - 1)
    y1c = np.clip(y0 + 1, 0, ph - 1)

    p = pano.astype(np.float32)
    top = p[y0c, x0m] * (1 - wx) + p[y0c, x1m] * wx
    bot = p[y1c, x0m] * (1 - wx) + p[y1c, x1m] * wx
    out = top * (1 - wy) + bot * wy
    return np.clip(out, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pano", help="panorama equirectangular (PNG/JPG, 2:1)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--yaws", default="0,90,180,270",
                    help="ângulos horizontais em graus, separados por vírgula")
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--fov", type=float, default=75.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args()

    pano = np.asarray(Image.open(args.pano).convert("RGB"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.pano).stem

    for yaw in (float(s) for s in args.yaws.split(",")):
        img = perspective_view(pano, yaw, args.pitch, args.fov,
                               args.width, args.height)
        dest = out_dir / f"{stem}_yaw{int(yaw):03d}.png"
        Image.fromarray(img).save(dest)
        print(f"[view] {dest}")


if __name__ == "__main__":
    main()
