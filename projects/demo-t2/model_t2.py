"""Constrói scene.blend do T2 demo — headless.

Uso:
    source pipeline/env.sh
    $BLENDER -b --factory-startup -P projects/demo-t2/model_t2.py -- --stage geometry --save --qa

Origem = canto SW interior, metros; X→este, Y→norte (fachada da varanda a norte, y=7,59); Z para cima.
Os rects de ROOMS são faces INTERIORES das divisões.

AVISO: cada stage reconstrói a cena do zero; correr sempre --stage all (stages isolados não
carregam scene.blend).
"""

import argparse
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- constantes
#
# Todas as cotas vivem em geometry.py (python puro, sem bpy) para que o pipeline as possa
# ler sem Blender instalado — é de lá que saem o teste de hotspots do build e o SVG do
# minimapa. Aqui só se importa; não duplicar valores neste ficheiro.

ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

import pbr  # noqa: E402  (depende do sys.path acima)

pbr.library(os.path.join(ROOT, "assets", "library"))

from geometry import (  # noqa: E402  (depende do sys.path acima)
    CEIL, WALL_INT, WALL_EXT, SLAB, DOOR_W, DOOR_H, GLAZ_H, FRAME, GLASS_T, RAIL_H,
    ROOMS, INTERIOR_ROOMS, DOORS, ENTRANCE, GLAZING, GROUND_Z, GROUND_R, BOUNDS,
    CAM_SPOTS, CAM_Z, CAM_CLEAR, CAM_CLEAR_ROOM, CAM_CLEAR_XY, CAM_XY_MIN_TOP,
    CAM_ROOM,
    find_partitions, door_for,
)

_LOG_COUNT = {"walls": 0, "slabs": 0, "glass": 0}


# ---------------------------------------------------------------- utilitários

def log(msg):
    print("[model_t2] " + msg)


def clean_scene():
    """Remove tudo o que vem da cena por omissão."""
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)
    log("cena limpa")


def get_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def box(name, x0, x1, y0, y1, z0, z1, coll):
    """Cria uma caixa alinhada aos eixos, definida pelos seus limites em metros."""
    if x1 - x0 <= 1e-5 or y1 - y0 <= 1e-5 or z1 - z0 <= 1e-5:
        return None
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        (0, 3, 2, 1),  # baixo
        (4, 5, 6, 7),  # cima
        (0, 1, 5, 4),  # -Y
        (1, 2, 6, 5),  # +X
        (2, 3, 7, 6),  # +Y
        (3, 0, 4, 7),  # -X
    ]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def subtract_spans(span, cuts):
    """Subtrai intervalos `cuts` de `span`; devolve a lista de intervalos restantes."""
    result = [span]
    for c0, c1 in cuts:
        nxt = []
        for a, b in result:
            if c1 <= a + 1e-9 or c0 >= b - 1e-9:
                nxt.append((a, b))
                continue
            if a < c0 - 1e-9:
                nxt.append((a, c0))
            if c1 < b - 1e-9:
                nxt.append((c1, b))
        result = nxt
    return [(a, b) for a, b in result if b - a > 1e-3]


def wall_run(name, kind, f0, f1, t0, t1, openings, coll, z0=0.0, z1=CEIL):
    """Emite uma parede segmentada em caixas à volta dos vãos (sem booleanos).

    kind='x' → o plano da parede tem normal em X: f0..f1 é a espessura em X, t0..t1 o
               desenvolvimento em Y.
    kind='y' → normal em Y: f0..f1 é a espessura em Y, t0..t1 o desenvolvimento em X.
    openings → lista de (a0, a1, oz0, oz1) em coordenada tangente + altura.
    """
    def emit(suffix, a0, a1, b0, b1):
        if kind == "x":
            return box("%s_%s" % (name, suffix), f0, f1, a0, a1, b0, b1, coll)
        return box("%s_%s" % (name, suffix), a0, a1, f0, f1, b0, b1, coll)

    ops = []
    for a0, a1, oz0, oz1 in openings:
        a0, a1 = max(a0, t0), min(a1, t1)
        if a1 - a0 > 1e-3:
            ops.append((a0, a1, max(oz0, z0), min(oz1, z1)))
    ops.sort()

    n = 0
    # nembos (troços cheios entre vãos)
    for a0, a1 in subtract_spans((t0, t1), [(o[0], o[1]) for o in ops]):
        if emit("p%d" % n, a0, a1, z0, z1):
            n += 1
    # padieiras e peitoris
    for i, (a0, a1, oz0, oz1) in enumerate(ops):
        if emit("verga%d" % i, a0, a1, oz1, z1):
            n += 1
        if emit("peitoril%d" % i, a0, a1, z0, oz0):
            n += 1
    _LOG_COUNT["walls"] += n
    log("parede %-28s %s=[%.2f,%.2f] t=[%.2f,%.2f] vãos=%d caixas=%d"
        % (name, kind, f0, f1, t0, t1, len(ops), n))
    return n


# ---------------------------------------------------------------- topologia

# `find_partitions()` e `door_for()` vivem em geometry.py — o teste de hotspots do build e o
# minimapa usam exactamente as mesmas paredes e vãos que a cena construída aqui.


# ---------------------------------------------------------------- construção

def build_floors_ceilings():
    floors = get_collection("Floors")
    ceilings = get_collection("Ceilings")
    for name in INTERIOR_ROOMS:
        x0, x1, y0, y1 = ROOMS[name]
        m = WALL_EXT + 0.05          # transborda para debaixo das paredes
        box("laje_%s" % name, x0 - m, x1 + m, y0 - m, y1 + m, -SLAB, 0.0, floors)
        box("tecto_%s" % name, x0 - m, x1 + m, y0 - m, y1 + m, CEIL, CEIL + SLAB, ceilings)
        _LOG_COUNT["slabs"] += 2
        log("divisão %-10s rect=(%.2f,%.2f)-(%.2f,%.2f)  %.2f×%.2f = %.2f m²  laje+tecto"
            % (name, x0, y0, x1, y1, x1 - x0, y1 - y0, (x1 - x0) * (y1 - y0)))


def build_walls(parts):
    walls = get_collection("Walls")

    # --- divisórias interiores (uma caixa por par, a preencher a folga entre rects)
    for p in parts:
        d = door_for(p["lo"], p["hi"])
        openings = [d] if d else []
        wall_run("int_%s_%s" % (p["lo"], p["hi"]), p["kind"],
                 p["f0"], p["f1"], p["t0"], p["t1"], openings, walls)

    # --- envelope exterior: o que sobra de cada face de cada divisão
    glaz_by_room = {}
    for room, g0, g1 in GLAZING:
        glaz_by_room.setdefault(room, []).append((g0, g1, 0.0, GLAZ_H))

    for name in INTERIOR_ROOMS:
        x0, x1, y0, y1 = ROOMS[name]
        sides = {
            # lado: (kind, f0, f1, t0, t1, filtro de cortes)
            "W": ("x", x0 - WALL_EXT, x0, y0, y1,
                  [(p["t0"], p["t1"]) for p in parts if p["kind"] == "x" and p["hi"] == name]),
            "E": ("x", x1, x1 + WALL_EXT, y0, y1,
                  [(p["t0"], p["t1"]) for p in parts if p["kind"] == "x" and p["lo"] == name]),
            "S": ("y", y0 - WALL_EXT, y0, x0, x1,
                  [(p["t0"], p["t1"]) for p in parts if p["kind"] == "y" and p["hi"] == name]),
            "N": ("y", y1, y1 + WALL_EXT, x0, x1,
                  [(p["t0"], p["t1"]) for p in parts if p["kind"] == "y" and p["lo"] == name]),
        }
        for side, (kind, f0, f1, ta, tb, cuts) in sides.items():
            for s0, s1 in subtract_spans((ta, tb), cuts):
                # prolongar nos cantos do rect para as paredes exteriores se encontrarem
                e0 = s0 - WALL_EXT if abs(s0 - ta) < 1e-6 else s0
                e1 = s1 + WALL_EXT if abs(s1 - tb) < 1e-6 else s1
                openings = []
                if side == "N":
                    openings = [g for g in glaz_by_room.get(name, [])]
                if side == "S" and name == ENTRANCE[0]:
                    openings = [(ENTRANCE[1], ENTRANCE[2], 0.0, ENTRANCE[3])]
                wall_run("ext_%s_%s" % (name, side), kind, f0, f1, e0, e1, openings, walls)


def build_glazing():
    """Caixilhos finos + panos de vidro nos vãos da fachada norte (y=7.59)."""
    openings = get_collection("Openings")
    yf0, yf1 = 7.59, 7.59 + WALL_EXT
    ygl = (yf0 + yf1) / 2.0
    for room, g0, g1 in GLAZING:
        tag = "vao_%s" % room
        box(tag + "_jamba_o", g0, g0 + FRAME, yf0, yf1, 0.0, GLAZ_H, openings)
        box(tag + "_jamba_e", g1 - FRAME, g1, yf0, yf1, 0.0, GLAZ_H, openings)
        box(tag + "_travessa", g0, g1, yf0, yf1, GLAZ_H - FRAME, GLAZ_H, openings)
        box(tag + "_soleira", g0, g1, yf0, yf1, 0.0, 0.04, openings)
        mid = (g0 + g1) / 2.0
        box(tag + "_montante", mid - 0.03, mid + 0.03, yf0, yf1, 0.04, GLAZ_H - FRAME, openings)
        box(tag + "_vidro_o", g0 + FRAME, mid, ygl - GLASS_T / 2, ygl + GLASS_T / 2,
            0.04, GLAZ_H - FRAME, openings)
        box(tag + "_vidro_e", mid, g1 - FRAME, ygl - GLASS_T / 2, ygl + GLASS_T / 2,
            0.04, GLAZ_H - FRAME, openings)
        _LOG_COUNT["glass"] += 2
        log("envidraçado %-8s x=[%.2f,%.2f] h=%.2f (correr, 2 folhas + caixilho)"
            % (room, g0, g1, GLAZ_H))


def build_varanda():
    """Laje ao nível do piso, guarda de vidro a norte, muretes laterais, tecto (recuada)."""
    floors = get_collection("Floors")
    walls = get_collection("Walls")
    ceilings = get_collection("Ceilings")
    openings = get_collection("Openings")
    vx0, vx1, vy0, vy1 = ROOMS["varanda"]

    box("laje_varanda", vx0 - WALL_EXT, vx1 + WALL_EXT, 7.59, vy1, -SLAB, 0.0, floors)
    box("tecto_varanda", vx0 - WALL_EXT, vx1 + WALL_EXT, vy0, vy1, CEIL, CEIL + SLAB, ceilings)
    box("varanda_murete_o", vx0 - WALL_EXT, vx0, vy0, vy1, 0.0, CEIL, walls)
    box("varanda_murete_e", vx1, vx1 + WALL_EXT, vy0, vy1, 0.0, CEIL, walls)
    # guarda de vidro + corrimão
    box("varanda_guarda_vidro", vx0, vx1, vy1 - 0.02, vy1, 0.05, RAIL_H, openings)
    box("varanda_guarda_base", vx0, vx1, vy1 - 0.05, vy1, 0.0, 0.05, walls)
    box("varanda_corrimao", vx0, vx1, vy1 - 0.06, vy1 + 0.01, RAIL_H, RAIL_H + 0.05, walls)
    _LOG_COUNT["slabs"] += 2
    _LOG_COUNT["walls"] += 4
    log("varanda   rect=(%.2f,%.2f)-(%.2f,%.2f)  %.2f×%.2f = %.2f m²  laje+guarda+muretes+tecto"
        % (vx0, vy0, vx1, vy1, vx1 - vx0, vy1 - vy0, (vx1 - vx0) * (vy1 - vy0)))


