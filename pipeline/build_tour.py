#!/usr/bin/env python3
"""Monta um tour Pannellum estático a partir dos renders 360°.

Uso:
    source pipeline/env.sh && $PY pipeline/build_tour.py projects/<projecto>

O python do venv ($PY) tem Pillow, e com Pillow os panoramas vão para o dist em JPEG em
vez de PNG (35 MB -> ~1 MB por cena a 6K). Com o python do sistema funciona à mesma, mas
o site fica com os PNG originais.

Espera em projects/<projecto>/:
    tour.json    — configuração (ver exemplo abaixo)
    renders/     — panoramas PNG produzidos pelo render.py
    geometry.py  — opcional; se existir, o build valida os hotspots contra os vãos reais
                   e gera o minimapa da planta

Produz projects/<projecto>/dist/ — site estático pronto a servir
(Cloudflare Pages, GitHub Pages, Netlify, qualquer host estático).

Exemplo de tour.json:
{
  "title": "T2 demo",
  "firstScene": "sala",
  "scenes": {
    "sala":    {"title": "Sala",     "pano": "sala.png",
                "hotSpots": [{"pitch": 0, "yaw": 90, "sceneId": "cozinha", "text": "Cozinha"}]},
    "cozinha": {"title": "Cozinha",  "pano": "cozinha.png",
                "hotSpots": [{"pitch": 0, "yaw": -90, "sceneId": "sala", "text": "Sala"}]}
  }
}
"""

import importlib.util
import json
import math
import re
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
TEMPLATE = _HERE.parent / "templates" / "tour" / "index.html"

_spec = importlib.util.spec_from_file_location("plan_svg", _HERE / "plan_svg.py")
plan_svg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_svg)

# Tolerância do aviso de descentramento: fracção do meio-arco do vão a partir da qual o
# hotspot, embora dentro do vão, já se lê como "colado ao bordo".
OFF_CENTRE_WARN = 0.60


def bearing(dx, dy):
    """Rumo tipo bússola em graus: 0 = +Y (Norte), positivo para Este.

    Mesma convenção do render equirectangular e do yaw do Pannellum — ver
    `_yawConvention` em tour.json.
    """
    return math.degrees(math.atan2(dx, dy))


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def check_hotspots(cfg, geom):
    """Verifica que cada hotspot aponta a um vão real e não a parede maciça.

    Devolve (erros, avisos, linhas_de_relatorio). Não escreve nada em disco — corre antes
    de o build tocar no `dist/`.
    """
    errors, warns, report = [], [], []
    scenes = cfg["scenes"]
    spots = {cam.removeprefix("360_"): spot for cam, spot in geom.CAM_ROOM.items()}

    for scene_id, scene in scenes.items():
        for hs in scene.get("hotSpots", []):
            target = hs.get("sceneId")
            label = f"{scene_id} → {target}"
            if target not in scenes:
                errors.append(f"{label}: cena de destino não existe")
                continue
            if scene_id not in spots or target not in spots:
                errors.append(f"{label}: cena sem ponto de câmara em CAM_ROOM")
                continue

            room_a = geom.SCENE_ROOM[scene_id]
            room_b = geom.SCENE_ROOM[target]
            if room_a == room_b:
                report.append(f"  {label}: mesma divisão, sem vão a verificar")
                continue

            seg = geom.opening_segment(room_a, room_b)
            if seg is None:
                errors.append(f"{label}: não há vão entre {room_a} e {room_b}")
                continue

            cx, cy = geom.CAM_SPOTS[spots[scene_id]]
            b0 = bearing(seg[0][0] - cx, seg[0][1] - cy)
            b1 = bearing(seg[1][0] - cx, seg[1][1] - cy)
            # arco relativo a b0 pelo caminho curto — o vão nunca subtende 180° ou mais
            span = wrap180(b1 - b0)
            centre = wrap180(b0 + span / 2.0)
            half = abs(span) / 2.0
            delta = wrap180(hs["yaw"] - centre)

            if abs(delta) > half:
                # os limites saem do centro ± meio-arco, não de min/max de b0/b1: um vão a
                # cavalo dos ±180° daria o arco complementar (o de fora) com min/max
                errors.append(
                    f"{label}: yaw {hs['yaw']:+.1f}° cai FORA do vão "
                    f"[{wrap180(centre - half):+.1f}°, {wrap180(centre + half):+.1f}°] — "
                    f"aponta a parede. Centro do vão: {centre:+.1f}°")
            else:
                mark = " "
                if half > 0 and abs(delta) / half > OFF_CENTRE_WARN:
                    warns.append(f"{label}: yaw {hs['yaw']:+.1f}° dentro do vão mas a "
                                 f"{abs(delta):.1f}° do centro ({centre:+.1f}°)")
                    mark = "!"
                report.append(f" {mark}{label}: yaw {hs['yaw']:+.1f}° · "
                              f"centro {centre:+.1f}° · meio-arco ±{half:.1f}°")

    # Todas as cenas têm de ser alcançáveis a partir da primeira — foi assim que a suite
    # ficou inacessível pelo interior sem ninguém dar por isso.
    seen, queue = {cfg["firstScene"]}, [cfg["firstScene"]]
    while queue:
        cur = queue.pop()
        for hs in scenes.get(cur, {}).get("hotSpots", []):
            nxt = hs.get("sceneId")
            if nxt in scenes and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    unreachable = sorted(set(scenes) - seen)
    if unreachable:
        errors.append("cenas inalcançáveis a partir de "
                      f"'{cfg['firstScene']}': {', '.join(unreachable)}")

    return errors, warns, report


