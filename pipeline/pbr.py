"""Materiais texturados, HDRI e modelos da biblioteca CC0 (Poly Haven).

Só corre dentro do Blender. A biblioteca é descarregada por `assets/library/fetch.py`.

Porquê projecção BOX e não UVs: a geometria dos projectos é gerada por bmesh (caixas,
cilindros, esferas) e não tem mapeamento UV. A projecção box a partir de coordenadas
`Object` mapeia a textura pelos três eixos do mundo e dá escala real em metros — uma
tábua de soalho mede o mesmo na sala e no quarto, sem desdobrar nada.
"""

import os

import bpy
import mathutils

_LIB = None


def library(path=None):
    """Raiz da biblioteca; definir uma vez a partir do projecto."""
    global _LIB
    if path:
        _LIB = path
    return _LIB


def _img(path, non_color=False):
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def tex_material(name, slug, size=2.0, base_tint=None, base_color=None, rough_mult=1.0,
                 normal_strength=1.0, coat=0.0, sheen=0.0, metal=0.0):
    """Material Principled com mapas de imagem da biblioteca.

    size = quantos metros cobre um ladrilho da textura (2.0 = a imagem repete a cada 2 m).
    base_tint = multiplica a cor difusa, para reaproveitar a mesma textura em variantes
    (o mesmo linho serve de roupa de cama clara e de tapete mais quente).
    base_color = ignora o mapa difuso e usa cor lisa, ficando só o relevo (rugosidade +
    normal). É o caso do reboco pintado: a tinta não tem variação de cor, só de superfície,
    e usar o difuso fotográfico traz o castanho da amostra para dentro da casa — foi o que
    fazia as paredes lerem-se sujas.
    """
    folder = os.path.join(_LIB, "texturas", slug)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]

    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0 / size,) * 3
    nt.links.new(mapping.inputs["Vector"], coord.outputs["Object"])

    def image_node(fname, non_color):
        path = os.path.join(folder, fname)
        if not os.path.exists(path):
            return None
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = _img(path, non_color)
        node.projection = "BOX"
        node.projection_blend = 0.25
        node.extension = "REPEAT"
        nt.links.new(node.inputs["Vector"], mapping.outputs["Vector"])
        return node

    diff = None if base_color else image_node("diffuse.jpg", False)
    if base_color:
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    if diff:
        if base_tint:
            # VectorMath e não MixRGB: os sockets de cor do Blender estão fixados a 0..1,
            # pelo que um tinte > 1 (levantar uma amostra escura) era cortado em silêncio.
            mix = nt.nodes.new("ShaderNodeVectorMath")
            mix.operation = "MULTIPLY"
            mix.inputs[1].default_value = base_tint
            nt.links.new(mix.inputs[0], diff.outputs["Color"])
            nt.links.new(bsdf.inputs["Base Color"], mix.outputs["Vector"])
        else:
            nt.links.new(bsdf.inputs["Base Color"], diff.outputs["Color"])

    rough = image_node("rough.jpg", True)
    if rough:
        if rough_mult != 1.0:
            mul = nt.nodes.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            mul.inputs[1].default_value = rough_mult
            mul.use_clamp = True
            nt.links.new(mul.inputs[0], rough.outputs["Color"])
            nt.links.new(bsdf.inputs["Roughness"], mul.outputs["Value"])
        else:
            nt.links.new(bsdf.inputs["Roughness"], rough.outputs["Color"])

    nor = image_node("normal.jpg", True)
    if nor:
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = normal_strength
        nt.links.new(nmap.inputs["Color"], nor.outputs["Color"])
        nt.links.new(bsdf.inputs["Normal"], nmap.outputs["Normal"])

    bsdf.inputs["Metallic"].default_value = metal
    for socket, value in (("Coat Weight", coat), ("Sheen Weight", sheen)):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = value
    return m


