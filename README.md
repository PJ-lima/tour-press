# tour-press

Pipeline CGI para tours virtuais 360° de imóveis a partir de plantas 2D. Converte uma planta em PDF/DWG num modelo 3D Blender, renderiza panoramas equirectangulares e publica um tour web estático — sem backend, sem captação fotográfica no local.

## Como funciona

```
planta 2D ──(modelação programática)──▶ scene.blend
scene.blend ──render.py──▶ renders/*.png (equirect 360°)
renders/ ──build_tour.py──▶ dist/ (site estático Pannellum)
renders/ ──pano_views.py──▶ views/*.png (frames 16:9 para stills/vídeo)
renders/ ──pano_pan.py──▶ clips de vídeo (pans cinematográficos, sem IA)
```

## Stack

| Etapa | Ferramenta |
|---|---|
| Modelação e materiais | Blender 4.2 LTS (headless, 100% programático via `bpy`) |
| Render 360° | Cycles — equirectangular 4096×2048 |
| Tour web | [Pannellum](https://pannellum.org/) — site estático |
| Stills / vídeo | Reprojecção gnomónica (numpy + Pillow) + ffmpeg |

Toolchain 100% portátil, sem sudo: Blender e ffmpeg em tarballs, dependências Python em venv (`pipeline/env.sh`).

## Utilização

```bash
source pipeline/env.sh

# 1. construir a cena a partir do script de modelação do projecto
$BLENDER -b --factory-startup -P projects/<projecto>/model_*.py -- --stage all --save

# 2. renderizar todos os panoramas (câmaras "360_*" na cena)
$BLENDER -b projects/<projecto>/scene.blend -P pipeline/render.py -- \
    --out projects/<projecto>/renders --samples 64 --res 4096

# 3. montar o tour (tour.json define cenas + hotspots)
python3 pipeline/build_tour.py projects/<projecto>

# 4. pré-visualizar
python3 -m http.server -d projects/<projecto>/dist

# 5. (opcional) clips de vídeo por reprojecção dos panoramas
$PY pipeline/pano_pan.py projects/<projecto>/renders/sala.png \
    --out clip.mp4 --yaw-start -25 --yaw-end 20 --dur 5
```

## Estrutura de um projecto

```
projects/<nome>/
├── model_*.py     # modelação programática da cena (paredes, materiais, mobília, câmaras)
├── scene.blend    # gerado pelo model_*.py
├── tour.json      # config do tour (cenas + hotspots)
├── renders/       # panoramas 360° (gerado)
└── dist/          # site final (gerado)
```

Convenções: câmaras `360_<divisão>` a 1,55 m; paredes interiores 0,12 m, exteriores 0,25 m; pé-direito 2,60 m. O `model_t2.py` incluído demonstra o processo completo — geometria derivada de um dicionário de rectângulos por divisão, aberturas por segmentação de paredes, materiais procedurais (sem texturas externas) e verificação automática de folgas das câmaras.

## Demo

Tour de demonstração de um T2 (78 m²) modelado a partir de uma planta pública: [pj-lima.github.io/tour-press](https://pj-lima.github.io/tour-press/)
