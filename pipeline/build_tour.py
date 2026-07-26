#!/usr/bin/env python3
"""Monta um tour Pannellum estático a partir dos renders 360°.

Uso:
    python3 pipeline/build_tour.py projects/<projecto>

Espera em projects/<projecto>/:
    tour.json    — configuração (ver exemplo abaixo)
    renders/     — panoramas PNG produzidos pelo render.py

Produz projects/<projecto>/dist/ — site estático pronto a servir
(Cloudflare Pages, GitHub Pages, Netlify, qualquer host estático).

Exemplo de tour.json:
{
  "title": "Ocean Side — T2",
  "firstScene": "sala",
  "scenes": {
    "sala":    {"title": "Sala",     "pano": "sala.png",
                "hotSpots": [{"pitch": 0, "yaw": 90, "sceneId": "cozinha", "text": "Cozinha"}]},
    "cozinha": {"title": "Cozinha",  "pano": "cozinha.png",
                "hotSpots": [{"pitch": 0, "yaw": -90, "sceneId": "sala", "text": "Sala"}]}
  }
}
"""

import json
import shutil
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "tour" / "index.html"


def build(project_dir: Path) -> Path:
    cfg_path = project_dir / "tour.json"
    renders = project_dir / "renders"
    dist = project_dir / "dist"

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    dist.mkdir(exist_ok=True)
    panos_out = dist / "panos"
    panos_out.mkdir(exist_ok=True)

    scenes = {}
    for scene_id, scene in cfg["scenes"].items():
        src = renders / scene["pano"]
        if not src.exists():
            sys.exit(f"ERRO: render em falta: {src}")
        shutil.copy2(src, panos_out / scene["pano"])
        scenes[scene_id] = {
            "title": scene.get("title", scene_id),
            "type": "equirectangular",
            "panorama": f"panos/{scene['pano']}",
            "autoLoad": True,
            "yaw": scene.get("yaw", 0),
            "hotSpots": [
                {**hs, "type": "scene"} for hs in scene.get("hotSpots", [])
            ],
        }

    pannellum_cfg = {
        "default": {
            "firstScene": cfg["firstScene"],
            "sceneFadeDuration": 800,
            "autoLoad": True,
        },
        "scenes": scenes,
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{TITLE}}", cfg.get("title", "Tour Virtual"))
    html = html.replace("{{TOUR_CONFIG}}", json.dumps(pannellum_cfg, ensure_ascii=False, indent=2))
    (dist / "index.html").write_text(html, encoding="utf-8")

    return dist


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = build(Path(sys.argv[1]))
    print(f"[ok] tour em {out}/ — testar com: python3 -m http.server -d {out}")
