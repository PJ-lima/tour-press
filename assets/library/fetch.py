#!/usr/bin/env python3
"""Descarrega a biblioteca de materiais e modelos CC0 usada pelos projectos.

Tudo vem do Poly Haven (polyhaven.com), licença CC0 — uso comercial livre, sem atribuição
obrigatória. Os ficheiros não são commitados (ver .gitignore); este script + o MANIFEST
abaixo são a fonte de verdade, e qualquer máquina reconstrói a biblioteca com:

    python3 assets/library/fetch.py

Estrutura produzida:
    assets/library/texturas/<slug>/{diffuse,rough,normal,ao,disp}.jpg
    assets/library/hdri/<slug>.hdr
    assets/library/modelos/<slug>.blend   (+ texturas do modelo ao lado)
"""

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.polyhaven.com/files/"

# Resolução por tipo. 2k chega para superfícies que ladrilham (o pano final é 6k mas cada
# textura cobre uma fracção pequena do quadro); o HDRI leva 4k por ser o fundo do mar.
TEX_RES = "2k"
HDRI_RES = "4k"

# slug -> mapas a guardar. As chaves da API do Poly Haven não são uniformes entre assets,
# daí a lista de alternativas por mapa.
MAPS = {
    "diffuse": ("Diffuse", "diff", "Color", "col"),
    "rough": ("Rough", "rough", "Roughness"),
    "normal": ("nor_gl", "Normal", "nor"),
    "ao": ("AO", "ao"),
    "disp": ("Displacement", "disp"),
}

# Nota sobre o difuso destas amostras: são fotografias com a luz do dia lá dentro, todas
# quentes e escuras. O `beige_wall_001` e o `rough_linen` entram no modelo só pelo relevo
# (normal + rugosidade) — a cor vem lisa do model_t2.py, senão a casa saía sépia e a roupa
# de cama azul. Ver pbr.tex_material(base_color=...).
TEXTURES = {
    "wood_floor":      "soalho de madeira — sala, quartos, hall",
    "beige_wall_001":  "reboco pintado — paredes interiores (só relevo)",
    "marble_01":       "mármore — bancada da cozinha",
    "rough_linen":     "linho — roupa de cama, sofá, cortinados (só relevo)",
}

HDRIS = {
    "kloofendal_48d_partly_cloudy_puresky":
        "tarde limpa, sem chão — o mar é geometria nossa. O pôr-do-sol que estava aqui "
        "antes punha uma dominante laranja em tudo e branqueava o mar.",
}

MODELS = {
    "potted_plant_04":   "planta de chão — sala",
    "potted_plant_01":   "planta de chão — suite e hall",
    "throw_pillows_01":  "almofadas — sofá e camas",
    "dining_chair_02":   "cadeiras da mesa de jantar",
    "wooden_bowl_01":    "taça — mesa de jantar",
    "wicker_basket_01":  "cesto — closet",
    "ceramic_vase_02":   "jarra — bancada da cozinha",
}


# O Poly Haven devolve 403 ao User-Agent por omissão do urllib.
UA = {"User-Agent": "tour-press/1.0 (build script; contacto via repositório)"}


def _open(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)


def api(slug):
    with _open(API + slug) as r:
        return json.load(r)


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  = {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  + {dest.name}")
    with _open(url) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def pick(files, names, res, fmt="jpg"):
    """Primeiro mapa que existir, na resolução pedida."""
    for name in names:
        entry = files.get(name, {}).get(res, {})
        if fmt in entry:
            return entry[fmt]["url"]
        for any_fmt in entry.values():          # png quando não há jpg
            if isinstance(any_fmt, dict) and "url" in any_fmt:
                return any_fmt["url"]
    return None


def fetch_textures():
    for slug, desc in TEXTURES.items():
        print(f"[textura] {slug} — {desc}")
        files = api(slug)
        for local, names in MAPS.items():
            url = pick(files, names, TEX_RES)
            if url:
                download(url, HERE / "texturas" / slug / f"{local}.jpg")


def fetch_hdris():
    for slug, desc in HDRIS.items():
        print(f"[hdri] {slug} — {desc}")
        url = api(slug)["hdri"][HDRI_RES]["hdr"]["url"]
        download(url, HERE / "hdri" / f"{slug}.hdr")


def fetch_models():
    for slug, desc in MODELS.items():
        print(f"[modelo] {slug} — {desc}")
        entry = api(slug)["blend"][TEX_RES]["blend"]
        out = HERE / "modelos" / slug
        download(entry["url"], out / f"{slug}.blend")
        # o .blend referencia as texturas por caminho relativo — têm de vir também
        for rel, info in entry.get("include", {}).items():
            download(info["url"], out / rel)


if __name__ == "__main__":
    what = sys.argv[1:] or ["texturas", "hdri", "modelos"]
    if "texturas" in what:
        fetch_textures()
    if "hdri" in what:
        fetch_hdris()
    if "modelos" in what:
        fetch_models()
    print("[ok] biblioteca em", HERE)
