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
    parser.add_argument("--only", default="", help="lista separada por vírgulas de divisões "
                        "a renderizar (ex.: quarto,suite); vazio = todas")
    return parser.parse_args(argv)


def setup_cycles(scene, samples, width):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    prefs = bpy.context.preferences.addons.get("cycles")
    if prefs:
        # Definir compute_device_type não chega: sem get_devices() + device.use=True o
        # Cycles não vê nenhum dispositivo e renderiza em CPU à mesma, em silêncio.
        cprefs = prefs.preferences
        enabled = []
        for kind in ("OPTIX", "CUDA"):
            try:
                cprefs.compute_device_type = kind
            except TypeError:
                continue
            devices = cprefs.get_devices_for_type(kind) if hasattr(
                cprefs, "get_devices_for_type") else []
            enabled = [d for d in devices if d.type == kind]
            for d in devices:
                d.use = (d.type == kind)
            if enabled:
                break
        if enabled:
            scene.cycles.device = "GPU"
            print(f"[render] GPU {kind}: {', '.join(d.name for d in enabled)}")
        else:
            scene.cycles.device = "CPU"
            print("[render] sem GPU disponível — CPU")
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
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        cams = [c for c in cams if c.name.removeprefix("360_") in wanted]
        missing = wanted - {c.name.removeprefix("360_") for c in cams}
        if missing:
            print(f"ERRO: sem câmara para {', '.join(sorted(missing))}", file=sys.stderr)
            sys.exit(1)
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