def build_exterior():
    """Plano de água até ao horizonte + faixa de costa distante (linha de horizonte).

    A câmara da varanda está a z=1.55 e vê o hemisfério inferior: sem geometria de
    terreno, o Nishita devolve preto abaixo do horizonte e o panorama fica com a metade
    de baixo vazia.
    """
    ext = get_collection("Exterior")
    box("terreno_mar", -GROUND_R, GROUND_R, -GROUND_R, GROUND_R,
        GROUND_Z - 0.05, GROUND_Z, ext)
    # costa ao largo, a norte (para lá da varanda): dá uma linha de horizonte legível
    box("terreno_costa", -GROUND_R, GROUND_R, 180.0, GROUND_R,
        GROUND_Z, GROUND_Z + 2.60, ext)
    log("exterior: plano de água %.0f×%.0f m a z=%.2f + costa distante"
        % (2 * GROUND_R, 2 * GROUND_R, GROUND_Z))


def build_geometry():
    clean_scene()
    for n in ("Walls", "Floors", "Ceilings", "Openings", "Exterior"):
        get_collection(n)
    parts = find_partitions()
    log("divisórias detectadas: %d" % len(parts))
    build_floors_ceilings()
    build_walls(parts)
    build_glazing()
    build_varanda()
    build_exterior()
    log("total: %d caixas de parede, %d lajes, %d panos de vidro, %d objectos"
        % (_LOG_COUNT["walls"], _LOG_COUNT["slabs"], _LOG_COUNT["glass"],
           len(bpy.data.objects)))


# ---------------------------------------------------------------- materiais

# Parâmetros de luz/exposição (afinados a olho nas pré-visualizações de QA).
SUN_W = 3.0            # W/m² (irradiância do sol, conforme brief)
SUN_ELEV = 18.0        # graus acima do horizonte — fim de tarde
SUN_AZ = 135.0         # graus a partir de +X, anti-horário → 135° = noroeste
# Céu de tarde limpa, não de pôr-do-sol: o `belfast_sunset` punha uma dominante laranja
# em tudo (paredes castanhas, mar branco) e o mar é o argumento de venda desta casa.
SKY_HDRI = "kloofendal_48d_partly_cloudy_puresky"   # assets/library/hdri (CC0 Poly Haven)
SKY_ROT = 210.0        # graus: roda o HDRI para o sol cair a noroeste, sobre o mar
SKY_STRENGTH = 1.0     # HDRI já vem calibrado — ao contrário do Nishita, não leva 0.28
EXPOSURE = 0.15        # exposição de filme (stops); desceu de +1.35 quando as paredes
                       # passaram de albedo 0.26 para 0.78 (a casa reflecte 3× mais)
# ~4200 K: o HDRI de fim de tarde já traz o quente todo. Com 3500 K a soma das duas
# fontes empurrava tudo para sépia e as paredes liam-se castanhas.
WARM_4200K = (1.0, 0.925, 0.845)
FILL_W_PER_M2 = 1.60   # area lights de tecto: divisões com envidraçado (W/m²)
FILL_W_DARK = 3.20     # idem, divisões interiores sem luz natural (W/m²)

FURN = []              # objectos de mobiliário (para o teste de folgas)


def _pbr(name, base, rough=0.6, metal=0.0, ior=1.45, transmission=0.0,
         sheen=0.0, coat=0.0, emis=None, emis_w=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]

    def put(key, val):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = val

    put("Base Color", (base[0], base[1], base[2], 1.0))
    put("Roughness", rough)
    put("Metallic", metal)
    put("IOR", ior)
    if transmission:
        put("Transmission Weight", transmission)
    if sheen:
        put("Sheen Weight", sheen)
    if coat:
        put("Coat Weight", coat)
    if emis:
        put("Emission Color", (emis[0], emis[1], emis[2], 1.0))
        put("Emission Strength", emis_w)
    m["_bsdf"] = True
    return m


def _bsdf(m):
    return m.node_tree.nodes["Principled BSDF"]


