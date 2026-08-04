"""Geometria do T2 demo em python puro — sem `bpy`.

Fonte única das cotas: `model_t2.py` importa daqui para construir a cena no Blender, e o
pipeline (`build_tour.py`, `plan_svg.py`) importa daqui para validar hotspots e desenhar a
planta sem precisar do Blender instalado.

Origem = canto SW interior, metros; X→este, Y→norte (fachada da varanda a norte, y=7,59);
Z para cima. Os rects de ROOMS são faces INTERIORES das divisões.
"""

# ---------------------------------------------------------------- constantes

CEIL = 2.60            # pé-direito
WALL_INT = 0.12        # espessura de divisória interior
WALL_EXT = 0.25        # espessura de parede exterior
SLAB = 0.15            # espessura da laje de piso (z -0.15..0) e de tecto (2.60..2.75)
DOOR_W = 0.90
DOOR_H = 2.10          # verga da porta
GLAZ_H = 2.26          # altura do vão envidraçado (soleira a z=0, correr até ao tecto)
FRAME = 0.06           # espessura dos caixilhos
GLASS_T = 0.03         # espessura do vidro
RAIL_H = 1.00          # altura da guarda de vidro da varanda

ROOMS = {
    #                x0     x1     y0     y1
    "suite":       (0.00,  2.80,  3.56,  7.59),   # 2.80×4.03 = 11.28
    "closet":      (0.00,  2.80,  1.62,  3.44),   # 2.80×1.82 = 5.10
    "is_suite":    (0.00,  2.60,  0.00,  1.50),   # 2.60×1.50 = 3.90
    "quarto":      (2.92,  5.57,  3.09,  7.59),   # 2.65×4.50 = 11.93
    "hall":        (2.92,  5.57,  1.62,  2.97),   # distribuição ≈ 3.36
    "is_social":   (2.72,  5.22,  0.00,  1.50),   # 2.50×1.50 = 3.75
    "arrumo":      (5.34,  6.90,  0.00,  1.30),   # 1.56×1.30 = 2.03
    "sala":        (5.69,  9.60,  1.54,  7.59),   # 3.91×6.05 = 23.65 (cozinha na parede leste)
    "varanda":     (0.00,  9.60,  7.84,  9.30),   # 9.60×1.46 ≈ 14.15, fora da fachada
}

INTERIOR_ROOMS = [n for n in ROOMS if n != "varanda"]

# Vãos entre divisões: (div_a, div_b, t0, t1, altura). t = coordenada tangente à parede
# partilhada (Y se a parede for vertical, X se for horizontal). Sem folhas de porta —
# vãos abertos, para não bloquear as vistas do tour.
DOORS = [
    ("hall", "quarto",    4.62, 5.52, DOOR_H),
    ("hall", "closet",    1.95, 2.85, DOOR_H),
    ("hall", "is_social", 3.88, 4.78, DOOR_H),
    ("hall", "sala",      1.74, 2.84, DOOR_H),   # passagem aberta 1,10 m
    ("closet", "suite",   1.85, 2.75, DOOR_H),
    ("closet", "is_suite", 1.10, 2.00, DOOR_H),
    ("sala", "arrumo",    5.67, 6.57, DOOR_H),
]

# Porta de entrada: parede sul da sala (a leste do arrumo, junto à fachada nascente).
ENTRANCE = ("sala", 8.20, 9.10, DOOR_H)

# Portas de vidro de correr para a varanda, na fachada norte y=7.59: (divisão, x0, x1)
GLAZING = [
    ("suite",  0.30, 2.50),
    ("quarto", 3.20, 5.30),
    ("sala",   6.00, 8.35),   # nembo cheio a nascente (x 8.35..9.60), conforme planta
]

# Envolvente exterior (mar + costa distante): sem isto a metade inferior do panorama da
# varanda é vazio preto — o céu Nishita só preenche o hemisfério superior.
GROUND_Z = -6.00           # cota do mar, ~2 pisos abaixo do apartamento
GROUND_R = 400.0           # semi-extensão do plano de água

# Limites do conjunto (para enquadrar a câmara de QA e o minimapa)
BOUNDS = (-WALL_EXT, 9.60 + WALL_EXT, -WALL_EXT, 9.30)


# ---------------------------------------------------------------- câmaras