JPEG_QUALITY = 88

# Largura máxima do panorama publicado. O Pannellum carrega o equirectangular como UMA
# textura WebGL; o limite de muitos telemóveis é 4096 px e acima disso a cena não carrega.
# Os renders em 6K ficam como masters (teasers, stills, futura versão multi-resolução).
PUBLISH_MAX_W = 4096


def publish_pano(src: Path, dest_dir: Path) -> str:
    """Prepara o panorama para o dist: reduz a PUBLISH_MAX_W e converte PNG em JPEG.

    Um equirectangular 6144×3072 em PNG anda pelos 35 MB; dez cenas seriam 350 MB de
    site estático. Em JPEG q88 o mesmo pano fica em ~1 MB sem diferença visível num
    viewer 360. Os PNG em renders/ continuam a ser os masters.

    Sem Pillow (o python do sistema não o tem — usar $PY do venv), copia tal e qual.
    """
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(src, dest_dir / src.name)
        return src.name

    out = dest_dir / (src.stem + ".jpg")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out.name
    im = Image.open(src).convert("RGB")
    if im.width > PUBLISH_MAX_W:
        im = im.resize((PUBLISH_MAX_W, PUBLISH_MAX_W // 2), Image.LANCZOS)
    im.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.name


def cta_html(project_dir: Path) -> str:
    """Cartão de contacto do promotor, lido de `brand.json` ao lado de `tour.json`.

    O ficheiro não é commitado (ver .gitignore): este repositório é público e os contactos
    do cliente não têm nada que aqui estar. Sem `brand.json` o tour sai sem cartão, que é
    o comportamento certo para uma demonstração.

    Campos: name (obrigatório), tagline, url, phone, email.
    """
    src = project_dir / "brand.json"
    if not src.exists():
        return ""
    b = json.loads(src.read_text(encoding="utf-8"))
    name = b.get("name")
    if not name:
        return ""

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    rows = ['<div class="cta-name">%s</div>' % esc(name)]
    if b.get("tagline"):
        rows.append('<div class="cta-line">%s</div>' % esc(b["tagline"]))
    links = []
    if b.get("phone"):
        links.append('<a href="tel:%s">%s</a>'
                     % (esc(re.sub(r"[^\d+]", "", b["phone"])), esc(b["phone"])))
    if b.get("email"):
        links.append('<a href="mailto:%s">%s</a>' % (esc(b["email"]), esc(b["email"])))
    if b.get("url"):
        links.append('<a href="%s" target="_blank" rel="noopener">%s</a>'
                     % (esc(b["url"]), esc(b.get("url_label", "Ficha do imóvel"))))
    if links:
        rows.append('<div class="cta-links">%s</div>' % " · ".join(links))
    return "".join(rows)


def build(project_dir: Path) -> Path:
    cfg_path = project_dir / "tour.json"
    renders = project_dir / "renders"
    dist = project_dir / "dist"

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    geom = plan_svg.load_geometry(project_dir)

    # --- validação antes de qualquer escrita ---
    if geom is None:
        print("[aviso] sem geometry.py — hotspots não verificados, minimapa desligado")
    else:
        errors, warns, report = check_hotspots(cfg, geom)
        print("\n".join(report))
        for w in warns:
            print(f"[aviso] {w}")
        if errors:
            for e in errors:
                print(f"[ERRO] {e}", file=sys.stderr)
            sys.exit(f"build abortado: {len(errors)} hotspot(s) inválido(s)")
        print(f"[ok] {len(report)} hotspots verificados contra os vãos reais")

    for scene in cfg["scenes"].values():
        src = renders / scene["pano"]
        if not src.exists():
            sys.exit(f"ERRO: render em falta: {src}")

    # Panos mais velhos que o modelo = tour a mostrar mobília/câmaras que já não existem.
    # Aviso, não erro: às vezes só se mexe em cotas que não afectam a imagem.
    model = project_dir / "model_t2.py"
    newest_src = max((f.stat().st_mtime for f in (model, project_dir / "geometry.py")
                      if f.exists()), default=0)
    stale = sorted(s["pano"] for s in cfg["scenes"].values()
                   if (renders / s["pano"]).stat().st_mtime < newest_src)
    if stale:
        print(f"[aviso] {len(stale)} panoramas mais antigos que o modelo — re-renderizar: "
              f"{', '.join(stale)}")

    # --- a partir daqui escreve-se ---
    dist.mkdir(exist_ok=True)
    panos_out = dist / "panos"
    panos_out.mkdir(exist_ok=True)

    scenes = {}
    for scene_id, scene in cfg["scenes"].items():
        pano = publish_pano(renders / scene["pano"], panos_out)
        scenes[scene_id] = {
            "title": scene.get("title", scene_id),
            "type": "equirectangular",
            "panorama": f"panos/{pano}",
            "autoLoad": True,
            "yaw": scene.get("yaw", 0),
            "hotSpots": [
                {**hs, "type": "scene"} for hs in scene.get("hotSpots", [])
            ],
        }

    # limpa panos de builds anteriores (renomeados, convertidos para JPEG, cenas removidas)
    published = {s["panorama"].split("/")[-1] for s in scenes.values()}
    for old in panos_out.iterdir():
        if old.name not in published:
            old.unlink()

    pannellum_cfg = {
        "default": {
            "firstScene": cfg["firstScene"],
            "sceneFadeDuration": 800,
            "autoLoad": True,
        },
        "scenes": scenes,
    }

    minimap = plan_svg.build_svg(geom) if geom else ""
    cams = plan_svg.cam_points(geom) if geom else {}

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{TITLE}}", cfg.get("title", "Tour Virtual"))
    html = html.replace("{{CTA}}", cta_html(project_dir))
    html = html.replace("{{TOUR_CONFIG}}", json.dumps(pannellum_cfg, ensure_ascii=False, indent=2))
    html = html.replace("{{MINIMAP_SVG}}", minimap)
    html = html.replace("{{CAM_POINTS}}", json.dumps(cams, ensure_ascii=False))
    (dist / "index.html").write_text(html, encoding="utf-8")

    return dist


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = build(Path(sys.argv[1]))
    print(f"[ok] tour em {out}/ — testar com: python3 -m http.server -d {out}")