def _noise_bump(m, scale=90.0, strength=0.06, detail=3.0, rough_mix=None):
    """Relevo subtil procedural (Noise → Bump) a partir de coordenadas de objecto."""
    nt = m.node_tree
    bsdf = _bsdf(m)
    co = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    nt.links.new(co.outputs["Object"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if rough_mix is not None:
        rr = nt.nodes.new("ShaderNodeMapRange")
        rr.inputs["To Min"].default_value = rough_mix[0]
        rr.inputs["To Max"].default_value = rough_mix[1]
        nt.links.new(tex.outputs["Fac"], rr.inputs["Value"])
        nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    return tex


def _plane_coords(nt, axis):
    """Devolve o socket de vector 2D adequado à orientação da superfície.
    axis='z' → usa (x,y); 'x' → (y,z) (paredes de normal X); 'y' → (x,z)."""
    co = nt.nodes.new("ShaderNodeTexCoord")
    if axis == "z":
        return co.outputs["Object"]
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    com = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(co.outputs["Object"], sep.inputs["Vector"])
    if axis == "x":
        nt.links.new(sep.outputs["Y"], com.inputs["X"])
    else:
        nt.links.new(sep.outputs["X"], com.inputs["X"])
    nt.links.new(sep.outputs["Z"], com.inputs["Y"])
    return com.outputs["Vector"]


def _brick_mat(name, axis, w, h, c1, c2, mortar, mortar_size, rough,
               bump=0.25, jitter=0.0):
    """Material de padrão rectangular (soalho ou azulejo) via Brick Texture."""
    m = _pbr(name, c1, rough=rough)
    nt = m.node_tree
    bsdf = _bsdf(m)
    vec = _plane_coords(nt, axis)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0 / w, 1.0 / h, 1.0)
    nt.links.new(vec, mp.inputs["Vector"])
    br = nt.nodes.new("ShaderNodeTexBrick")
    br.offset = 0.5
    br.squash = 1.0
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Brick Width"].default_value = 1.0
    br.inputs["Row Height"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = mortar_size
    br.inputs["Mortar Smooth"].default_value = 0.1
    br.inputs["Bias"].default_value = 0.0
    br.inputs["Color1"].default_value = (c1[0], c1[1], c1[2], 1.0)
    br.inputs["Color2"].default_value = (c2[0], c2[1], c2[2], 1.0)
    br.inputs["Mortar"].default_value = (mortar[0], mortar[1], mortar[2], 1.0)
    nt.links.new(mp.outputs["Vector"], br.inputs["Vector"])

    # variação de tom por peça/tábua
    ns = nt.nodes.new("ShaderNodeTexNoise")
    ns.inputs["Scale"].default_value = 1.6
    ns.inputs["Detail"].default_value = 2.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = jitter
    nt.links.new(mp.outputs["Vector"], ns.inputs["Vector"])
    nt.links.new(br.outputs["Color"], mix.inputs[6])   # A (RGBA)
    nt.links.new(ns.outputs["Color"], mix.inputs[7])   # B (RGBA)
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])

    # juntas em baixo-relevo
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = bump
    nt.links.new(br.outputs["Fac"], inv.inputs[1])
    nt.links.new(inv.outputs["Value"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def _art_mat(name, kind, c1, c2, c3, scale=6.0, distortion=0.0, rough=0.80):
    """Tela pintada: Noise ou Wave → ColorRamp de 3 tons → Base Color.

    Sem isto os quadros são chapas de cor lisa e lêem-se como telas em branco.
    Mesmo padrão de nós do `_brick_mat` (Texture Coordinate → Object → Mapping → textura).
    """
    m = _pbr(name, c1, rough=rough)
    nt = m.node_tree
    bsdf = _bsdf(m)
    co = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(23.0))
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    if kind == "wave":
        tex = nt.nodes.new("ShaderNodeTexWave")
        tex.bands_direction = "Z"
        tex.inputs["Scale"].default_value = scale
        tex.inputs["Distortion"].default_value = distortion
        tex.inputs["Detail"].default_value = 3.0
        out = tex.outputs["Fac"]
    else:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = scale
        tex.inputs["Detail"].default_value = 5.0
        tex.inputs["Roughness"].default_value = 0.62
        if "Distortion" in tex.inputs:
            tex.inputs["Distortion"].default_value = distortion
        out = tex.outputs["Fac"]
    nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.interpolation = "B_SPLINE"
    cr.elements[0].position = 0.30
    cr.elements[0].color = (c1[0], c1[1], c1[2], 1.0)
    cr.elements[1].position = 0.72
    cr.elements[1].color = (c3[0], c3[1], c3[2], 1.0)
    mid = cr.elements.new(0.52)
    mid.color = (c2[0], c2[1], c2[2], 1.0)
    nt.links.new(out, ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def build_materials():
    M = {}
    # soalho carvalho claro (tábuas 1,30 × 0,19)
    # Superfícies grandes levam textura fotográfica CC0 (assets/library) em vez de
    # procedural: é a diferença entre "render de arquitecto" e maquete. As pequenas
    # (metais, louça, vidro) ficam procedurais — aí a textura não acrescenta nada.
    M["floor"] = pbr.tex_material("chao_carvalho", "wood_floor", size=2.6,
                                  rough_mult=0.95, normal_strength=0.7, coat=0.12)
    # paredes / tectos
    # cor lisa + relevo do reboco: o difuso da amostra é castanho (albedo linear 0.26) e
    # punha a casa toda sépia — tinta de parede é ~0.75 de reflectância, quase neutra
    M["wall"] = pbr.tex_material("parede_offwhite", "beige_wall_001", size=3.2,
                                 base_color=(0.780, 0.772, 0.752), normal_strength=0.35)
    _noise_bump(M["wall"], scale=180.0, strength=0.03)
    M["ceil"] = _pbr("tecto_branco", (0.860, 0.858, 0.852), rough=0.92)
    M["wall_accent"] = _pbr("parede_taupe", (0.420, 0.395, 0.360), rough=0.90)
    # azulejo (2 orientações + chão)
    tile_c1 = (0.745, 0.750, 0.752)
    tile_c2 = (0.700, 0.706, 0.712)
    tile_j = (0.575, 0.582, 0.590)
    # mármore cinza nas I.S.: um único material serve as duas orientações, porque a
    # projecção box já resolve paredes e chão sem UVs
    # As I.S. ficam procedurais de propósito: o catálogo CC0 de pedra/azulejo é todo
    # exterior e rústico (o "grey_cartago" é lousa ferruginosa) e lia-se como ferrugem
    # numa casa de banho. Porcelânico de grande formato não tem variação fotográfica
    # nenhuma — só junta e brilho, que o procedural dá melhor e sem dominante.
    M["tile_x"] = _brick_mat("azulejo_x", "x", 0.60, 0.60, tile_c1, tile_c2,
                             tile_j, 0.010, 0.14, bump=0.22, jitter=0.03)
    M["tile_y"] = _brick_mat("azulejo_y", "y", 0.60, 0.60, tile_c1, tile_c2,
                             tile_j, 0.010, 0.14, bump=0.22, jitter=0.03)
    M["tile_floor"] = _brick_mat("azulejo_chao", "z", 0.60, 0.60,
                                 (0.470, 0.470, 0.468), (0.442, 0.444, 0.446),
                                 (0.360, 0.362, 0.364), 0.008, 0.20,
                                 bump=0.18, jitter=0.04)
    M["deck"] = _brick_mat("pavimento_varanda", "z", 0.60, 0.30,
                           (0.400, 0.388, 0.368), (0.372, 0.362, 0.344),
                           (0.300, 0.294, 0.282), 0.010, 0.45,
                           bump=0.25, jitter=0.08)
    # cozinha
    M["stone"] = pbr.tex_material("bancada_marmore", "marble_01", size=1.6,
                                  rough_mult=0.35, normal_strength=0.25, coat=0.45)
    _noise_bump(M["stone"], scale=340.0, strength=0.04)
    M["lacquer"] = _pbr("lacado_claro", (0.780, 0.775, 0.760), rough=0.26, coat=0.25)
    M["steel"] = _pbr("inox", (0.640, 0.645, 0.650), rough=0.28, metal=1.0)
    M["chrome"] = _pbr("cromado", (0.780, 0.785, 0.790), rough=0.10, metal=1.0)
    # vãos
    M["glass"] = _pbr("vidro", (0.960, 0.975, 0.970), rough=0.02, transmission=1.0,
                      ior=1.45)
    M["frame"] = _pbr("caixilho_antracite", (0.055, 0.057, 0.060), rough=0.42,
                      metal=0.85)
    # tecidos e madeiras
    # o mesmo linho serve sofá, cama e tapete — muda o tinte e a escala do ladrilho
    # Têxteis: cor lisa + trama (normal/rugosidade) da amostra. O difuso do `rough_linen`
    # é claramente azul (linear 0.28/0.41/0.62) e nenhum tinte o neutraliza — multiplicar
    # preserva a razão entre canais, era isso que deixava a roupa de cama azul-clara.
    # A 0.55 m de ladrilho a trama do linho não se lê a 2 m de distância e o sofá saía
    # como um bloco cinzento liso. Ladrilho mais curto e normal mais forte devolvem o
    # tecido; o tom desce de cinza-médio para azul-ardósia, que não compete com a madeira.
    M["fabric"] = pbr.tex_material("tecido_sofa", "rough_linen", size=0.30,
                                   base_color=(0.115, 0.126, 0.148),
                                   normal_strength=2.0, sheen=0.35)
    _noise_bump(M["fabric"], scale=420.0, strength=0.14)
    # Almofadas: cor lisa lia-se a plástico. Mesma trama do linho, ladrilho curto porque a
    # peça tem 45 cm — a 2.0 m o ladrilho dava uma face inteira sem variação.
    M["cushion"] = pbr.tex_material("almofada_terracota", "rough_linen", size=0.20,
                                    base_color=(0.330, 0.150, 0.098),
                                    normal_strength=1.8, sheen=0.5)
    M["cushion2"] = pbr.tex_material("almofada_areia", "rough_linen", size=0.20,
                                     base_color=(0.475, 0.408, 0.318),
                                     normal_strength=1.8, sheen=0.5)
    M["linen"] = pbr.tex_material("linho_cama", "rough_linen", size=0.42,
                                  base_color=(0.720, 0.706, 0.674),
                                  normal_strength=1.4, sheen=0.4)
    _noise_bump(M["linen"], scale=380.0, strength=0.12)
    M["sheer"] = pbr.tex_material("cortinado_linho", "rough_linen", size=0.30,
                                  base_color=(0.700, 0.690, 0.665),
                                  normal_strength=1.0, sheen=0.7)
    M["throw"] = _pbr("manta", (0.330, 0.360, 0.375), rough=0.92, sheen=0.4)
    M["rug"] = pbr.tex_material("tapete_la", "rough_linen", size=0.30,
                                base_color=(0.300, 0.262, 0.208),
                                normal_strength=1.8, sheen=0.5)
    _noise_bump(M["rug"], scale=260.0, strength=0.30)
    M["walnut"] = _pbr("nogueira", (0.185, 0.108, 0.062), rough=0.36, coat=0.15)
    _noise_bump(M["walnut"], scale=45.0, strength=0.025)
    M["oak"] = _pbr("carvalho_movel", (0.355, 0.268, 0.182), rough=0.40)
    _noise_bump(M["oak"], scale=45.0, strength=0.025)
    # louça, espelho, ecrã
    M["ceramic"] = _pbr("louca_branca", (0.870, 0.870, 0.865), rough=0.08, coat=0.5)
    M["mirror"] = _pbr("espelho", (0.930, 0.935, 0.940), rough=0.02, metal=1.0)
    M["screen"] = _pbr("ecra", (0.018, 0.018, 0.020), rough=0.24)
    M["black"] = _pbr("preto_mate", (0.035, 0.035, 0.036), rough=0.55)
    # decoração
    M["plant"] = _pbr("folhagem", (0.105, 0.220, 0.098), rough=0.62)
    M["plant2"] = _pbr("folhagem_clara", (0.150, 0.290, 0.120), rough=0.62)
    M["pot"] = _pbr("vaso", (0.560, 0.400, 0.320), rough=0.55)
    # telas com padrão procedural (não são chapas de cor lisa)
    M["art1"] = _art_mat("quadro_ocre", "noise",
                         (0.640, 0.470, 0.205), (0.780, 0.640, 0.400),
                         (0.300, 0.205, 0.120), scale=5.5, distortion=1.4)
    M["art2"] = _art_mat("quadro_azul", "wave",
                         (0.120, 0.180, 0.280), (0.230, 0.330, 0.430),
                         (0.640, 0.660, 0.660), scale=4.5, distortion=8.0)
    M["art3"] = _art_mat("quadro_creme", "noise",
                         (0.760, 0.730, 0.665), (0.560, 0.520, 0.455),
                         (0.330, 0.310, 0.280), scale=3.2, distortion=2.2)
    # exterior
    M["sea"] = _pbr("mar", (0.045, 0.075, 0.100), rough=0.16, coat=0.15)
    _noise_bump(M["sea"], scale=0.9, strength=0.22, detail=6.0)
    M["terrain"] = _pbr("costa_distante", (0.088, 0.098, 0.082), rough=0.85)
    _noise_bump(M["terrain"], scale=0.35, strength=0.20)
    M["lamp"] = _pbr("abajur", (0.900, 0.860, 0.780), rough=0.75,
                     emis=(1.0, 0.78, 0.52), emis_w=2.2)
    M["bulb"] = _pbr("luz_pendente", (0.9, 0.9, 0.9), rough=0.5,
                     emis=(1.0, 0.76, 0.50), emis_w=6.0)
    log("materiais criados: %d" % len(M))
    return M


def _set(ob, mat):
    ob.data.materials.clear()
    ob.data.materials.append(mat)


def assign_shell_materials(M):
    """Materiais na casca (paredes, lajes, tectos, vãos) + desempate de faces coplanares.

    As lajes/tectos de divisões vizinhas sobrepõem-se (transbordam 0,30 m para debaixo
    das paredes) — sem um pequeno desvio em Z haveria z-fighting visível ao longo dos
    rodapés. Deslocamos cada laje 0,4 mm por índice; o degrau é invisível.
    """
    n = 0
    for i, name in enumerate(INTERIOR_ROOMS):
        for prefix, dz in (("laje_", i * 0.0004), ("tecto_", -i * 0.0004)):
            ob = bpy.data.objects.get(prefix + name)
            if ob:
                ob.location.z += dz

    # Paredes exteriores de divisões vizinhas que dão para a mesma fachada (ex.: quarto
    # e sala, ambas com y1=7.59) partilham a mesma espessura f0..f1 na direcção normal
    # da parede — faces exactamente coincidentes, riscas pretas em Cycles (o mesmo
    # problema das lajes, aqui na normal da parede em vez de Z). Mesmo truque: desvio
    # de 0,4 mm por índice de divisão, ao longo da normal (Y para paredes N/S, X para
    # E/W); as aberturas (vãos) mantêm-se intactas porque toda a caixa da parede — nembo,
    # verga e peitoril — se desloca em bloco.
    for i, name in enumerate(INTERIOR_ROOMS):
        dz = i * 0.0004
        prefix = "ext_%s_" % name
        for ob in bpy.data.objects:
            if ob.name.startswith(prefix):
                side = ob.name.split("_")[-2]
                if side in ("N", "S"):
                    ob.location.y += dz
                elif side in ("E", "W"):
                    ob.location.x += dz

    ob = bpy.data.objects.get("laje_varanda")
    if ob:
        ob.location.z += 0.0060   # ganha à borda das lajes interiores
        _set(ob, M["deck"])
        n += 1
    ob = bpy.data.objects.get("tecto_varanda")
    if ob:
        ob.location.z -= 0.0060
        _set(ob, M["ceil"])
        n += 1

    for coll_name in ("Floors", "Ceilings", "Walls", "Openings", "Exterior"):
        coll = bpy.data.collections.get(coll_name)
        if not coll:
            continue
        for ob in coll.objects:
            nm = ob.name
            if ob.data.materials:
                continue
            if nm == "terreno_mar":
                mat = M["sea"]
            elif nm == "terreno_costa":
                mat = M["terrain"]
            elif nm.startswith("laje_"):
                mat = M["floor"]
            elif nm.startswith("tecto_"):
                mat = M["ceil"]
            elif "_vidro" in nm:
                mat = M["glass"]
                ob.visible_shadow = False      # o sol atravessa sem cáusticas
            elif nm.startswith("vao_") or nm == "varanda_corrimao" \
                    or nm == "varanda_guarda_base":
                mat = M["frame"]
            else:
                mat = M["wall"]
            _set(ob, mat)
            n += 1
    log("materiais aplicados à casca: %d objectos" % n)


# ---------------------------------------------------------------- construtores

class Piece:
    """Acumula primitivas num único mesh, com um slot de material por material usado."""

    def __init__(self, name, coll):
        self.name = name
        self.coll = coll
        self.bm = bmesh.new()
        self.mats = []

    def _slot(self, mat):
        if mat in self.mats:
            return self.mats.index(mat)
        self.mats.append(mat)
        return len(self.mats) - 1

    def _tag(self, verts, mat, smooth_sides=False):
        idx = self._slot(mat)
        faces = set()
        for v in verts:
            faces.update(v.link_faces)
        for f in faces:
            f.material_index = idx
            if smooth_sides and abs(f.normal.z) < 0.85:
                f.smooth = True

    def box(self, x0, x1, y0, y1, z0, z1, mat):
        res = bmesh.ops.create_cube(self.bm, size=1.0)
        vs = res["verts"]
        bmesh.ops.scale(self.bm, vec=Vector((x1 - x0, y1 - y0, z1 - z0)), verts=vs)
        bmesh.ops.translate(self.bm, vec=Vector(((x0 + x1) / 2.0, (y0 + y1) / 2.0,
                                                 (z0 + z1) / 2.0)), verts=vs)
        self._tag(vs, mat)
        return vs

    def cyl(self, cx, cy, z0, z1, r, mat, r2=None, seg=24):
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False,
                                    segments=seg, radius1=r,
                                    radius2=(r if r2 is None else r2),
                                    depth=(z1 - z0))
        vs = res["verts"]
        bmesh.ops.translate(self.bm, vec=Vector((cx, cy, (z0 + z1) / 2.0)), verts=vs)
        self._tag(vs, mat, smooth_sides=True)
        return vs

    def sphere(self, cx, cy, cz, r, mat, sz=1.0, seg=20):
        try:
            res = bmesh.ops.create_uvsphere(self.bm, u_segments=seg,
                                            v_segments=max(6, seg // 2), radius=r)
        except TypeError:
            res = bmesh.ops.create_uvsphere(self.bm, u_segments=seg,
                                            v_segments=max(6, seg // 2), diameter=r)
        vs = res["verts"]
        if sz != 1.0:
            bmesh.ops.scale(self.bm, vec=Vector((1.0, 1.0, sz)), verts=vs)
        bmesh.ops.translate(self.bm, vec=Vector((cx, cy, cz)), verts=vs)
        idx = self._slot(mat)
        faces = set()
        for v in vs:
            faces.update(v.link_faces)
        for f in faces:
            f.material_index = idx
            f.smooth = True
        return vs

    def drape(self, x0, x1, y, z0, z1, mat, amp=0.05, waves=5, cols=40):
        """Pano vertical ondulado no plano XZ — cortinado.

        A onda em seno é o que separa um cortinado de um rectângulo de pano: dá as pregas
        e, com elas, o gradiente de luz vertical que o olho lê como tecido pendurado.
        """
        cols_v = []
        for i in range(cols + 1):
            t = i / float(cols)
            x = x0 + (x1 - x0) * t
            yy = y + amp * math.sin(t * waves * 2.0 * math.pi)
            cols_v.append((self.bm.verts.new((x, yy, z0)),
                           self.bm.verts.new((x, yy, z1))))
        idx = self._slot(mat)
        for i in range(cols):
            a, b = cols_v[i]
            c, d = cols_v[i + 1]
            f = self.bm.faces.new((a, c, d, b))
            f.smooth = True
            f.material_index = idx
        self.bm.normal_update()
        return [v for pair in cols_v for v in pair]

    def finish(self):
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(self.name, me)
        self.coll.objects.link(ob)
        FURN.append(ob)
        return ob


class Local:
    """Coordenadas locais de uma peça: u = largura, v = profundidade a partir das costas.

    face indica para onde a peça 'olha': 'N' (+Y), 'S' (-Y), 'E' (+X), 'W' (-X).
    (ox, oy) é o ponto u=0, v=0 (canto de trás, à esquerda de quem olha para a peça).
    """

    _M = {"N": (1, 0, 0, 1), "S": (-1, 0, 0, -1),
          "E": (0, 1, -1, 0), "W": (0, -1, 1, 0)}

    def __init__(self, piece, face, ox, oy):
        self.p = piece
        self.ox, self.oy = ox, oy
        self.m = self._M[face]

    def xy(self, u, v):
        a, b, c, d = self.m
        return (self.ox + a * u + b * v, self.oy + c * u + d * v)

    def b(self, u0, u1, v0, v1, z0, z1, mat):
        (x0, y0), (x1, y1) = self.xy(u0, v0), self.xy(u1, v1)
        return self.p.box(min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1),
                          z0, z1, mat)

    def c(self, u, v, z0, z1, r, mat, **kw):
        x, y = self.xy(u, v)
        return self.p.cyl(x, y, z0, z1, r, mat, **kw)

    def s(self, u, v, z, r, mat, **kw):
        x, y = self.xy(u, v)
        return self.p.sphere(x, y, z, r, mat, **kw)


def furn_coll():
    return get_collection("Furniture")


# ---------------------------------------------------------------- peças

def sofa(M, face, ox, oy, w=2.10, d=0.92, name="sofa"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    fab, wd = M["fabric"], M["walnut"]
    L.b(0, w, 0, d, 0.12, 0.40, fab)                 # base
    L.b(0, w, 0, 0.20, 0.40, 0.78, fab)              # encosto
    L.b(0, 0.19, 0.20, d, 0.40, 0.60, fab)           # braço esq
    L.b(w - 0.19, w, 0.20, d, 0.40, 0.60, fab)       # braço dir
    seat = (w - 0.38) / 3.0
    for i in range(3):
        u0 = 0.19 + i * seat + 0.015
        L.b(u0, u0 + seat - 0.03, 0.22, d - 0.05, 0.40, 0.50, fab)
        L.b(u0 + 0.04, u0 + seat - 0.07, 0.20, 0.30, 0.50, 0.74, fab)
    # as almofadas do sofá vêm da biblioteca CC0 (ver PROPS): as caixas que aqui estavam
    # ficavam dentro do modelo apendado, geometria a atravessar geometria
    for u, v in ((0.06, 0.08), (w - 0.12, 0.08), (0.06, d - 0.14), (w - 0.12, d - 0.14)):
        L.b(u, u + 0.06, v, v + 0.06, 0.0, 0.12, wd)
    return P.finish()


def coffee_table(M, cx, cy, w, d, h=0.38, top=None, legs=None, name="mesa_centro"):
    P = Piece(name, furn_coll())
    top = top or M["walnut"]
    legs = legs or M["black"]
    P.box(cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2, h - 0.04, h, top)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = cx + sx * (w / 2 - 0.08)
            y = cy + sy * (d / 2 - 0.08)
            P.box(x - 0.025, x + 0.025, y - 0.025, y + 0.025, 0.0, h - 0.04, legs)
    return P.finish()


def dining_table(M, cx, cy, w, d, h=0.75, name="mesa_jantar"):
    P = Piece(name, furn_coll())
    P.box(cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2, h - 0.045, h, M["oak"])
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = cx + sx * (w / 2 - 0.10)
            y = cy + sy * (d / 2 - 0.09)
            P.box(x - 0.035, x + 0.035, y - 0.035, y + 0.035, 0.0, h - 0.045,
                  M["oak"])
    # o centro de mesa é a taça de madeira da biblioteca (ver PROPS): o vaso com esfera
    # verde que aqui estava era exactamente o "isto parece maquete"
    return P.finish()


def chair(M, face, cx, cy, w=0.46, d=0.48, name="cadeira", seat=None, frame=None):
    """cx, cy = centro da cadeira (planta)."""
    P = Piece(name, furn_coll())
    L = Local(P, face, *(0, 0))
    L.ox, L.oy = cx, cy
    a, b, c, dd = L.m
    # recolocar a origem no canto de trás/esquerda
    L.ox = cx - (a * w + b * d) / 2.0
    L.oy = cy - (c * w + dd * d) / 2.0
    seat = seat or M["oak"]
    frame = frame or M["black"]
    L.b(0, w, 0, d, 0.42, 0.47, seat)                 # assento
    L.b(0.04, w - 0.04, 0.02, 0.07, 0.47, 0.92, seat)  # costas
    for u, v in ((0.03, 0.03), (w - 0.07, 0.03), (0.03, d - 0.07), (w - 0.07, d - 0.07)):
        L.b(u, u + 0.04, v, v + 0.04, 0.0, 0.42, frame)
    return P.finish()


def rug(M, x0, x1, y0, y1, mat=None, name="tapete"):
    P = Piece(name, furn_coll())
    P.box(x0, x1, y0, y1, 0.002, 0.016, mat or M["rug"])
    return P.finish()


def tv_unit(M, face, ox, oy, w=1.30, d=0.42, h=0.45, name="movel_tv"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, d, 0.10, h, M["walnut"])
    L.b(0.02, w - 0.02, d, d + 0.014, 0.16, h - 0.06, M["black"])   # frentes
    for u in (0.05, w - 0.11):
        L.b(u, u + 0.06, 0.06, d - 0.06, 0.0, 0.10, M["black"])
    return P.finish()


def tv_panel(M, face, ox, oy, w=1.15, h=0.66, z0=0.95, name="tv"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0.0, 0.035, z0, z0 + h, M["black"])
    L.b(0.015, w - 0.015, 0.035, 0.045, z0 + 0.015, z0 + h - 0.015, M["screen"])
    return P.finish()


def wall_art(M, face, ox, oy, w, h, z0, mat, name="quadro"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0.0, 0.035, z0, z0 + h, M["walnut"])
    L.b(0.035, w - 0.035, 0.035, 0.042, z0 + 0.035, z0 + h - 0.035, mat)
    return P.finish()


def plant(M, cx, cy, h=1.30, r=0.30, name="planta"):
    P = Piece(name, furn_coll())
    pr = min(0.24, r * 0.8)
    P.cyl(cx, cy, 0.0, 0.36, pr, M["pot"], r2=pr * 0.85)
    P.cyl(cx, cy, 0.32, h * 0.50, 0.028, M["walnut"])
    P.sphere(cx, cy, h * 0.70, r * 0.90, M["plant"], sz=0.62)
    P.sphere(cx - r * 0.62, cy + r * 0.34, h * 0.56, r * 0.60, M["plant2"], sz=0.7)
    P.sphere(cx + r * 0.58, cy - r * 0.40, h * 0.60, r * 0.55, M["plant"], sz=0.7)
    P.sphere(cx + r * 0.30, cy + r * 0.50, h * 0.80, r * 0.48, M["plant2"], sz=0.7)
    return P.finish()


def pendant(M, cx, cy, z=2.00, r=0.17, name="pendente"):
    P = Piece(name, furn_coll())
    P.cyl(cx, cy, z + 0.02, CEIL, 0.011, M["frame"])
    P.cyl(cx, cy, z - 0.17, z + 0.02, r, M["frame"], r2=r * 0.30)
    P.sphere(cx, cy, z - 0.155, r * 0.38, M["bulb"], sz=0.9)
    return P.finish()


def bed(M, face, ox, oy, w=1.62, l=2.02, headboard=0.0, name="cama"):
    """ox, oy = canto da cabeceira (u=0, v=0). v cresce para os pés."""
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0.04, w - 0.04, 0.06, l, 0.10, 0.34, M["walnut"])          # estrado
    L.b(0.02, w - 0.02, 0.06, l - 0.02, 0.33, 0.58, M["linen"])    # colchão
    L.b(0.0, w, 0.40, l - 0.02, 0.565, 0.62, M["linen"])           # edredão
    L.b(-0.02, w + 0.02, l - 0.58, l + 0.02, 0.575, 0.645, M["throw"])  # manta
    for i in (0, 1):
        u0 = 0.10 + i * (w / 2.0 - 0.06)
        L.b(u0, u0 + w / 2.0 - 0.22, 0.12, 0.52, 0.565, 0.71, M["linen"])
    if headboard > 0:
        L.b(-0.02, w + 0.02, 0.0, 0.12, 0.26, 0.26 + headboard, M["fabric"])
    else:
        L.b(0.0, w, 0.0, 0.06, 0.10, 0.95, M["walnut"])
    return P.finish()


def curtains(M, x0, x1, y=7.44, name="cortinado", panel=0.62, z1=2.50):
    """Dois panos recolhidos nas ombreiras de um envidraçado, mais a calha.

    Não fecham o vão: a vista para o mar é o argumento de venda da casa. Servem de
    enquadramento — sem eles, cada vão é um rectângulo de vidro colado a uma parede lisa.
    """
    P = Piece(name, furn_coll())
    for a, b in ((x0 - 0.10, x0 - 0.10 + panel), (x1 + 0.10 - panel, x1 + 0.10)):
        P.drape(a, b, y, 0.02, z1, M["sheer"], amp=0.045, waves=4)
    # calha: cilindro ao longo de X, feito por caixa fina (o cilindro do Piece é vertical)
    P.box(x0 - 0.20, x1 + 0.20, y - 0.02, y + 0.02, z1, z1 + 0.035, M["black"])
    return P.finish()


def nightstand(M, face, ox, oy, w=0.42, d=0.38, h=0.46, name="mesa_cabeceira"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, d, 0.12, h, M["walnut"])
    L.b(0.03, w - 0.03, d, d + 0.016, h - 0.26, h - 0.05, M["lacquer"])
    L.b(w / 2 - 0.07, w / 2 + 0.07, d + 0.016, d + 0.032, h - 0.17, h - 0.14,
        M["chrome"])
    for u in (0.03, w - 0.07):
        L.b(u, u + 0.04, 0.04, d - 0.04, 0.0, 0.12, M["black"])
    return P.finish()


def table_lamp(M, cx, cy, z0, h=0.42, name="candeeiro"):
    P = Piece(name, furn_coll())
    P.cyl(cx, cy, z0, z0 + 0.02, 0.075, M["black"])
    P.cyl(cx, cy, z0 + 0.02, z0 + h * 0.55, 0.014, M["black"])
    P.cyl(cx, cy, z0 + h * 0.52, z0 + h, 0.13, M["lamp"], r2=0.16)
    return P.finish()


def wardrobe(M, face, ox, oy, w, d=0.60, h=2.30, doors=3, name="roupeiro"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, d, 0.0, h, M["lacquer"])
    dw = w / doors
    for i in range(doors):
        u0 = i * dw + 0.012
        L.b(u0, u0 + dw - 0.024, d, d + 0.018, 0.03, h - 0.03, M["lacquer"])
        L.b(u0 + dw - 0.10, u0 + dw - 0.055, d + 0.018, d + 0.038, 0.95, 1.45,
            M["chrome"])
    return P.finish()


def open_closet(M, face, ox, oy, w, d=0.60, h=2.30, name="closet_modulo"):
    """Módulo aberto: costas, ilhargas, prateleiras, varão e roupa abstracta."""
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, 0.03, 0.0, h, M["lacquer"])                 # costas
    for u in (0.0, w - 0.03):
        L.b(u, u + 0.03, 0.03, d, 0.0, h, M["lacquer"])      # ilhargas
    L.b(0, w, 0.03, d, 0.0, 0.05, M["lacquer"])
    L.b(0, w, 0.03, d, h - 0.04, h, M["lacquer"])
    L.b(0, w, 0.03, d, 1.28, 1.32, M["lacquer"])             # prateleira média
    # varão + roupa pendurada (caixas de tons neutros)
    x0, y0 = L.xy(0.06, d / 2.0)
    x1, y1 = L.xy(w - 0.06, d / 2.0)
    P.box(min(x0, x1), max(x0, x1), min(y0, y1) - 0.012, max(y0, y1) + 0.012,
          1.53, 1.57, M["chrome"])
    u = 0.10
    tones = [M["linen"], M["fabric"], M["throw"], M["cushion"], M["linen"],
             M["walnut"], M["fabric"]]
    i = 0
    while u < w - 0.20:
        wdt = 0.09 + 0.03 * ((i * 7) % 3)
        L.b(u, u + wdt, 0.12, d - 0.10, 0.72, 1.50, tones[i % len(tones)])
        u += wdt + 0.035
        i += 1
    # caixas na prateleira de cima
    u = 0.10
    for k in range(3):
        L.b(u, u + 0.34, 0.10, d - 0.08, 1.32, 1.62, tones[(k + 2) % len(tones)])
        u += 0.40
        if u > w - 0.36:
            break
    return P.finish()


def shelf_unit(M, face, ox, oy, w, d=0.32, h=2.10, rows=5, name="estante"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, 0.025, 0.0, h, M["lacquer"])
    for u in (0.0, w - 0.025):
        L.b(u, u + 0.025, 0.025, d, 0.0, h, M["lacquer"])
    tones = [M["linen"], M["cushion"], M["fabric"], M["throw"], M["walnut"]]
    for r in range(rows + 1):
        z = h * r / float(rows)
        L.b(0, w, 0.025, d, max(0.0, z - 0.02), min(h, z + 0.02), M["lacquer"])
        if 0 < r < rows:
            L.b(0.10 + 0.05 * (r % 2), 0.10 + 0.05 * (r % 2) + 0.30,
                0.06, d - 0.05, z + 0.02, z + 0.24, tones[r % len(tones)])
            if w > 0.95:
                L.b(w - 0.48, w - 0.16, 0.06, d - 0.05, z + 0.02, z + 0.20,
                    tones[(r + 2) % len(tones)])
    return P.finish()


def bench(M, face, ox, oy, w=1.30, d=0.40, h=0.45, name="banco", top=None):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0, d, h - 0.12, h, top or M["throw"])
    for u in (0.04, w - 0.10):
        L.b(u, u + 0.06, 0.05, d - 0.05, 0.0, h - 0.12, M["walnut"])
    return P.finish()


def kitchen_run(M, name="cozinha"):
    """Bancada contínua na parede leste da sala (x = 9.60), com lava-loiça,
    placa, exaustor, armários superiores/inferiores e frigorífico."""
    P = Piece(name, furn_coll())
    xw = 9.60                      # face interior da parede leste
    y0, y1 = 5.35, 7.35            # desenvolvimento da bancada (metade norte, conforme planta)
    # rodapé + carcaça + frentes
    P.box(xw - 0.55, xw, y0, y1, 0.0, 0.10, M["black"])
    P.box(xw - 0.60, xw, y0, y1, 0.10, 0.86, M["lacquer"])
    ny = int((y1 - y0) / 0.50)
    for i in range(ny):
        a = y0 + i * (y1 - y0) / ny + 0.008
        b = y0 + (i + 1) * (y1 - y0) / ny - 0.008
        P.box(xw - 0.618, xw - 0.60, a, b, 0.12, 0.84, M["lacquer"])
        P.box(xw - 0.628, xw - 0.618, (a + b) / 2 - 0.09, (a + b) / 2 + 0.09,
              0.74, 0.78, M["chrome"])
    # bancada de pedra + frontão
    P.box(xw - 0.635, xw, y0 - 0.02, y1 + 0.02, 0.86, 0.90, M["stone"])
    P.box(xw - 0.02, xw, y0 - 0.02, y1 + 0.02, 0.90, 1.46, M["tile_x"])
    # lava-loiça
    P.box(xw - 0.52, xw - 0.12, 5.75, 6.30, 0.72, 0.895, M["steel"])
    P.box(xw - 0.49, xw - 0.15, 5.78, 6.27, 0.755, 0.90, M["black"])
    P.cyl(xw - 0.13, 6.03, 0.90, 1.22, 0.022, M["chrome"])
    P.box(xw - 0.34, xw - 0.11, 6.01, 6.05, 1.18, 1.22, M["chrome"])
    # placa de indução
    P.box(xw - 0.56, xw - 0.08, 6.60, 7.20, 0.898, 0.912, M["black"])
    for dx, dy in ((-0.42, 6.75), (-0.20, 6.75), (-0.42, 7.05), (-0.20, 7.05)):
        P.cyl(xw + dx, dy, 0.912, 0.915, 0.085, M["screen"])
    # exaustor
    P.box(xw - 0.42, xw, 6.53, 7.27, 1.52, 1.60, M["steel"])
    P.box(xw - 0.42, xw, 6.53, 7.27, 1.60, 1.74, M["steel"])
    P.box(xw - 0.28, xw, 6.77, 7.03, 1.74, CEIL, M["steel"])
    # armários superiores (a sul do exaustor)
    P.box(xw - 0.35, xw, y0, 6.47, 1.50, 2.25, M["lacquer"])
    for i in range(2):
        a = y0 + i * (6.47 - y0) / 2 + 0.008
        b = y0 + (i + 1) * (6.47 - y0) / 2 - 0.008
        P.box(xw - 0.368, xw - 0.35, a, b, 1.52, 2.23, M["lacquer"])
    # frigorífico (coluna, a sul da bancada)
    P.box(xw - 0.66, xw, 4.45, 5.15, 0.0, 1.92, M["steel"])
    P.box(xw - 0.675, xw - 0.66, 4.47, 5.13, 0.04, 1.24, M["steel"])
    P.box(xw - 0.675, xw - 0.66, 4.47, 5.13, 1.27, 1.88, M["steel"])
    P.box(xw - 0.695, xw - 0.675, 4.51, 4.57, 0.90, 1.20, M["chrome"])
    P.box(xw - 0.695, xw - 0.675, 4.51, 4.57, 1.32, 1.62, M["chrome"])
    return P.finish()


def vanity(M, face, ox, oy, w=1.10, d=0.47, name="lavatorio"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0.03, w - 0.03, 0.04, d, 0.22, 0.80, M["walnut"])         # móvel
    L.b(0.10, w - 0.10, d, d + 0.018, 0.40, 0.435, M["chrome"])   # puxador
    L.b(0, w, 0.0, d + 0.02, 0.80, 0.85, M["stone"])               # tampo
    # bacia: 4 bordos + fundo, para ler como recesso
    bu0, bu1 = w / 2 - 0.26, w / 2 + 0.26
    bv0, bv1 = 0.10, d - 0.06
    L.b(bu0, bu1, bv0, bv1, 0.845, 0.885, M["ceramic"])            # fundo
    L.b(bu0, bu0 + 0.035, bv0, bv1, 0.845, 0.965, M["ceramic"])
    L.b(bu1 - 0.035, bu1, bv0, bv1, 0.845, 0.965, M["ceramic"])
    L.b(bu0, bu1, bv0, bv0 + 0.035, 0.845, 0.965, M["ceramic"])
    L.b(bu0, bu1, bv1 - 0.035, bv1, 0.845, 0.965, M["ceramic"])
    L.c(w / 2, 0.10, 0.85, 1.14, 0.021, M["chrome"])
    L.b(w / 2 - 0.02, w / 2 + 0.02, 0.10, 0.24, 1.10, 1.14, M["chrome"])
    return P.finish()


def mirror_panel(M, face, ox, oy, w, h, z0, name="espelho"):
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0, w, 0.0, 0.02, z0, z0 + h, M["frame"])
    L.b(0.012, w - 0.012, 0.02, 0.028, z0 + 0.012, z0 + h - 0.012, M["mirror"])
    return P.finish()


def toilet(M, face, ox, oy, name="sanita"):
    """ox, oy = canto do autoclismo encostado à parede (u=0, v=0). Largura 0.40.

    A cuba e o tampo eram duas lajes de 6 cm sobre um pé de 12 cm: de cima lia-se como
    duas folhas brancas pousadas no chão. Agora o pé acompanha a cuba em toda a
    profundidade e a frente é redonda, que é o que dá a silhueta de sanita.
    """
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    cer = M["ceramic"]
    L.b(0.02, 0.38, 0.0, 0.17, 0.30, 0.88, cer)                 # autoclismo
    L.b(0.0, 0.40, 0.0, 0.19, 0.88, 0.915, cer)                 # tampo do autoclismo
    # pé: da parede até sob a frente da cuba, a estreitar — sem isto a cuba flutuava
    L.b(0.09, 0.31, 0.08, 0.50, 0.0, 0.34, cer)
    L.c(0.20, 0.50, 0.0, 0.34, 0.11, cer)
    # cuba: caixa + nariz redondo
    L.b(0.03, 0.37, 0.12, 0.52, 0.30, 0.42, cer)
    L.c(0.20, 0.52, 0.30, 0.42, 0.17, cer)
    # assento e tampo, a acompanhar a mesma planta
    L.b(0.025, 0.375, 0.11, 0.53, 0.42, 0.455, cer)
    L.c(0.20, 0.53, 0.42, 0.455, 0.175, cer)
    L.b(0.14, 0.26, 0.02, 0.06, 0.82, 0.86, M["chrome"])        # botão
    ob = P.finish()
    # louça não tem arestas vivas; o bevel geral de 4 mm é pouco a esta escala
    pbr.bevel_all([ob], width=0.012, segments=3, angle_deg=50.0)
    return ob


def shower(M, face, ox, oy, w=1.42, d=0.62, screen_len=None, name="duche"):
    """Base + resguardo de vidro. Coluna de duche no plano v=0 (parede de fundo),
    resguardo no plano v=d, com abertura de entrada no topo de u."""
    P = Piece(name, furn_coll())
    L = Local(P, face, ox, oy)
    L.b(0.0, w, 0.0, d, 0.0, 0.045, M["tile_floor"])
    L.c(w / 2.0, d / 2.0, 0.045, 0.056, 0.045, M["chrome"])       # ralo
    sl = screen_len or (w - 0.36)
    L.b(0.0, sl, d - 0.012, d, 0.045, 2.05, M["glass"])
    L.b(0.0, 0.022, d - 0.022, d, 0.045, 2.05, M["frame"])
    L.b(sl - 0.022, sl, d - 0.022, d, 0.045, 2.05, M["frame"])
    # coluna + chuveiro na parede de fundo
    L.c(w / 2.0, 0.055, 0.90, 2.02, 0.016, M["chrome"])
    L.b(w / 2.0 - 0.11, w / 2.0 + 0.11, 0.0, 0.32, 2.00, 2.035, M["chrome"])
    L.b(w / 2.0 - 0.10, w / 2.0 + 0.10, 0.22, 0.32, 1.955, 2.00, M["chrome"])
    return P.finish()


def door_leaf(M, x0, x1, y0, y1, h=DOOR_H - 0.02, name="porta"):
    """Folha de porta (só na entrada: sem ela, o vão abre para o céu do HDRI)."""
    P = Piece(name, furn_coll())
    P.box(x0, x1, y0, y1, 0.0, h, M["lacquer"])
    cx = x0 + (x1 - x0) * 0.88 if (x1 - x0) > (y1 - y0) else x0
    if (x1 - x0) > (y1 - y0):
        P.cyl(cx, y1 + 0.03, 1.00, 1.06, 0.018, M["chrome"])
        P.box(cx - 0.02, cx + 0.10, y1 + 0.02, y1 + 0.05, 1.00, 1.06, M["chrome"])
    return P.finish()


def clad_room(M, room, z1=2.20, skip=None, floor=True):
    """Reveste as paredes interiores de uma divisão com azulejo (caixas finas de 12 mm)
    e sobrepõe pavimento cerâmico. skip = {'N'|'S'|'E'|'W': [(t0, t1), ...]} (vãos)."""
    x0, x1, y0, y1 = ROOMS[room]
    skip = skip or {}
    t = 0.012
    P = Piece("azulejo_%s" % room, furn_coll())
    for side in ("N", "S"):
        yy = (y1 - t, y1) if side == "N" else (y0, y0 + t)
        for a, b in subtract_spans((x0, x1), skip.get(side, [])):
            P.box(a, b, yy[0], yy[1], 0.0, z1, M["tile_y"])
    for side in ("E", "W"):
        xx = (x1 - t, x1) if side == "E" else (x0, x0 + t)
        for a, b in subtract_spans((y0, y1), skip.get(side, [])):
            P.box(xx[0], xx[1], a, b, 0.0, z1, M["tile_x"])
    if floor:
        P.box(x0, x1, y0, y1, 0.0, 0.014, M["tile_floor"])
    ob = P.finish()
    FURN.remove(ob)       # revestimento não conta como obstáculo
    return ob


# ---------------------------------------------------------------- divisões

def furnish_sala(M):
    # A cozinha ocupa a metade NORTE da parede nascente (y 5.35..7.35), pelo que a zona
    # de estar desce para sul e a zona de refeição fica a norte, ao lado da bancada.
    # Livres: passagem do hall (parede poente, y 1.74..2.84) e porta de entrada
    # (parede sul, x 8.20..9.10).
    # --- zona de estar (sul): sofá na parede poente virado a nascente, TV a nascente
    rug(M, 6.40, 8.70, 2.90, 5.05)
    # o bevel geral de 4 mm serve mesas e armários mas deixava o sofá com arestas de
    # marcenaria; estofo pede um raio uma ordem de grandeza acima
    upholstery = sofa(M, "E", 5.75, 5.00, w=2.05, d=0.92)   # y 2.95..5.00
    pbr.bevel_all([upholstery], width=0.022, segments=4, angle_deg=55.0)
    coffee_table(M, 7.55, 3.50, 1.00, 0.62)
    tv_unit(M, "W", 9.58, 3.05, w=1.30, d=0.42)       # y 3.05..4.35, por baixo do frigorífico
    tv_panel(M, "W", 9.57, 3.15, w=1.10, h=0.64, z0=0.95)
    # quadro por cima do sofá (parede poente; a nascente a essa cota está a TV)
    wall_art(M, "E", 5.70, 4.48, 1.00, 0.68, 1.22, M["art2"], name="quadro_sala")
    # planta real da biblioteca (ver PROPS) — as esferas verdes eram o detalhe mais
    # amador do render anterior
    # --- zona de refeição (norte, entre o envidraçado e a cozinha)
    dining_table(M, 7.00, 6.30, 1.50, 0.90)
    # as quatro cadeiras vêm da biblioteca CC0 (ver PROPS): são a peça mais próxima da
    # câmara na vista principal da sala e as de caixa liam-se logo como maquete
    pendant(M, 7.00, 6.30, z=2.02, name="pendente_jantar")
    # --- cozinha (metade norte da parede leste)
    kitchen_run(M)


# As camas correm no sentido do comprimento da divisão (cabeceira na parede SUL, pés para o
# envidraçado), não atravessadas na parede comprida. Um quarto tem 2,65 m de largura: uma
# cama de 2,00 m encostada à parede oeste deixava 0,61 m entre os pés e a parede este — não
# se passava. Assim a cama ocupa 1,62 m da largura e sobra 1,03 m de circulação a toda a
# extensão, e o comprimento da divisão (4,50 m) absorve os 2,00 m da cama.

def furnish_quarto(M):
    # cama x 2.96–4.58, y 3.15–5.15 (livre da porta do hall, que abre em x 4.62–5.52)
    bed(M, "N", 2.96, 3.15, w=1.62, l=2.00, name="cama_quarto")
    # sem mesa de cabeceira: a cama encosta à parede sul e o lado livre é a passagem de
    # entrada — uma cabeceira ali é o primeiro móvel contra o qual se esbarra, e sem
    # candeeiro (retirado por não caber) não tinha função nenhuma
    rug(M, 3.10, 4.80, 5.10, 6.80, name="tapete_quarto")
    # roupeiro na parede este, a norte da cama — não estreita a faixa de passagem
    wardrobe(M, "W", 5.57, 5.70, w=1.50, d=0.60, h=2.30, doors=3,
             name="roupeiro_quarto")
    wall_art(M, "E", 2.93, 6.40, 0.90, 0.62, 1.30, M["art1"], name="quadro_quarto")
    # a parede da cabeceira ficava vazia — é o enquadramento que a câmara do quarto apanha
    # de frente, e uma parede nua a ocupar meio panorama lê-se como obra por acabar
    wall_art(M, "N", 3.28, 3.10, 0.98, 0.66, 1.42, M["art3"],
             name="quadro_quarto_cabeceira")


def furnish_suite(M):
    # cama x 0.06–1.68, y 3.62–5.62 (livre da porta do closet, em x 1.85–2.75)
    bed(M, "N", 0.06, 3.62, w=1.62, l=2.00, headboard=0.92, name="cama_suite")
    # idem quarto: cabeceira retirada, ficava na passagem de entrada
    rug(M, 0.40, 2.20, 5.80, 7.30, name="tapete_suite")
    # o banco que estava a oeste deixava 0,06 m entre ele e a cama — retirado.
    # quadro na parede sul, acima da cabeceira (1,18 m de topo)
    wall_art(M, "N", 0.35, 3.57, 0.95, 0.66, 1.25, M["art3"], name="quadro_suite")


def furnish_closet(M):
    open_closet(M, "E", 0.04, 3.40, w=1.74, d=0.58, h=2.30, name="closet_poente")
    shelf_unit(M, "S", 1.76, 3.42, w=1.02, d=0.30, h=2.10, rows=5,
               name="closet_norte")
    mirror_panel(M, "W", 2.79, 2.95, 0.42, 1.60, 0.30, name="espelho_closet")


def furnish_is(M, room, mirror=True):
    x0, x1, y0, y1 = ROOMS[room]
    tag = room.replace("is_", "")
    # Duche a poente, lavatório na parede sul, sanita no canto nascente.
    #
    # A colisão não era da sanita, era do móvel: 1.10 × 0.47 numa parede de 2.50 m fazia a
    # gaveta cruzar a cuba. Com 0.85 × 0.38 o curso da gaveta desce para 38 cm e o móvel
    # acaba 35 cm antes da sanita (25 na social, que é 10 cm mais estreita). Chegou-se aqui
    # comparando três plantas em render e em planta — a alternativa era trocar as duas
    # peças de sítio, que media melhor mas punha o espelho fora do eixo de quem entra.
    shower(M, "E", x0 + 0.04, y1 - 0.04, w=1.42, d=0.62, name="duche_%s" % tag)
    vanity(M, "N", x0 + 0.68, y0 + 0.02, w=0.85, d=0.38, name="lavatorio_%s" % tag)
    if mirror:
        mirror_panel(M, "N", x0 + 0.73, y0 + 0.02, 0.75, 0.85, 1.05,
                     name="espelho_%s" % tag)
    toilet(M, "W", x1 - 0.02, y0 + 0.50, name="sanita_%s" % tag)


def furnish_hall(M):
    P = Piece("consola_hall", furn_coll())
    P.box(2.96, 3.62, 1.66, 1.96, 0.72, 0.78, M["walnut"])
    for x in (3.00, 3.54):
        P.box(x, x + 0.04, 1.70, 1.74, 0.0, 0.72, M["black"])
        P.box(x, x + 0.04, 1.90, 1.94, 0.0, 0.72, M["black"])
    P.finish()
    mirror_panel(M, "N", 3.06, 1.64, 0.50, 0.85, 1.02, name="espelho_hall")


def furnish_arrumo(M):
    """Estante em U: poente, sul e nascente. A parede norte fica livre porque é onde
    está o vão para a sala (x 5.67..6.57).

    d=0.28 em vez de 0.32 e a câmara recuada para (6.12, 0.92) — ver CAM_SPOTS. Com três
    paredes ocupadas sobram 0.96 × 1.00 m de chão, que é o que um arrumo desta área dá:
    a alternativa era manter uma única estante e uma divisão vazia.
    """
    d = 0.28
    x0, x1, y0, y1 = ROOMS["arrumo"]
    # poente: da estante sul até ao vão, virada a nascente
    shelf_unit(M, "E", x0 + 0.04, y1 - 0.02, w=y1 - 0.02 - (y0 + d + 0.02), d=d,
               h=2.05, rows=4, name="estante_arrumo_o")
    # nascente: mesma altura, virada a poente
    shelf_unit(M, "W", x1 - 0.04, y0 + d + 0.02, w=y1 - 0.02 - (y0 + d + 0.02), d=d,
               h=2.05, rows=4, name="estante_arrumo_e")
    # sul: entre as duas, virada a norte
    shelf_unit(M, "N", x0 + d + 0.06, y0 + 0.04, w=x1 - x0 - 2 * d - 0.14, d=d,
               h=2.05, rows=4, name="estante_arrumo_s")


def furnish_varanda(M):
    coffee_table(M, 7.20, 8.58, 0.62, 0.62, h=0.36, top=M["stone"],
                 legs=M["frame"], name="mesa_varanda")
    chair(M, "E", 6.42, 8.58, w=0.52, d=0.54, seat=M["throw"], frame=M["frame"],
          name="cadeira_var_o")
    chair(M, "W", 7.98, 8.58, w=0.52, d=0.54, seat=M["throw"], frame=M["frame"],
          name="cadeira_var_e")


def build_furniture(M):
    del FURN[:]
    furn_coll()
    # folha maior que o vão, para não deixar frestas de céu à volta
    door_leaf(M, ENTRANCE[1] - 0.05, ENTRANCE[2] + 0.05, 1.34, 1.40,
              h=ENTRANCE[3] + 0.05, name="porta_entrada")
    clad_room(M, "is_suite", z1=2.20, skip={"N": [(1.10, 2.00)]})
    clad_room(M, "is_social", z1=2.20, skip={"N": [(3.88, 4.78)]})
    furnish_sala(M)
    furnish_quarto(M)
    furnish_suite(M)
    furnish_closet(M)
    furnish_is(M, "is_suite")
    furnish_is(M, "is_social")
    furnish_hall(M)
    furnish_arrumo(M)
    furnish_varanda(M)
    for room, g0, g1 in GLAZING:
        curtains(M, g0, g1, name="cortinado_%s" % room)
    pbr.bevel_all(FURN)
    props(M)
    log("mobiliário: %d peças" % len(FURN))


# Adereços da biblioteca CC0: plantas, almofadas, cadeiras e loiça reais em vez de esferas
# e caixas. Ficam FORA de FURN de propósito — a verificação de folgas percorre polígono a
# polígono em python e estes modelos têm dezenas de milhares de faces; as posições abaixo
# são escolhidas dentro de espaço já validado como livre.
# A colocação é pelo centro da base do conjunto (ver pbr.append_model), não pela origem
# do ficheiro do asset.
PROPS = [
    # sem planta no canto sudeste da sala: à escala real o vaso ocupa 20 cm num canto de
    # 4 m vazio e lê-se como objecto esquecido, não como decoração
    ("potted_plant_01", (2.30, 7.10, 0.0), -35.0, 0.9, "planta_suite"),
    # sobre a consola (tampo a 0.78): o hall tem 1.35 m de profundidade e uma planta de
    # chão lia-se como obstáculo a meio da passagem
    ("potted_plant_01", (3.28, 1.81, 0.78), 15.0, 0.45, "planta_hall"),
    # assento do sofá: topo a 0.50, x 5.97..6.62 (o encosto ocupa x 5.75..5.95)
    ("throw_pillows_01", (6.28, 3.45, 0.50), 90.0, 0.80, "almofadas_sofa_s"),
    ("throw_pillows_01", (6.28, 4.55, 0.50), 90.0, 0.80, "almofadas_sofa_n"),
    # cadeiras de jantar reais: a mesa (7.00, 6.30) mede 1.50 × 0.90, logo y 5.85..6.75.
    # O modelo tem as costas em +Y, portanto as do lado sul levam 180°.
    ("dining_chair_02", (6.60, 5.52, 0.0), 180.0, 1.0, "cadeira_s_660"),
    ("dining_chair_02", (7.40, 5.52, 0.0), 180.0, 1.0, "cadeira_s_740"),
    ("dining_chair_02", (6.60, 7.08, 0.0), 0.0, 1.0, "cadeira_n_660"),
    ("dining_chair_02", (7.40, 7.08, 0.0), 0.0, 1.0, "cadeira_n_740"),
    ("wooden_bowl_01", (7.00, 6.30, 0.75), 0.0, 1.0, "taca_mesa"),
    # almofadas decorativas à frente das de dormir, sobre o edredão (topo a 0.62)
    ("throw_pillows_01", (3.77, 3.86, 0.615), 0.0, 0.62, "almofadas_quarto"),
    ("throw_pillows_01", (0.87, 4.32, 0.615), 0.0, 0.62, "almofadas_suite"),
    ("wicker_basket_01", (0.45, 3.15, 0.0), -20.0, 1.0, "cesto_closet"),
    ("potted_plant_04", (1.30, 8.55, 0.0), -60.0, 0.85, "planta_varanda"),
    # bancada da cozinha: face interior a x=8.965, tampo a 0.90
    ("ceramic_vase_02", (9.22, 5.58, 0.90), 0.0, 1.0, "jarra_cozinha"),
]


# O `throw_pillows_01` da biblioteca vem com um ziguezague vermelho e ocre dos anos 70 —
# aparecia no sofá e nas duas camas, e era o único padrão saturado do apartamento. Só o
# material é trocado: a geometria amarrotada do asset é o que dá o ar de tecido usado.
PROP_MATERIALS = {
    "almofadas_sofa_s": "cushion",
    "almofadas_sofa_n": "cushion2",
    "almofadas_quarto": "cushion",
    "almofadas_suite": "cushion2",
}


def props(M):
    coll = furn_coll()
    placed = 0
    for slug, loc, rot, scale, name in PROPS:
        root = pbr.append_model(slug, coll, location=loc, rotation_z=rot, scale=scale,
                                name=name)
        if not root:
            continue
        placed += 1
        mat = M.get(PROP_MATERIALS.get(name, ""))
        if mat:
            for ob in root.children_recursive:
                for slot in ob.material_slots:
                    slot.material = mat
    log("adereços da biblioteca: %d de %d (%d retexturados)"
        % (placed, len(PROPS), len(PROP_MATERIALS)))


# ---------------------------------------------------------------- luz

def lighting(M):
    scene = bpy.context.scene
    lights = get_collection("Lights")

    # --- céu: HDRI fotográfico de fim de tarde (CC0, sem chão — o mar é geometria nossa)
    # O Nishita procedural dava um azul uniforme sem nuvens nem gradiente de horizonte;
    # nos reflexos do vidro e da pedra isso lê-se imediatamente como render sintético.
    pbr.world_hdri(SKY_HDRI, strength=SKY_STRENGTH, rotation_deg=SKY_ROT)

    # --- sol
    az, el = math.radians(SUN_AZ), math.radians(SUN_ELEV)
    to_sun = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az),
                     math.sin(el)))
    ld = bpy.data.lights.new("Sol", type="SUN")
    ld.energy = SUN_W
    ld.angle = math.radians(1.6)
    ld.color = (1.0, 0.955, 0.90)   # sol de fim de tarde, mas sem dominante sépia
    sun = bpy.data.objects.new("Sol", ld)
    sun.location = to_sun * 24.0 + Vector((4.8, 4.0, 0.0))
    sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    lights.objects.link(sun)
    log("sol %.1f W/m² elev=%.0f° azim=%.0f° (NO) + HDRI %s (rot %.0f°, %.2f)"
        % (SUN_W, SUN_ELEV, SUN_AZ, SKY_HDRI, SKY_ROT, SKY_STRENGTH))

    # --- luz de tecto fraca e quente por divisão (evita cantos negros); as divisões
    # sem envidraçado levam mais potência, pois não recebem luz natural directa
    glazed = set(r for r, _, _ in GLAZING)
    for name in INTERIOR_ROOMS:
        x0, x1, y0, y1 = ROOMS[name]
        area = (x1 - x0) * (y1 - y0)
        d = bpy.data.lights.new("luz_%s" % name, type="AREA")
        d.shape = "RECTANGLE"
        d.size = max(0.5, (x1 - x0) * 0.55)
        d.size_y = max(0.5, (y1 - y0) * 0.55)
        d.energy = (area * FILL_W_PER_M2 if name in glazed
                    else max(6.0, area * FILL_W_DARK))
        d.color = WARM_4200K
        ob = bpy.data.objects.new("luz_%s" % name, d)
        ob.location = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, CEIL - 0.05)
        ob.visible_camera = False       # não aparece como rectângulo branco
        lights.objects.link(ob)

    # foco dedicado sobre a bancada da cozinha (canto mais afastado do envidraçado)
    kd = bpy.data.lights.new("luz_cozinha", type="AREA")
    kd.shape = "RECTANGLE"
    kd.size = 0.50
    kd.size_y = 2.20
    kd.energy = 20.0
    kd.color = WARM_4200K
    kob = bpy.data.objects.new("luz_cozinha", kd)
    kob.location = (9.28, 6.30, CEIL - 0.08)
    kob.visible_camera = False
    lights.objects.link(kob)

    log("area lights 4200 K: %d divisões (%.2f W/m² c/ vão, %.2f W/m² interiores)"
        % (len(INTERIOR_ROOMS), FILL_W_PER_M2, FILL_W_DARK))


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 64
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    sc.cycles.max_bounces = 8
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 3
    sc.cycles.transmission_bounces = 8
    sc.cycles.transparent_max_bounces = 8
    sc.cycles.volume_bounces = 0
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.blur_glossy = 1.5
    sc.cycles.use_fast_gi = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.exposure = EXPOSURE
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "None"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            continue
    sc.render.image_settings.file_format = "PNG"
    log("render: Cycles CPU 64 spp, AgX exp=%+.1f, look=%s"
        % (EXPOSURE, sc.view_settings.look))