# Pontos de câmara panorâmica, por divisão — FONTE ÚNICA das coordenadas: `CAMS` (as
# câmaras reais no Blender) deriva daqui, para não voltarem a divergir do que o QA verifica.
CAM_SPOTS = {
    "sala": (7.30, 4.30), "cozinha": (8.25, 6.35), "quarto": (3.90, 6.30),
    "suite": (1.30, 6.60), "closet": (1.40, 2.50), "is_suite": (1.30, 0.98),
    "is_social": (3.97, 0.98), "hall": (4.60, 2.30), "varanda": (4.80, 8.55),
    "arrumo": (6.12, 0.92),
}
# arrumo: com estante nas três paredes (poente, sul e nascente) sobram 0.96 × 1.00 m de
# chão. O ponto antigo (6.30, 0.65) ficava a 0.28 m da estante nascente — abaixo do
# mínimo do QA. (6.12, 0.92) é o centro do que resta, a 0.46 m da peça mais próxima.
# quarto/suite: as câmaras estavam a 0,5 m dos pés da cama e dentro da largura dela, o que
# fazia a cama encher o quadro e a divisão parecer intransitável. Agora ficam na zona livre
# a norte da cama, com o envidraçado à frente e a cama em segundo plano.
CAM_Z = 1.55
CAM_CLEAR = 0.55       # folga 3D (a câmara não pode ficar dentro de uma peça)
# Excepção por divisão. O arrumo tem 1.56 m de largura: com estante nas paredes poente e
# nascente sobram menos de 1.10 m e NENHUM ponto cumpre os 0.55 m. A regra existe para o
# mobiliário não encher o quadro; num arrumo de 2 m² isso é o que a divisão é. Um
# fotógrafo dispara esta divisão da soleira, que é o que 0.45 m representa aqui.
CAM_CLEAR_ROOM = {"arrumo": 0.45}
CAM_CLEAR_XY = 0.45    # folga EM PLANTA: a câmara não pode ficar por cima de mobília
CAM_XY_MIN_TOP = 0.25  # peças mais baixas que isto não bloqueiam (tapetes, rodapés)

CAM_ROOM = {  # câmara 360° → ponto em CAM_SPOTS
    "360_sala": "sala", "360_cozinha": "cozinha", "360_quarto": "quarto",
    "360_suite": "suite", "360_closet": "closet", "360_is": "is_suite",
    "360_is_social": "is_social", "360_hall": "hall", "360_varanda": "varanda",
    "360_arrumo": "arrumo",
}

# Cena do tour → divisão de ROOMS onde a câmara está.
#
# Não é `CAM_ROOM` sem o prefixo: "cozinha" é um ponto de câmara, não uma divisão — a
# cozinha é a bancada na parede leste da SALA e não tem rect próprio em ROOMS. Sem este
# override, qualquer verificação geométrica procuraria uma parede entre "sala" e "cozinha"
# que não existe.
SCENE_ROOM = {cam.removeprefix("360_"): room for cam, room in CAM_ROOM.items()}
SCENE_ROOM["cozinha"] = "sala"


# ---------------------------------------------------------------- paredes e vãos

def find_partitions():
    """Detecta divisórias interiores a partir dos rects: pares de divisões adjacentes
    com uma folga <= 0.35 m num eixo e sobreposição no outro. A parede preenche a folga."""
    parts = []
    names = INTERIOR_ROOMS
    for i, a in enumerate(names):
        ax0, ax1, ay0, ay1 = ROOMS[a]
        for b in names[i + 1:]:
            bx0, bx1, by0, by1 = ROOMS[b]
            # parede vertical (normal em X)
            ov0, ov1 = max(ay0, by0), min(ay1, by1)
            if ov1 - ov0 > 0.05:
                for g0, g1, lo, hi in ((ax1, bx0, a, b), (bx1, ax0, b, a)):
                    if 1e-6 < g1 - g0 <= 0.35:
                        parts.append(dict(kind="x", lo=lo, hi=hi,
                                          f0=g0, f1=g1, t0=ov0, t1=ov1))
            # parede horizontal (normal em Y)
            oh0, oh1 = max(ax0, bx0), min(ax1, bx1)
            if oh1 - oh0 > 0.05:
                for g0, g1, lo, hi in ((ay1, by0, a, b), (by1, ay0, b, a)):
                    if 1e-6 < g1 - g0 <= 0.35:
                        parts.append(dict(kind="y", lo=lo, hi=hi,
                                          f0=g0, f1=g1, t0=oh0, t1=oh1))
    return parts


def door_for(a, b):
    key = frozenset((a, b))
    for ra, rb, t0, t1, h in DOORS:
        if frozenset((ra, rb)) == key:
            return (t0, t1, 0.0, h)
    return None


def partition_for(a, b):
    """A divisória que separa `a` de `b`, ou None. Mesmo par → mesma parede em
    `find_partitions()`, pelo que basta procurar pelo par {lo, hi}."""
    key = frozenset((a, b))
    for part in find_partitions():
        if frozenset((part["lo"], part["hi"])) == key:
            return part
    return None


def opening_segment(a, b):
    """Segmento 2D do vão que liga as divisões `a` e `b`, em coordenadas do mundo.

    Devolve ((x0, y0), (x1, y1)) no plano do eixo da parede, ou None se não houver ligação
    directa. Cobre os dois casos:

    - divisória interior: vão de `DOORS` sobre a parede devolvida por `partition_for`;
    - fachada norte: vão envidraçado de `GLAZING` quando um dos lados é a varanda.
    """
    if "varanda" in (a, b):
        room = b if a == "varanda" else a
        for name, x0, x1 in GLAZING:
            if name == room:
                _, _, _, y = ROOMS[room]      # fachada = bordo norte da divisão (y=7.59)
                return ((x0, y), (x1, y))
        return None

    door = door_for(a, b)
    part = partition_for(a, b)
    if door is None or part is None:
        return None
    t0, t1 = door[0], door[1]
    axis = (part["f0"] + part["f1"]) / 2.0    # eixo da parede, a meio da espessura
    if part["kind"] == "x":                   # parede vertical: t é Y, eixo é X
        return ((axis, t0), (axis, t1))
    return ((t0, axis), (t1, axis))           # parede horizontal: t é X, eixo é Y
