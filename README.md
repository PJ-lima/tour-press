# tour-press

Pipeline CGI para tours virtuais 360° de imóveis a partir de plantas 2D. Converte uma planta em PDF/DWG num modelo 3D Blender, renderiza panoramas equirectangulares e publica um tour web estático — sem backend, sem captação fotográfica no local.

## Como funciona

```
planta 2D ──(modelação programática)──▶ scene.blend
scene.blend ──render.py──▶ renders/*.png (equirect 360°)
renders/ ──build_tour.py──▶ dist/ (site estático Pannellum + minimapa da planta)
renders/ ──pano_views.py──▶ views/*.png (frames 16:9 para stills/vídeo)
renders/ ──pano_pan.py──▶ clips de vídeo (pans cinematográficos, sem IA)
renders/ ──teaser.py──▶ teaser.mp4 + teaser_9x16.mp4 (montagem completa)
```

## Stack

| Etapa | Ferramenta |
|---|---|
| Modelação e materiais | Blender 4.0.2 (headless, 100% programático via `bpy`) |
| Materiais e mobília | PBR de bibliotecas CC0 (`pipeline/pbr.py`, `assets/library/fetch.py`) |
| Render 360° | Cycles — equirectangular 6144×3072, 128 amostras |
| Tour web | [Pannellum](https://pannellum.org/) — site estático |
| Stills / vídeo | Reprojecção gnomónica (numpy + Pillow) + ffmpeg |

Toolchain 100% portátil, sem sudo: Blender e ffmpeg em tarballs, dependências Python em venv (`pipeline/env.sh`).

## Utilização

```bash
source pipeline/env.sh

# 0. (uma vez) descarregar as texturas/HDRI/modelos CC0 usados pelos materiais
$PY assets/library/fetch.py

# 1. construir a cena a partir do script de modelação do projecto
$BLENDER -b --factory-startup -P projects/<projecto>/model_*.py -- --stage all --save --qa

# 2. renderizar todos os panoramas (câmaras "360_*" na cena)
$BLENDER -b projects/<projecto>/scene.blend -P pipeline/render.py -- \
    --out projects/<projecto>/renders --samples 128 --res 6144

# 3. montar o tour (tour.json define cenas + hotspots)
$PY pipeline/build_tour.py projects/<projecto>

# 4. pré-visualizar
python3 -m http.server -d projects/<projecto>/dist

# 5. (opcional) teaser em 16:9 e 9:16 a partir dos mesmos panoramas
$PY pipeline/teaser.py projects/<projecto>
```

## Estrutura de um projecto

```
projects/<nome>/
├── geometry.py    # cotas das divisões, vãos e câmaras — fonte única, python puro
├── model_*.py     # modelação programática da cena (paredes, materiais, mobília, câmaras)
├── scene.blend    # gerado pelo model_*.py
├── tour.json      # config do tour (cenas + hotspots)
├── brand.json     # (opcional) cartão do promotor no tour — ver brand.example.json
├── renders/       # panoramas 360° (gerado)
└── dist/          # site final (gerado)
```

`geometry.py` não importa `bpy`: as mesmas cotas servem o Blender e o build, que valida cada hotspot contra o vão real antes de escrever o `dist/` e desenha o minimapa da planta em SVG (`pipeline/plan_svg.py`).

Convenções: câmaras `360_<divisão>` a 1,55 m; paredes interiores 0,12 m, exteriores 0,25 m; pé-direito 2,60 m; yaw = rumo de bússola, 0° na fachada envidraçada. O `--qa` do modelo recusa a cena se alguma câmara ficar dentro de mobília ou sem folga para a divisão.

O `model_t2.py` incluído demonstra o processo completo — geometria derivada de um dicionário de rectângulos por divisão, aberturas por segmentação de paredes, materiais PBR com texturas CC0 e verificação automática de folgas das câmaras.

## Demo

Tour de demonstração de um T2 (78 m²) modelado a partir de uma planta pública: [pj-lima.github.io/tour-press](https://pj-lima.github.io/tour-press/)