def furnish():
    M = build_materials()
    assign_shell_materials(M)
    build_furniture(M)
    lighting(M)
    setup_render()
    missing = [ob.name for ob in bpy.data.objects
               if ob.type == "MESH" and not ob.data.materials]
    if missing:
        log("AVISO: %d objectos sem material: %s" % (len(missing), missing[:8]))
    else:
        log("todos os objectos mesh têm material")
    qa_clearance_check()    # verificação padrão (3D + planta), não depende de --qa
    log("etapa furnish concluída — %d objectos na cena" % len(bpy.data.objects))


# Pontos de câmara panorâmica: `CAM_SPOTS`/`CAM_ROOM` vêm de geometry.py — `CAMS` (as
# câmaras reais) deriva daí, para não voltarem a divergir do que o QA verifica.
CAMS = {cam: CAM_SPOTS[room] for cam, room in CAM_ROOM.items()}


def cameras():
    """Cria câmaras perspécticas simples nos pontos de tour 360°; pipeline/render.py
    converte-as para equirectangular (cam.type='PANO') na altura do render — aqui basta
    posicioná-las a CAM_Z, niveladas (pitch 90° = a olhar para o horizonte; o guinada é
    irrelevante porque o pano cobre 360°)."""
    coll = get_collection("Cameras")
    for name, (x, y) in CAMS.items():
        cam_data = bpy.data.cameras.new(name)
        cam_data.lens = 18.0
        cam_data.clip_start = 0.02
        cam_data.clip_end = 60.0
        cam = bpy.data.objects.new(name, cam_data)
        cam.location = (x, y, CAM_Z)
        cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)  # nivelada, olha na horizontal
        coll.objects.link(cam)
    scene = bpy.context.scene
    if CAMS:
        scene.camera = bpy.data.objects[next(iter(CAMS))]
    log("etapa cameras: %d câmaras 360° criadas em %s" % (len(CAMS), sorted(CAMS)))