def world_hdri(slug, strength=1.0, rotation_deg=0.0):
    """Substitui o céu procedural por um HDRI. Devolve o nó de mapping (para afinar o
    azimute do sol sem refazer o mundo)."""
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = _img(os.path.join(_LIB, "hdri", f"{slug}.hdr"))
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value[2] = rotation_deg * 3.141592653589793 / 180.0
    coord = nt.nodes.new("ShaderNodeTexCoord")

    nt.links.new(mapping.inputs["Vector"], coord.outputs["Generated"])
    nt.links.new(env.inputs["Vector"], mapping.outputs["Vector"])
    nt.links.new(bg.inputs["Color"], env.outputs["Color"])
    nt.links.new(out.inputs["Surface"], bg.outputs["Background"])
    return mapping


def append_model(slug, collection, location=(0, 0, 0), rotation_z=0.0, scale=1.0,
                 name=None):
    """Traz o objecto principal de um .blend da biblioteca para a cena.

    Devolve o objecto raiz (já com filhos ligados) ou None se o ficheiro não existir —
    assim uma biblioteca por descarregar degrada para "sem o adereço" em vez de rebentar.
    """
    path = os.path.join(_LIB, "modelos", slug, f"{slug}.blend")
    if not os.path.exists(path):
        print(f"[pbr] AVISO: modelo em falta: {path}")
        return None

    before = set(bpy.data.objects)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    new = [o for o in bpy.data.objects if o not in before]
    # Os .blend do Poly Haven trazem o estúdio de apresentação junto: uma Camera, uma
    # Light e um Cube de fundo. Importados sem filtro, acendiam luzes soltas dentro da casa.
    STUDIO = ("Cube", "Plane", "Backdrop", "Floor", "Ground")
    keep = [o for o in new if o.type in ("MESH", "EMPTY")
            and o.name.split(".")[0] not in STUDIO]
    for o in new:
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    new = keep
    if not new:
        return None

    for ob in new:
        collection.objects.link(ob)
    roots = [o for o in new if o.parent is None] or new

    # Muitos assets vêm em peças soltas, não numa hierarquia: as almofadas são dois
    # objectos irmãos e o conjunto de livros são noventa, cada um com o seu deslocamento.
    # Transformar só o primeiro deixava os restantes esquecidos na origem do mundo (havia
    # uma pilha de livros dentro da I.S. da suite). Ancorar tudo a um Empty no centro da
    # base do conjunto preserva as posições relativas e dá um ponto de colocação previsível.
    mn = [1e9] * 3
    mx = [-1e9] * 3
    for ob in new:
        for corner in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(corner)
            for i in range(3):
                mn[i] = min(mn[i], w[i])
                mx[i] = max(mx[i], w[i])
    anchor = ((mn[0] + mx[0]) / 2.0, (mn[1] + mx[1]) / 2.0, mn[2])

    root = bpy.data.objects.new(name or slug, None)
    collection.objects.link(root)
    root.empty_display_size = 0.1
    for ob in roots:
        ob.location = (ob.location[0] - anchor[0], ob.location[1] - anchor[1],
                       ob.location[2] - anchor[2])
        ob.parent = root
    root.location = location
    root.rotation_euler[2] = rotation_z * 3.141592653589793 / 180.0
    root.scale = (scale, scale, scale)
    return root


def bevel_all(objects, width=0.004, segments=2, angle_deg=35.0):
    """Bevel de canto vivo. Uma aresta perfeitamente viva não existe na realidade e é o
    que faz a geometria de caixas ler-se como maquete: o bevel devolve o brilho fino que
    o olho procura no limite de cada peça."""
    for ob in objects:
        if ob.type != "MESH" or any(m.type == "BEVEL" for m in ob.modifiers):
            continue
        mod = ob.modifiers.new("bevel", "BEVEL")
        mod.width = width
        mod.segments = segments
        mod.limit_method = "ANGLE"
        mod.angle_limit = angle_deg * 3.141592653589793 / 180.0
        mod.harden_normals = True
        # `use_auto_smooth` desapareceu no Blender 4.1; sem o guarda, o bevel com
        # harden_normals rebentava em vez de simplesmente não suavizar
        if hasattr(ob.data, "use_auto_smooth"):
            ob.data.use_auto_smooth = True
        for poly in ob.data.polygons:
            poly.use_smooth = True
