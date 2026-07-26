"""Render de panoramas 360° equirectangulares — um por câmara — via Blender headless.

Uso:
    blender -b projects/<projecto>/scene.blend -P pipeline/render.py -- \
        --out projects/<projecto>/renders [--samples 128] [--res 4096]

Convenção: toda a câmara cujo nome começa por "360_" é renderizada uma vez.
    Câmara "360_sala"    -> <out>/sala.png
    Câmara "360_quarto1" -> <out>/quarto1.png

Colocar as câmaras a ~1.55 m do chão, no centro de cada divisão.
"""

import argparse
import os
import sys

import bpy


def parse_args():
    # Blender passa os args do script depois de "--"
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="pasta de destino dos renders")
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--res", type=int, default=4096, help="largura; altura = largura/2")
    return parser.parse_args(argv)


def setup_cycles(scene, samples, width):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    prefs = bpy.context.preferences.addons.get("cycles")
    if prefs:
        # usa GPU se existir; cai para CPU sem falhar
        try:
            prefs.preferences.compute_device_type = "CUDA"
            scene.cycles.device = "GPU"
        except TypeError:
            scene.cycles.device = "CPU"
    scene.render.resolution_x = width
    scene.render.resolution_y = width // 2
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"


def make_panoramic(cam_obj):
    cam = cam_obj.data
    cam.type = "PANO"
    # Cycles: panorama equirectangular
    if hasattr(cam, "panorama_type"):
        cam.panorama_type = "EQUIRECTANGULAR"
    else:  # Blender >= 3.x guarda no cycles settings
        cam.cycles.panorama_type = "EQUIRECTANGULAR"


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    scene = bpy.context.scene
    setup_cycles(scene, args.samples, args.res)

    cams = [o for o in scene.objects if o.type == "CAMERA" and o.name.startswith("360_")]
    if not cams:
        print("ERRO: nenhuma câmara '360_*' na cena", file=sys.stderr)
        sys.exit(1)

    for cam_obj in cams:
        make_panoramic(cam_obj)
        scene.camera = cam_obj
        room = cam_obj.name.removeprefix("360_")
        scene.render.filepath = os.path.join(args.out, f"{room}.png")
        print(f"[render] {cam_obj.name} -> {scene.render.filepath}")
        bpy.ops.render.render(write_still=True)

    print(f"[ok] {len(cams)} panoramas em {args.out}")


if __name__ == "__main__":
    main()