# ---------------------------------------------------------------- QA

QA_SECTION_Z = 1.20        # cota do corte horizontal da planta de QA


def qa_top_render(path):
    """Câmara ortográfica a prumo com corte horizontal a 1,20 m (planta de arquitectura):
    tudo acima do plano de corte é descartado pelo clip_start, pelo que os vãos de porta
    aparecem como interrupções nas paredes. Workbench + tectos escondidos."""
    scene = bpy.context.scene
    x0, x1, y0, y1 = BOUNDS
    cam_z = 20.0
    cam_data = bpy.data.cameras.new("QA_Top")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(x1 - x0, y1 - y0) * 1.05
    cam_data.clip_start = cam_z - QA_SECTION_Z   # corta acima de z=1.20
    cam_data.clip_end = cam_z + 2.0
    cam = bpy.data.objects.new("QA_Top", cam_data)
    cam.location = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, cam_z)
    cam.rotation_euler = (0.0, 0.0, 0.0)   # a olhar para -Z
    scene.collection.objects.link(cam)
    scene.camera = cam

    hidden = []
    for coll_name in ("Ceilings", "Floors"):
        coll = bpy.data.collections.get(coll_name)
        if coll:
            for ob in coll.objects:
                hidden.append((ob, ob.hide_render))
                ob.hide_render = True

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "RANDOM"
    scene.display.shading.show_shadows = False
    scene.display.shading.show_object_outline = True
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1600
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    log("QA render escrito em %s" % path)

    for ob, prev in hidden:
        ob.hide_render = prev
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)


# Vistas perspécticas de QA: (posição, alvo, distância focal em mm)
QA_SHOTS = {
    "sala":     ((8.60, 2.00, 1.62), (6.70, 6.80, 1.12), 20.0),
    "cozinha":  ((7.55, 4.45, 1.58), (9.52, 6.70, 1.05), 24.0),
    "quarto":   ((5.28, 3.52, 1.60), (3.45, 6.50, 1.00), 20.0),
    "suite":    ((2.52, 3.92, 1.60), (0.80, 6.60, 1.00), 20.0),
    "is_suite": ((2.36, 1.30, 1.58), (0.55, 0.30, 0.95), 16.0),
}


def _piece_distance(ob, px, py, pz):
    """Distância (conservadora) de um ponto à mesh, medida polígono a polígono — a
    caixa envolvente do objecto inteiro daria falsos positivos em peças compostas."""
    me = ob.data
    co = me.vertices
    best = 1e9
    for poly in me.polygons:
        vs = [co[i].co for i in poly.vertices]
        dx = max(min(v.x for v in vs) - px, 0.0, px - max(v.x for v in vs))
        dy = max(min(v.y for v in vs) - py, 0.0, py - max(v.y for v in vs))
        dz = max(min(v.z for v in vs) - pz, 0.0, pz - max(v.z for v in vs))
        d = dx * dx + dy * dy + dz * dz
        if d < best:
            best = d
            if best == 0.0:
                break
    return math.sqrt(best)


def _piece_distance_xy(ob, px, py, min_top=CAM_XY_MIN_TOP):
    """Distância EM PLANTA (ignora Z) do ponto à mesh, contando só polígonos que atingem
    pelo menos `min_top` de altura.

    Sem isto uma peça baixa mesmo por baixo da câmara passa no teste 3D (a distância
    vertical mascara a horizontal) e a câmara acaba em cima da cama. Peças abaixo da
    altura de assento (tapetes, mesas de centro, bases de duche) não impedem a posição.
    """
    me = ob.data
    co = me.vertices
    best = 1e9
    for poly in me.polygons:
        vs = [co[i].co for i in poly.vertices]
        if max(v.z for v in vs) < min_top:
            continue
        dx = max(min(v.x for v in vs) - px, 0.0, px - max(v.x for v in vs))
        dy = max(min(v.y for v in vs) - py, 0.0, py - max(v.y for v in vs))
        d = dx * dx + dy * dy
        if d < best:
            best = d
            if best == 0.0:
                break
    return math.sqrt(best)


def qa_clearance_check():
    """Duas verificações por posição de câmara (meshes já em coordenadas do mundo):

    1. folga 3D >= CAM_CLEAR — a câmara não está dentro de nenhuma peça;
    2. folga em planta >= CAM_CLEAR_XY para peças acima de CAM_XY_MIN_TOP — a câmara não
       está POR CIMA de mobiliário (foi assim que as câmaras do quarto e da suite
       ficaram em cima das camas: passavam no teste 3D pela distância vertical).
    """
    bad = 0
    for room, (cx, cy) in sorted(CAM_SPOTS.items()):
        clear = CAM_CLEAR_ROOM.get(room, CAM_CLEAR)
        worst, worst_ob = 1e9, None
        worst_xy, worst_xy_ob = 1e9, None
        for ob in FURN:
            d = _piece_distance(ob, cx, cy, CAM_Z)
            if d < worst:
                worst, worst_ob = d, ob.name
            if d < clear:
                log("AVISO folga 3D: %-10s ←→ %-22s %.3f m" % (room, ob.name, d))
                bad += 1
            h = _piece_distance_xy(ob, cx, cy)
            if h < worst_xy:
                worst_xy, worst_xy_ob = h, ob.name
            if h < CAM_CLEAR_XY:
                log("AVISO folga planta: %-10s ←→ %-22s %.3f m"
                    % (room, ob.name, h))
                bad += 1
        log("folga mínima %-10s 3D %.2f m (%-22s)  planta %.2f m (%s)"
            % (room, worst, worst_ob, worst_xy, worst_xy_ob))
    log("QA folgas de câmara: %d conflitos (3D >= %.2f m, planta >= %.2f m acima de %.2f m; "
        "excepções: %s)"
        % (bad, CAM_CLEAR, CAM_CLEAR_XY, CAM_XY_MIN_TOP,
           ", ".join("%s %.2f" % kv for kv in sorted(CAM_CLEAR_ROOM.items())) or "nenhuma"))
    return bad


def qa_persp_renders(outdir):
    """Uma pré-visualização perspéctica por divisão-chave (Cycles, 1280×720, 64 spp)."""
    scene = bpy.context.scene
    setup_render()
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    os.makedirs(outdir, exist_ok=True)
    prev_cam = scene.camera
    for room, (loc, target, lens) in sorted(QA_SHOTS.items()):
        cd = bpy.data.cameras.new("QA_%s" % room)
        cd.lens = lens
        cd.clip_start = 0.02
        cd.clip_end = 120.0
        cam = bpy.data.objects.new("QA_%s" % room, cd)
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(target) - Vector(loc)) \
            .to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(cam)
        scene.camera = cam
        path = os.path.join(outdir, "persp_%s.png" % room)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        log("QA perspectiva %-9s (%.1f mm) → %s" % (room, lens, path))
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cd)
    scene.camera = prev_cam


# ---------------------------------------------------------------- main

def parse_args(argv):
    p = argparse.ArgumentParser(prog="model_t2.py")
    p.add_argument("--stage", default="all",
                   choices=["geometry", "furnish", "cameras", "all"])
    p.add_argument("--save", action="store_true", help="grava projects/demo-t2/scene.blend")
    p.add_argument("--qa", action="store_true", help="renderiza qa/top.png (planta ortográfica)")
    p.add_argument("--out", default=os.path.join(HERE, "scene.blend"))
    return p.parse_args(argv)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parse_args(argv)
    log("etapa=%s save=%s qa=%s" % (args.stage, args.save, args.qa))

    if args.stage in ("geometry", "all"):
        build_geometry()
    if args.stage in ("furnish", "all"):
        furnish()
    if args.stage in ("cameras", "all"):
        cameras()

    if args.qa:
        qa_top_render(os.path.join(HERE, "qa", "top.png"))
        if args.stage in ("furnish", "all"):
            bad = qa_clearance_check()
            qa_persp_renders(os.path.join(HERE, "qa"))
            if bad > 0:
                log("QA folgas de câmara FALHOU: %d conflito(s) — abortando." % bad)
                sys.exit(1)
    if args.save:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=args.out)
        log("cena gravada em %s" % args.out)
    log("OK")


# O Blender em `-b -P` termina com código 0 mesmo quando o script lança uma excepção;
# apanhamos aqui só para reemitir o traceback e sair com código != 0 (o pipeline depende disso).
try:
    main()
except Exception:
    traceback.print_exc()
    sys.stderr.flush()
    sys.exit(1)
