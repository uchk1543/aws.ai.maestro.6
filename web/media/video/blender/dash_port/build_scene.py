# 대시보드 부산항 장면 (흰 클레이 + 파랑·주황 컨테이너).
# 진행: 배 입항 → 안벽 크레인 하역 → 트럭 이동 → 검사대 → 게이트 반출 → 항구 전체로 빠짐 (인트로),
#       그다음 항구 전체 항공샷에서 트럭·크레인이 도는 되풀이 구간.
# 실행: blender -b -P build_scene.py -- [still]   (dash_port.blend 저장, still 이면 확인용 그림 몇 장 렌더)
import bpy, bmesh, math, random, sys, os
from mathutils import Vector, Matrix, Euler, Quaternion

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 24
INTRO = 576          # 24초
LOOP = 288           # 12초 (배경 트럭·크레인이 이 주기로 되풀이)
XF = 24              # 되풀이 이음매 겹침(물결만 다름)
END = INTRO + LOOP + XF
W, H = 1440, 630

random.seed(6)
bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
scn.render.fps = FPS
scn.frame_start, scn.frame_end = 1, END

# ---------------------------------------------------------------- 재질
def principled(name, color, rough=0.55, spec=0.5, metal=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = spec
    if coat and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = coat
    m.diffuse_color = (*color, 1)
    return m

WHITE = principled("white", (0.80, 0.82, 0.86), 0.55)
WHITE2 = principled("white2", (0.88, 0.89, 0.92), 0.5)
GROUND = principled("ground", (0.70, 0.72, 0.77), 0.7, 0.3)
LINE = principled("line", (0.92, 0.93, 0.96), 0.6)
RAIL = principled("rail", (0.36, 0.38, 0.43), 0.4, 0.6, 0.6)
BLUE = principled("blue", (0.010, 0.060, 0.78), 0.32, 0.5, 0, 0.25)
BLUE2 = principled("blue2", (0.016, 0.085, 0.86), 0.36, 0.5, 0, 0.25)
ORANGE = principled("orange", (0.90, 0.19, 0.018), 0.36, 0.5, 0, 0.25)
ORANGE2 = principled("orange2", (0.95, 0.25, 0.03), 0.4, 0.5, 0, 0.25)
DARK = principled("dark", (0.035, 0.037, 0.045), 0.55)
GLASS = principled("glass", (0.005, 0.03, 0.30), 0.08, 0.9)
GREEN = principled("green", (0.10, 0.36, 0.10), 0.7)
GREEN2 = principled("green2", (0.05, 0.25, 0.08), 0.7)
GREEN3 = principled("green3", (0.25, 0.48, 0.12), 0.7)
TRUNK = principled("trunk", (0.30, 0.17, 0.08), 0.8)
SCAN = bpy.data.materials.new("scan")
SCAN.use_nodes = True
_b = next(n for n in SCAN.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
_b.inputs["Base Color"].default_value = (0.1, 0.4, 1, 1)
_b.inputs["Emission Color"].default_value = (0.15, 0.45, 1, 1)
_b.inputs["Emission Strength"].default_value = 0.0
SCAN.blend_method = "BLEND"
_b.inputs["Alpha"].default_value = 0.0


def building_mat(name, wall, roof, win=(0.012, 0.05, 0.42), sx=3.2, sz=3.4, z0=1.6, wx=(0.28, 0.72), wz=(0.32, 0.76)):
    """벽은 흰색, 창은 파랑(물체 좌표 격자), 위를 보는 면은 지붕 색."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N = nt.nodes
    L = nt.links
    b = next(n for n in N if n.type == "BSDF_PRINCIPLED")
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sep.inputs[0])
    geo = N.new("ShaderNodeNewGeometry")
    nsep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], nsep.inputs[0])

    def math(op, a, bb=None, v=None):
        n = N.new("ShaderNodeMath")
        n.operation = op
        for i, x in enumerate((a, bb)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                L.new(x, n.inputs[i])
        return n.outputs[0]

    u = math("ADD", sep.outputs[0], sep.outputs[1])
    fu = math("FRACT", math("DIVIDE", u, sx))
    fz = math("FRACT", math("DIVIDE", math("SUBTRACT", sep.outputs[2], z0), sz))
    inu = math("MULTIPLY", math("GREATER_THAN", fu, wx[0]), math("LESS_THAN", fu, wx[1]))
    inz = math("MULTIPLY", math("GREATER_THAN", fz, wz[0]), math("LESS_THAN", fz, wz[1]))
    wall_face = math("LESS_THAN", math("ABSOLUTE", nsep.outputs[2]), 0.5)
    above = math("GREATER_THAN", sep.outputs[2], z0)
    win_f = math("MULTIPLY", math("MULTIPLY", inu, inz), math("MULTIPLY", wall_face, above))
    roof_f = math("GREATER_THAN", nsep.outputs[2], 0.6)

    mix1 = N.new("ShaderNodeMix")
    mix1.data_type = "RGBA"
    L.new(win_f, mix1.inputs["Factor"])
    mix1.inputs[6].default_value = (*wall, 1)
    mix1.inputs[7].default_value = (*win, 1)
    mix2 = N.new("ShaderNodeMix")
    mix2.data_type = "RGBA"
    L.new(roof_f, mix2.inputs["Factor"])
    L.new(mix1.outputs[2], mix2.inputs[6])
    mix2.inputs[7].default_value = (*roof, 1)
    L.new(mix2.outputs[2], b.inputs["Base Color"])
    rmap = N.new("ShaderNodeMapRange")
    L.new(win_f, rmap.inputs[0])
    rmap.inputs[3].default_value = 0.55
    rmap.inputs[4].default_value = 0.12
    L.new(rmap.outputs[0], b.inputs["Roughness"])
    m.diffuse_color = (*wall, 1)
    return m


W_BLUE = (0.010, 0.060, 0.78)
W_ORNG = (0.90, 0.19, 0.018)
W_WALL = (0.80, 0.82, 0.86)
BLD_B = building_mat("bld_blue", W_WALL, W_BLUE)
BLD_O = building_mat("bld_orange", W_WALL, W_ORNG)
BLD_W = building_mat("bld_white", W_WALL, (0.86, 0.87, 0.9))
BLD_TOWER = building_mat("bld_tower", W_WALL, (0.86, 0.87, 0.9), sx=2.2, sz=3.0, z0=1.0, wx=(0.18, 0.82), wz=(0.25, 0.8))
SHIP_WIN = building_mat("ship_win", W_WALL, (0.86, 0.87, 0.9), sx=2.0, sz=2.6, z0=0.6, wx=(0.25, 0.75), wz=(0.35, 0.75))

# 선체: 흰색, 뱃전 위쪽 파란 줄, 갑판은 회색
HULL = bpy.data.materials.new("hull")
HULL.use_nodes = True
_nt = HULL.node_tree
_N, _L = _nt.nodes, _nt.links
_b = next(n for n in _N if n.type == "BSDF_PRINCIPLED")
_b.inputs["Roughness"].default_value = 0.4
_tc = _N.new("ShaderNodeTexCoord")
_sp = _N.new("ShaderNodeSeparateXYZ")
_L.new(_tc.outputs["Object"], _sp.inputs[0])
_cr = _N.new("ShaderNodeValToRGB")
_cr.color_ramp.interpolation = "CONSTANT"
_e = _cr.color_ramp.elements
_e[0].position = 0.0
_e[0].color = (0.82, 0.84, 0.88, 1)
_e[1].position = 0.80
_e[1].color = (0.010, 0.060, 0.78, 1)
_e3 = _cr.color_ramp.elements.new(0.86)
_e3.color = (0.82, 0.84, 0.88, 1)
_mr = _N.new("ShaderNodeMapRange")
_L.new(_sp.outputs[2], _mr.inputs[0])
_mr.inputs[1].default_value = -1.0
_mr.inputs[2].default_value = 6.0
_L.new(_mr.outputs[0], _cr.inputs[0])
_geo = _N.new("ShaderNodeNewGeometry")
_ns = _N.new("ShaderNodeSeparateXYZ")
_L.new(_geo.outputs["Normal"], _ns.inputs[0])
_up = _N.new("ShaderNodeMath")
_up.operation = "GREATER_THAN"
_L.new(_ns.outputs[2], _up.inputs[0])
_up.inputs[1].default_value = 0.6
_mx = _N.new("ShaderNodeMix")
_mx.data_type = "RGBA"
_L.new(_up.outputs[0], _mx.inputs["Factor"])
_L.new(_cr.outputs[0], _mx.inputs[6])
_mx.inputs[7].default_value = (0.55, 0.57, 0.62, 1)
_L.new(_mx.outputs[2], _b.inputs["Base Color"])

# 바다
WATER = bpy.data.materials.new("water")
WATER.use_nodes = True
_nt = WATER.node_tree
_N, _L = _nt.nodes, _nt.links
_b = next(n for n in _N if n.type == "BSDF_PRINCIPLED")
_b.inputs["Base Color"].default_value = (0.004, 0.022, 0.13, 1)
_b.inputs["Roughness"].default_value = 0.16
_b.inputs["Specular IOR Level"].default_value = 0.45
_nz = _N.new("ShaderNodeTexNoise")
_nz.inputs["Scale"].default_value = 0.35
_nz.inputs["Detail"].default_value = 6
_tcw = _N.new("ShaderNodeTexCoord")
_L.new(_tcw.outputs["Object"], _nz.inputs["Vector"])
_bump = _N.new("ShaderNodeBump")
_bump.inputs["Strength"].default_value = 0.12
_bump.inputs["Distance"].default_value = 0.4
_L.new(_nz.outputs["Fac"], _bump.inputs["Height"])
_L.new(_bump.outputs["Normal"], _b.inputs["Normal"])

# ---------------------------------------------------------------- 메시 만들기
col_main = bpy.data.collections.new("port")
scn.collection.children.link(col_main)


class MB:
    """bmesh 로 상자·기둥·원기둥을 쌓아 물체 하나를 만든다. mi 는 재질 번호."""

    def __init__(self):
        self.bm = bmesh.new()

    def box(self, c, size, mi=0, rot=None):
        hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
        pts = [Vector((x, y, z)) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
        if rot is not None:
            pts = [rot @ p for p in pts]
        c = Vector(c)
        vs = [self.bm.verts.new(c + p) for p in pts]
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            face = self.bm.faces.new([vs[i] for i in f])
            face.material_index = mi
        return vs

    def beam(self, p1, p2, a, b=None, mi=0):
        p1, p2 = Vector(p1), Vector(p2)
        d = p2 - p1
        rot = d.to_track_quat("Z", "Y").to_matrix()
        self.box((p1 + p2) / 2, (a, b or a, d.length), mi, rot)

    def cyl(self, c, r, h, n=20, mi=0, axis="Z", smooth=True, r2=None):
        c = Vector(c)
        r2 = r if r2 is None else r2
        if axis == "Z":
            M = Matrix.Identity(3)
        elif axis == "X":
            M = Euler((0, math.pi / 2, 0)).to_matrix()
        else:
            M = Euler((math.pi / 2, 0, 0)).to_matrix()
        bot, top = [], []
        for i in range(n):
            a = 2 * math.pi * i / n
            bot.append(self.bm.verts.new(c + M @ Vector((r * math.cos(a), r * math.sin(a), -h / 2))))
            top.append(self.bm.verts.new(c + M @ Vector((r2 * math.cos(a), r2 * math.sin(a), h / 2))))
        for i in range(n):
            j = (i + 1) % n
            f = self.bm.faces.new((bot[i], bot[j], top[j], top[i]))
            f.material_index = mi
            f.smooth = smooth
        f = self.bm.faces.new(list(reversed(bot)))
        f.material_index = mi
        f = self.bm.faces.new(top)
        f.material_index = mi

    def sphere(self, c, r, seg=16, rings=10, mi=0, sz=1.0, half=False):
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=rings, radius=r,
                                        matrix=Matrix.Translation(Vector(c)) @ Matrix.Diagonal((1, 1, sz, 1)))
        vs = res["verts"]
        faces = {f for v in vs for f in v.link_faces}
        if half:
            kill = [v for v in vs if v.co.z < c[2] - 1e-4]
            bmesh.ops.delete(self.bm, geom=kill, context="VERTS")
            faces = {f for v in vs if v.is_valid for f in v.link_faces}
        for f in faces:
            f.material_index = mi
            f.smooth = True

    def obj(self, name, mats, bevel=0.0, parent=None, smooth_angle=0.6):
        me = bpy.data.meshes.new(name)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in mats:
            me.materials.append(m)
        if hasattr(me, "use_auto_smooth"):
            me.use_auto_smooth = True
            me.auto_smooth_angle = smooth_angle
        o = bpy.data.objects.new(name, me)
        col_main.objects.link(o)
        if bevel:
            md = o.modifiers.new("bevel", "BEVEL")
            md.width = bevel
            md.segments = 2
            md.limit_method = "ANGLE"
            md.harden_normals = False
        if parent:
            o.parent = parent
        return o


def inst(name, mesh, loc, rot_z=0.0, mat=None, parent=None):
    o = bpy.data.objects.new(name, mesh)
    col_main.objects.link(o)
    o.location = loc
    o.rotation_euler = (0, 0, rot_z)
    if mat is not None:
        o.material_slots[0].link = "OBJECT"
        o.material_slots[0].material = mat
    if parent:
        o.parent = parent
    return o


# ---------------------------------------------------------------- 컨테이너 (골판 벽, 모서리 기둥, 문 잠금대)
CL, CW, CH = 12.19, 2.44, 2.59


def container_mesh(name, L=CL, detail=True):
    mb = MB()
    hw, hh = CW / 2, CH / 2
    mb.box((0, 0, 0), (L - 0.12, CW - 0.14, CH - 0.14))
    # 위·아래 테두리
    for y in (-hw + 0.07, hw - 0.07):
        for z in (-hh + 0.08, hh - 0.07):
            mb.box((0, y, z), (L, 0.14, 0.15 if z < 0 else 0.13))
    for x in (-L / 2 + 0.08, L / 2 - 0.08):
        for z in (-hh + 0.08, hh - 0.07):
            mb.box((x, 0, z), (0.16, CW, 0.14))
        for y in (-hw + 0.08, hw - 0.08):
            mb.box((x, y, 0), (0.16, 0.16, CH))
    if detail:
        n = int((L - 0.4) / 0.62)
        for i in range(n):
            x = -L / 2 + 0.35 + (i + 0.5) * (L - 0.7) / n
            for s in (-1, 1):
                mb.box((x, s * (hw - 0.05), 0), (0.2, 0.07, CH - 0.34))
        n2 = int((L - 0.4) / 0.9)
        for i in range(n2):
            x = -L / 2 + 0.3 + (i + 0.5) * (L - 0.6) / n2
            mb.box((x, 0, hh - 0.05), (0.3, CW - 0.34, 0.05))
        # 문 쪽 잠금대
        for y in (-0.85, -0.35, 0.35, 0.85):
            mb.box((L / 2 - 0.02, y, 0), (0.05, 0.06, CH - 0.3))
        for z in (-0.4, 0.4):
            mb.box((L / 2 - 0.01, 0, z), (0.04, CW - 0.4, 0.05))
    return mb.obj(name, [ORANGE]).data


CONT = container_mesh("container40")
CONT_LO = container_mesh("container40_lo", detail=False)
for o in list(col_main.objects):
    bpy.data.objects.remove(o)
CMATS = [BLUE, BLUE, BLUE2, ORANGE, ORANGE2]


def rand_cmat(bias=0.5):
    return random.choice([BLUE, BLUE2]) if random.random() < bias else random.choice([ORANGE, ORANGE2])


# ---------------------------------------------------------------- 땅·바다
def ground():
    mb = MB()
    # 부두 판 (앞면이 보이는 두꺼운 판)
    mb.box((0, 330, -3.2), (900, 660, 6.4), 0)
    o = mb.obj("land", [GROUND], bevel=0.6)
    # 차선·선
    mb = MB()
    for y in (12.5, 23.5):
        for x in range(-260, 300, 10):
            mb.box((x, y, 0.02), (6, 0.35, 0.04))
    for y in (2.0, 38.5, 41.5, 103, 120):
        mb.box((20, y, 0.02), (560, 0.3, 0.04))
    for x in range(-150, 200, 2):
        pass
    for y in range(44, 100, 6):
        mb.box((38.0, y, 0.02), (0.3, 3.5, 0.04))
    # 장치장 블록 테두리
    for (x0, x1) in ((-185, 30), (52, 225)):
        for (y0, y1) in ((47, 70), (75, 98)):
            for y in (y0, y1):
                mb.box(((x0 + x1) / 2, y, 0.02), (x1 - x0, 0.25, 0.04))
            for x in (x0, x1):
                mb.box((x, (y0 + y1) / 2, 0.02), (0.25, y1 - y0, 0.04))
    mb.obj("lines", [LINE])
    # 크레인 레일
    mb = MB()
    for y in (4, 34):
        mb.box((20, y, 0.03), (560, 0.6, 0.06))
    mb.obj("rails", [RAIL])
    # 방현재·계선주
    mb = MB()
    for x in range(-255, 300, 9):
        mb.box((x, -0.25, -1.4), (2.2, 0.8, 2.4), 0)
    for x in range(-252, 300, 18):
        mb.cyl((x, 1.4, 0.35), 0.35, 0.7, 12, 1)
        mb.sphere((x, 1.4, 0.72), 0.42, 12, 6, 1, 0.5)
    mb.obj("fenders", [DARK, WHITE2])


def water():
    bpy.ops.mesh.primitive_plane_add(size=1)
    o = bpy.context.active_object
    o.name = "sea"
    for c in o.users_collection:
        c.objects.unlink(o)
    col_main.objects.link(o)
    md = o.modifiers.new("ocean", "OCEAN")
    md.geometry_mode = "GENERATE"
    md.resolution = 10
    md.spatial_size = 60
    md.repeat_x = 30
    md.repeat_y = 14
    md.wave_scale = 0.35
    md.choppiness = 0.9
    md.wind_velocity = 9
    md.random_seed = 3
    o.location = (-900, -840, -0.6)
    o.data.materials.append(WATER)
    o.data.polygons.foreach_set("use_smooth", [True] * len(o.data.polygons))
    md.time = 0
    md.keyframe_insert("time", frame=1)
    md.time = END / FPS * 0.9
    md.keyframe_insert("time", frame=END)
    for fc in o.animation_data.action.fcurves:
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"
    return o


# ---------------------------------------------------------------- 안벽 크레인 (STS)
STS_TOP = 30.0


def sts_crane(name, x, hero=False):
    mb = MB()
    O, Wt, Dk, Gl, Bl = 0, 1, 2, 3, 4
    lw = 1.1
    legs = [(x + sx * 8, y) for sx in (-1, 1) for y in (4, 34)]
    for (lx, ly) in legs:
        mb.box((lx, ly, STS_TOP / 2 + 1.2), (lw, lw, STS_TOP - 2.4 + 0.5), O)
        # 바퀴 대차
        mb.box((lx, ly, 1.1), (4.4, 1.8, 1.0), Wt)
        for wx in (-1.5, -0.5, 0.5, 1.5):
            mb.cyl((lx + wx, ly, 0.4), 0.38, 1.6, 14, Dk, "Y")
    for sx in (-1, 1):
        lx = x + sx * 8
        mb.box((lx, 19, 9.5), (lw, 30, 1.1), O)            # 아래 가로보
        mb.box((lx, 19, STS_TOP), (lw * 1.2, 31.2, 1.6), O)  # 위 가로보
        mb.beam((lx, 5, 10.2), (lx, 33, STS_TOP - 0.8), 0.45, mi=O)
        mb.beam((lx, 33, 10.2), (lx, 5, STS_TOP - 0.8), 0.45, mi=O)
    for y in (4, 34):
        mb.box((x, y, STS_TOP + 0.2), (17.2, 1.3, 1.8), O)
    # 붐: 상자형 거더 두 줄 (바다 쪽 -46, 뒤 +48)
    for sx in (-1, 1):
        gx = x + sx * 2.6
        mb.box((gx, 3, STS_TOP + 1.6), (0.7, 84, 0.5), O)    # 아래 현
        mb.box((gx, 3, STS_TOP + 3.4), (0.6, 84, 0.4), O)    # 위 현
        for i in range(28):
            y0 = -39 + i * 3
            mb.beam((gx, y0, STS_TOP + 1.7), (gx, y0 + 3, STS_TOP + 3.3), 0.16, mi=O)
            mb.box((gx, y0, STS_TOP + 2.5), (0.16, 0.16, 1.8), O)
    for i in range(15):
        mb.box((x, -39 + i * 6, STS_TOP + 1.45), (5.6, 0.35, 0.3), O)
    mb.box((x, -39.3, STS_TOP + 2.5), (5.8, 0.8, 2.2), O)
    # A 프레임과 당김줄
    apex = STS_TOP + 17
    for sx in (-1, 1):
        ax = x + sx * 2.6
        mb.beam((x + sx * 6.5, 5, STS_TOP + 0.9), (ax, 18, apex), 0.8, mi=O)
        mb.beam((x + sx * 6.5, 33, STS_TOP + 0.9), (ax, 18, apex), 0.8, mi=O)
        mb.beam((ax, 18, apex), (ax, -14, STS_TOP + 3.5), 0.2, mi=Wt)
        mb.beam((ax, 18, apex), (ax, -38, STS_TOP + 3.5), 0.2, mi=Wt)
        mb.beam((ax, 18, apex), (ax, 44, STS_TOP + 3.5), 0.2, mi=Wt)
    mb.box((x, 18, apex), (6.2, 1.1, 1.1), O)
    # 기계실, 계단, 난간
    mb.box((x, 38, STS_TOP + 5.6), (8, 9, 4.2), Wt)
    mb.box((x, 38, STS_TOP + 7.85), (8.4, 9.4, 0.3), Wt)
    for i in range(3):
        mb.box((x - 4.03, 35 + i * 3, STS_TOP + 5.9), (0.05, 1.6, 1.3), Gl)
    mb.box((x + 2.6, 38, STS_TOP + 8.7), (1.6, 1.6, 1.4), Bl)
    for sx in (-1, 1):
        mb.box((x + sx * 8.7, 19, STS_TOP + 1.3), (0.1, 30, 0.1), Wt)
    o = mb.obj(name, [ORANGE, WHITE2, DARK, GLASS, BLUE], bevel=0.12)

    # 트롤리 + 운전실
    mb = MB()
    mb.box((0, 0, 0), (7.4, 5.6, 1.4), 0)
    mb.box((0, 0, 0.9), (6.4, 4.8, 0.5), 0)
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.cyl((sx * 3.2, sy * 2.0, -0.6), 0.35, 0.5, 10, 2, "X")
    mb.box((-2.4, 1.2, -2.6), (2.6, 3.0, 2.6), 0)
    mb.box((-2.4, -0.3, -2.7), (2.66, 0.06, 1.5), 1)
    mb.box((-1.07, 1.2, -2.7), (0.06, 3.06, 1.5), 1)
    mb.box((-3.73, 1.2, -2.7), (0.06, 3.06, 1.5), 1)
    tro = mb.obj(name + "_trolley", [WHITE2, GLASS, DARK], bevel=0.08)
    tro.location = (x, 18, STS_TOP + 1.2)

    # 스프레더
    mb = MB()
    mb.box((0, 0, 0), (12.2, 0.7, 0.5), 0)
    mb.box((0, 0, 0.3), (3.4, 2.4, 0.6), 1)
    for sx in (-1, 1):
        mb.box((sx * 5.9, 0, -0.05), (0.5, 2.5, 0.4), 0)
        for sy in (-1, 1):
            mb.box((sx * 5.9, sy * 1.1, -0.35), (0.35, 0.35, 0.3), 2)
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.box((sx * 1.4, sy * 1.0, 0.8), (0.3, 0.3, 0.3), 2)
    spr = mb.obj(name + "_spreader", [WHITE2, ORANGE, DARK], bevel=0.05)
    spr.location = (x, 18, 25)

    # 와이어 (길이 1, z 방향으로 늘린다)
    mb = MB()
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.box((sx * 1.4, sy * 1.0, -0.5), (0.09, 0.09, 1.0), 0)
    cab = mb.obj(name + "_cables", [DARK])
    return o, tro, spr, cab


def set_hoist(tro, spr, cab, x, y, sz, f):
    """트롤리 y, 스프레더 높이 sz 를 프레임 f 에 넣는다."""
    tro.location = (x, y, STS_TOP + 1.2)
    tro.keyframe_insert("location", frame=f)
    spr.location = (x, y, sz)
    spr.keyframe_insert("location", frame=f)
    top = STS_TOP + 0.3
    cab.location = (x, y, top)
    cab.scale = (1, 1, max(0.1, top - (sz + 0.9)))
    cab.keyframe_insert("location", frame=f)
    cab.keyframe_insert("scale", frame=f)


# ---------------------------------------------------------------- 장치장 크레인 (RTG)
def rtg_mesh():
    mb = MB()
    Wt, Bl, Dk, Gl, O = 0, 1, 2, 3, 4
    h = 19
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.box((sx * 4.5, sy * 12.2, h / 2), (0.9, 0.9, h), Wt)
            mb.cyl((sx * 4.5 + 0.9, sy * 12.2, 0.75), 0.75, 0.8, 16, Dk, "Y")
            mb.cyl((sx * 4.5 - 0.9, sy * 12.2, 0.75), 0.75, 0.8, 16, Dk, "Y")
        mb.box((sx * 4.5, 0, h + 0.8), (1.2, 26.2, 1.6), Wt)
        mb.box((sx * 4.5, 0, h - 1.2), (0.6, 24.4, 0.4), Wt)
    for sy in (-1, 1):
        mb.box((0, sy * 12.2, 1.6), (11, 1.2, 1.2), Wt)
        mb.box((0, sy * 12.2, h + 0.8), (10, 1.2, 1.6), Wt)
        mb.beam((-4.5, sy * 12.2, 2.5), (4.5, sy * 12.2, h - 0.5), 0.35, mi=Wt)
        mb.beam((4.5, sy * 12.2, 2.5), (-4.5, sy * 12.2, h - 0.5), 0.35, mi=Wt)
    mb.box((0, -12.6, 9), (3.4, 1.8, 3.2), Bl)        # 전기실
    mb.box((0, 4, h + 2.1), (8.6, 4.4, 1.2), Wt)      # 트롤리
    mb.box((-2.6, 5.4, h - 0.6), (2.0, 2.4, 2.2), Wt) # 운전실
    mb.box((-2.6, 4.18, h - 0.6), (2.06, 0.06, 1.3), Gl)
    mb.box((0, 4, 9.5), (11.4, 2.4, 0.45), O)          # 스프레더
    for sx in (-1, 1):
        mb.box((sx * 1.2, 4, h / 2 + 5), (0.07, 0.07, h - 10), Dk)
    return mb.obj("rtg_mesh", [WHITE2, BLUE, DARK, GLASS, ORANGE], bevel=0.08).data


# ---------------------------------------------------------------- 트럭 (트랙터 + 섀시, 원점은 차 가운데)
def truck(name, cab_mat=WHITE2):
    mb = MB()
    Wt, Dk, Gl, Bl, Gr = 0, 1, 2, 3, 4
    # 트레일러 섀시
    mb.box((-1.8, 0, 1.05), (12.6, 0.5, 0.35), Gr)
    for y in (-0.95, 0.95):
        mb.box((-1.8, y, 1.15), (12.6, 0.18, 0.28), Gr)
    for i in range(7):
        mb.box((-7.6 + i * 1.95, 0, 1.25), (0.16, 2.4, 0.16), Gr)
    for ax in (-6.9, -5.6, -4.3):
        for y in (-0.95, 0.95):
            mb.cyl((ax, y, 0.52), 0.52, 0.55, 16, Dk, "Y")
            mb.cyl((ax, y * 1.29, 0.52), 0.25, 0.04, 12, Gr, "Y")
    mb.box((-5.6, 0, 0.95), (4.2, 2.2, 0.3), Gr)
    mb.box((-8.1, 0, 0.75), (0.2, 2.4, 0.6), Dk)
    for y in (-1.0, 1.0):
        mb.box((-8.22, y, 0.75), (0.06, 0.3, 0.16), Bl)
    # 트랙터
    mb.box((5.6, 0, 0.95), (5.6, 1.0, 0.35), Gr)
    for ax in (3.5, 4.8, 7.6):
        for y in (-1.0, 1.0):
            mb.cyl((ax, y, 0.52), 0.52, 0.5, 16, Dk, "Y")
    mb.box((7.2, 0, 2.35), (2.6, 2.5, 2.5), Wt)           # 운전실
    mb.box((7.0, 0, 3.75), (2.2, 2.4, 0.4), Wt)
    mb.box((8.53, 0, 2.75), (0.06, 2.2, 1.05), Gl)        # 앞 유리
    for y in (-1.26, 1.26):
        mb.box((7.75, y, 2.75), (1.0, 0.04, 0.85), Gl)    # 옆 창
        mb.box((7.0, y * 1.0, 1.6), (2.4, 0.06, 0.18), Bl)
    mb.box((8.62, 0, 1.45), (0.18, 2.3, 0.7), Gr)         # 범퍼
    for y in (-0.85, 0.85):
        mb.box((8.72, y, 1.6), (0.04, 0.4, 0.2), Wt)
    mb.box((5.5, 0, 1.55), (1.6, 2.0, 0.5), Gr)           # 연결부
    mb.cyl((5.9, -1.15, 1.45), 0.35, 1.3, 12, Gr, "X")    # 연료통
    mb.cyl((5.8, 1.05, 3.1), 0.1, 2.4, 8, Dk)             # 배기관
    o = mb.obj(name, [cab_mat, DARK, GLASS, BLUE, RAIL], bevel=0.06)
    return o


TRUCK_CONT_LOCAL = Vector((-1.8, 0, 1.2 + CH / 2))


# ---------------------------------------------------------------- 배
def ship(name, L=112, B=20, D=4.5, Hd=5.0, sup_color=WHITE2):
    mb = MB()
    st = 46
    prof_n = 6
    rings = []
    for i in range(st):
        t = i / (st - 1)
        x = -L / 2 + t * L
        if t < 0.06:
            w = B / 2 * (0.86 + 0.14 * t / 0.06)
        elif t > 0.66:
            k = (t - 0.66) / 0.34
            w = B / 2 * max(0.035, math.cos(k * math.pi / 2) ** 0.75)
        else:
            w = B / 2
        keel = -D + (3.2 * ((t - 0.82) / 0.18) ** 1.6 if t > 0.82 else 0) + (1.0 * (1 - t / 0.06) if t < 0.06 else 0)
        deck = Hd + (1.8 * ((t - 0.78) / 0.22) ** 2 if t > 0.78 else 0)
        r = min(2.6, w * 0.9)
        pts = [(-w, deck), (-w, keel + r)]
        for k in range(1, prof_n):
            a = math.pi + (k / prof_n) * math.pi / 2
            pts.append((-w + r + r * math.cos(a), keel + r + r * math.sin(a)))
        pts += [(-w + r, keel), (w - r, keel)]
        for k in range(1, prof_n):
            a = 1.5 * math.pi + (k / prof_n) * math.pi / 2
            pts.append((w - r + r * math.cos(a), keel + r + r * math.sin(a)))
        pts += [(w, keel + r), (w, deck)]
        rings.append([mb.bm.verts.new((x, y, z)) for (y, z) in pts])
    n = len(rings[0])
    for i in range(st - 1):
        a, b = rings[i], rings[i + 1]
        for k in range(n - 1):
            f = mb.bm.faces.new((a[k], b[k], b[k + 1], a[k + 1]))
            f.smooth = True
        mb.bm.faces.new((a[n - 1], b[n - 1], b[0], a[0]))
    mb.bm.faces.new(rings[0])
    mb.bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(mb.bm, faces=mb.bm.faces)
    hull = mb.obj(name, [HULL], smooth_angle=0.75)

    # 갑판 위: 뱃전 난간, 해치 덮개, 선교, 굴뚝, 마스트, 레이더
    mb = MB()
    Wt, Gl, Bl, Dk, Gr = 0, 1, 2, 3, 4
    for i in range(int(L * 0.66 / 2.5)):
        x = -L / 2 + 2 + i * 2.5
        for s in (-1, 1):
            mb.box((x, s * (B / 2 - 0.15), Hd + 0.55), (0.1, 0.1, 1.1), Wt)
    for s in (-1, 1):
        mb.box((-L / 2 + 2 + L * 0.33, s * (B / 2 - 0.15), Hd + 1.1), (L * 0.66, 0.1, 0.1), Wt)
    sx0 = -L / 2 + 9
    # 선교 (뒤쪽)
    mb.box((sx0, 0, Hd + 2.5), (12, B - 2, 5), Wt)
    mb.box((sx0 + 0.5, 0, Hd + 6.5), (10, B - 4, 3), Wt)
    mb.box((sx0 + 1, 0, Hd + 9.6), (8.5, B + 1.5, 3.2), Wt)       # 선교 날개
    mb.box((sx0 + 5.27, 0, Hd + 9.9), (0.08, B + 1.3, 1.5), Gl)   # 선교 창
    for s in (-1, 1):
        mb.box((sx0 + 1, s * (B / 2 + 0.77), Hd + 9.9), (8.3, 0.08, 1.4), Gl)
    mb.box((sx0 + 1, 0, Hd + 11.35), (9, B + 2, 0.3), Wt)
    mb.box((sx0 - 0.5, 0, Hd + 12.6), (5, 6, 2.2), Wt)
    mb.cyl((sx0 - 0.5, 0, Hd + 16), 0.18, 5, 8, Wt)
    mb.box((sx0 - 0.5, 0, Hd + 16.5), (0.2, 3.4, 0.2), Wt)
    mb.sphere((sx0 + 1.4, 1.8, Hd + 14.6), 0.9, 16, 8, Bl)
    mb.cyl((sx0 + 1.4, 1.8, Hd + 13.85), 0.3, 0.5, 10, Wt)
    mb.box((sx0 - 4.6, 0, Hd + 7.8), (3.0, 3.6, 7), Wt)           # 굴뚝
    mb.box((sx0 - 4.6, 0, Hd + 11.6), (3.1, 3.7, 0.8), Bl)
    # 뱃머리 마스트
    mb.cyl((L / 2 - 9, 0, Hd + 4.5), 0.2, 6, 8, Wt)
    mb.box((L / 2 - 9, 0, Hd + 6.8), (0.2, 2.4, 0.2), Wt)
    mb.box((L / 2 - 12, 0, Hd + 0.6), (2, 9, 1.2), Wt)
    # 해치 덮개
    for k in range(7):
        bx = -L / 2 + 22 + k * 12.9
        mb.box((bx, 0, Hd + 0.25), (12.5, B - 3, 0.5), Gr)
    sup = mb.obj(name + "_deck", [sup_color, GLASS, BLUE, DARK, RAIL], bevel=0.07, parent=hull)
    sup_win = None
    return hull


SHIP_BAYS = [-56 + 22 + k * 12.9 for k in range(7)]
SHIP_ROWS = [(-3 + i + 0.5) * 2.5 for i in range(6)]
DECK_Z = 5.0 + 0.5


def load_ship(hull, seed, bias=0.5, skip=None, tiers=(1, 3)):
    rnd = random.Random(seed)
    for bi, bx in enumerate(SHIP_BAYS):
        for ri, ry in enumerate(SHIP_ROWS):
            n = rnd.randint(*tiers)
            for t in range(n):
                if skip and (bi, ri, t) in skip:
                    continue
                m = rand_cmat(bias) if rnd.random() > 0.2 else (BLUE if bias > 0.5 else ORANGE)
                inst("c", CONT, (bx, ry, DECK_Z + CH / 2 + t * CH), 0, m, hull)


# ---------------------------------------------------------------- 건물·나무
def warehouse(x, y, w, d, h, roof=ORANGE, docks_side=-1):
    mb = MB()
    mb.box((x, y, h / 2), (w, d, h), 0)
    # 박공 지붕
    rh = d * 0.18
    o = 0.6
    bm = mb.bm
    v = [bm.verts.new(p) for p in (
        (x - w / 2 - o, y - d / 2 - o, h), (x + w / 2 + o, y - d / 2 - o, h),
        (x + w / 2 + o, y, h + rh), (x - w / 2 - o, y, h + rh),
        (x - w / 2 - o, y + d / 2 + o, h), (x + w / 2 + o, y + d / 2 + o, h))]
    t = 0.35
    vb = [bm.verts.new((p.co.x, p.co.y, p.co.z - t)) for p in v]
    for f in ((0, 1, 2, 3), (3, 2, 5, 4)):
        bm.faces.new([v[i] for i in f]).material_index = 1
        bm.faces.new([vb[i] for i in reversed(f)]).material_index = 1
    for (a, b) in ((0, 1), (1, 2), (2, 5), (5, 4), (4, 3), (3, 0)):
        bm.faces.new((v[a], vb[a], vb[b], v[b])).material_index = 1
    # 박공 벽
    for sx in (-1, 1):
        gv = [bm.verts.new(p) for p in ((x + sx * w / 2, y - d / 2, h), (x + sx * w / 2, y + d / 2, h), (x + sx * w / 2, y, h + rh - 0.1))]
        f = bm.faces.new(gv if sx > 0 else list(reversed(gv)))
        f.material_index = 0
    # 하역문, 차양
    n = max(2, int(w / 9))
    for i in range(n):
        dx = x - w / 2 + (i + 0.5) * w / n
        yy = y + docks_side * (d / 2 + 0.05)
        mb.box((dx, yy, 2.2), (4.0, 0.15, 4.0), 2)
        mb.box((dx, yy + docks_side * 1.6, 4.9), (5.0, 3.2, 0.25), 3)
        mb.box((dx, yy + docks_side * 2.0, 0.6), (3.6, 4.0, 1.2), 3)
    # 지붕 채광창
    for i in range(int(w / 7)):
        dx = x - w / 2 + 3.5 + i * 7
        mb.box((dx, y - d * 0.22, h + rh * 0.55), (2.5, 0.9, 0.3), 4)
    return mb.obj("warehouse", [BLD_W, roof, DARK, WHITE2, GLASS], bevel=0.12)


def office(x, y, w, d, h, mat=BLD_B, roofbox=True):
    mb = MB()
    mb.box((x, y, h / 2), (w, d, h), 0)
    mb.box((x, y, h + 0.3), (w + 0.4, d + 0.4, 0.6), 1)
    if roofbox:
        mb.box((x + w * 0.2, y, h + 1.4), (w * 0.3, d * 0.4, 1.6), 1)
    mb.box((x, y - d / 2 - 1.2, 3.3), (w * 0.5, 2.4, 0.3), 1)
    return mb.obj("office", [mat, WHITE2], bevel=0.1)


def silos(x, y):
    mb = MB()
    for i in range(3):
        for j in range(2):
            cx, cy = x + i * 9, y + j * 9
            mb.cyl((cx, cy, 12), 4, 24, 28, 0)
            mb.sphere((cx, cy, 24), 4, 28, 12, 0, 0.45, half=True)
            for z in (4, 9, 14, 19):
                mb.cyl((cx, cy, z), 4.12, 0.3, 28, 0)
    mb.box((x + 9, y + 4.5, 27.5), (24, 2, 2), 0)
    mb.box((x + 9, y + 4.5, 28.8), (3, 3, 3), 0)
    mb.beam((x + 22, y + 4.5, 27), (x + 40, y + 4.5, 4), 1.6, mi=0)
    return mb.obj("silos", [WHITE2], bevel=0.05)


def trees(points):
    mb = MB()
    for (x, y, s, kind) in points:
        mb.cyl((x, y, 1.2 * s), 0.35 * s, 2.4 * s, 8, 0)
        if kind == "cone":
            for k in range(3):
                mb.cyl((x, y, (2.4 + k * 1.6) * s), (2.4 - k * 0.6) * s, 2.6 * s, 10, random.choice((1, 2)), r2=0.25 * s)
        else:
            mb.sphere((x, y, 4.3 * s), 2.4 * s, 14, 8, random.choice((1, 2, 3)), 1.05)
    return mb.obj("trees", [TRUNK, GREEN, GREEN2, GREEN3])


# ---------------------------------------------------------------- 검사대·게이트
def scanner(x, y):
    mb = MB()
    for sx in (-1, 1):
        mb.box((x + sx * 3.6, y, 4), (1.2, 4.5, 8), 0)
        mb.box((x + sx * 3.05, y, 4), (0.08, 3.8, 6.5), 2)
    mb.box((x, y, 8.6), (9, 5, 1.4), 1)
    mb.box((x + 6.5, y + 4, 1.8), (3.5, 3, 3.6), 0)
    mb.box((x + 4.73, y + 4, 2.2), (0.06, 2.4, 1.2), 3)
    return mb.obj("scanner", [WHITE2, BLUE, BLUE2, GLASS], bevel=0.1)


def gate(x, y):
    mb = MB()
    for gx in (-9, 0, 9):
        mb.box((x + gx, y, 3.5), (0.7, 0.7, 7), 0)
    mb.box((x, y, 7.4), (24, 8, 0.8), 1)
    mb.box((x, y, 7.9), (24.4, 8.4, 0.2), 0)
    for gx in (-4.5, 4.5):
        mb.box((x + gx, y, 0.5), (1.4, 3, 1.0), 0)
    mb.box((x - 13.5, y + 3, 1.6), (3, 3, 3.2), 0)
    mb.box((x - 11.97, y + 3, 2.0), (0.06, 2.4, 1.2), 2)
    base = mb.obj("gate", [WHITE2, BLUE, GLASS], bevel=0.08)
    arms = []
    for (px, ln) in ((x - 4.0, 8.0),):
        mb = MB()
        for i in range(8):
            mb.box((ln * (i + 0.5) / 8, 0, 0), (ln / 8, 0.18, 0.18), i % 2)
        a = mb.obj("barrier", [ORANGE, WHITE2])
        a.location = (px, y - 1.6, 1.1)
        arms.append(a)
    return base, arms[0]


# ---------------------------------------------------------------- 경로
def ease(t):
    t = min(1, max(0, t))
    return t * t * (3 - 2 * t)


def ease_in(t):
    t = min(1, max(0, t))
    return t * t


def lerp(a, b, t):
    return a + (b - a) * t


class Path:
    """꺾이는 길을 둥근 모서리로 이은 점 목록. at(s) 는 (위치, 방향각)."""

    def __init__(self, pts, radius=8, closed=False, step=0.5):
        P = [Vector((p[0], p[1], 0)) for p in pts]
        out = []
        m = len(P)
        rng = range(m) if closed else range(1, m - 1)
        if not closed:
            out.append(P[0])
        for i in rng:
            a, b, c = P[i - 1], P[i], P[(i + 1) % m]
            d1 = (b - a).normalized()
            d2 = (c - b).normalized()
            p0 = b - d1 * radius
            p2 = b + d2 * radius
            for k in range(9):
                t = k / 8
                out.append((1 - t) ** 2 * p0 + 2 * (1 - t) * t * b + t * t * p2)
        if closed:
            out.append(out[0])
        else:
            out.append(P[-1])
        self.pts = out
        self.cum = [0.0]
        for i in range(1, len(out)):
            self.cum.append(self.cum[-1] + (out[i] - out[i - 1]).length)
        self.length = self.cum[-1]

    def at(self, s):
        s = min(max(s, 0), self.length)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        t = 0 if seg == 0 else (s - self.cum[lo]) / seg
        p = self.pts[lo].lerp(self.pts[hi], t)
        d = self.pts[hi] - self.pts[lo]
        return p, math.atan2(d.y, d.x)


def key_obj(o, f, loc, rz=None):
    o.location = loc
    o.keyframe_insert("location", frame=f)
    if rz is not None:
        o.rotation_euler = (0, 0, rz)
        o.keyframe_insert("rotation_euler", frame=f)


def linear_all(o):
    if o.animation_data and o.animation_data.action:
        for fc in o.animation_data.action.fcurves:
            for k in fc.keyframe_points:
                k.interpolation = "LINEAR"


def unwrap_angles(o):
    """방향각이 ±π 를 넘을 때 크게 도는 것을 막는다."""
    if not (o.animation_data and o.animation_data.action):
        return
    for fc in o.animation_data.action.fcurves:
        if fc.data_path == "rotation_euler" and fc.array_index == 2:
            prev = None
            for k in fc.keyframe_points:
                v = k.co[1]
                if prev is not None:
                    while v - prev > math.pi:
                        v -= 2 * math.pi
                    while v - prev < -math.pi:
                        v += 2 * math.pi
                k.co[1] = v
                prev = v


# ================================================================= 장면 쌓기
ground()
sea = water()

HERO_X = 20.0
HERO_Y_TRUCK = 18.0
cranes = {}
for nm, cx in (("sts_hero", HERO_X), ("sts_b", 62), ("sts_c", -38), ("sts_d", -112), ("sts_e", -156)):
    cranes[nm] = sts_crane(nm, cx)

# 배: 뱃머리가 -x 쪽 (yaw π). 영웅 컨테이너는 3번 베이, 2번 줄, 맨 위
HB, HR = 3, 2
HERO_TIER = 2
SHIP_Y = -12.2
ship_x_dock = HERO_X + SHIP_BAYS[HB]          # yaw π 라 로컬 x 가 뒤집힌다
hero_ship = ship("ship_hero")
load_ship(hero_ship, 11, 0.45, skip={(HB, HR, t) for t in range(0, 6) if t >= HERO_TIER}, tiers=(1, 3))
# 영웅 줄은 아래 두 단을 채워 둔다
for t in range(HERO_TIER):
    inst("c", CONT, (SHIP_BAYS[HB], SHIP_ROWS[HR], DECK_Z + CH / 2 + t * CH), 0, BLUE, hero_ship)
hero_c = inst("hero_container", CONT, (0, 0, 0), 0, ORANGE)

ship2 = ship("ship_b")
ship2.location = (-130, SHIP_Y - 0.4, 0)
ship2.rotation_euler = (0, 0, math.pi)
load_ship(ship2, 23, 0.75, tiers=(2, 4))
ship3 = ship("ship_far")
ship3.location = (260, -150, 0)
ship3.rotation_euler = (0, 0, math.pi * 0.92)
load_ship(ship3, 31, 0.4, tiers=(2, 4))

# 장치장
RTG = rtg_mesh()
for o in [o for o in col_main.objects if o.name.startswith("rtg_mesh")]:
    bpy.data.objects.remove(o)
yard_rnd = random.Random(5)
rtgs = []
for (x0, x1) in ((-185, 30), (52, 225)):
    for (y0, y1) in ((47, 70), (75, 98)):
        rows = 6
        nb = int((x1 - x0 - 4) / 12.9)
        for b in range(nb):
            bx = x0 + 2 + 6.45 + b * 12.9
            if yard_rnd.random() < 0.12:
                continue
            for r in range(rows):
                ry = y0 + 2.2 + r * 2.6
                n = yard_rnd.choice((1, 2, 2, 3, 3, 3, 4, 4))
                for t in range(n):
                    far = abs(bx - 40) > 90
                    inst("y", CONT_LO if far else CONT, (bx, ry, CH / 2 + t * CH), 0,
                         rand_cmat(0.55 if bx < 40 else 0.4))
        ro = inst("rtg", RTG, (lerp(x0, x1, yard_rnd.uniform(0.25, 0.75)), (y0 + y1) / 2 + 2.5, 0))
        rtgs.append((ro, x0 + 12, x1 - 12, yard_rnd.uniform(0, 1)))

# 검사대 · 게이트 · 건물
SCAN_Y = 110.0
GATE_Y = 128.0
scanner(40, SCAN_Y)
gate_base, barrier = gate(42, GATE_Y)
scan_plane = MB()
scan_plane.box((0, 0, 0), (6.0, 0.25, 7.5), 0)
scan_o = scan_plane.obj("scan_light", [SCAN])
scan_o.location = (40, SCAN_Y, 4)

bld = []
for i, x in enumerate((70, 112, 154, 196)):
    warehouse(x, 150, 34, 22, 9, ORANGE if i % 3 != 2 else BLUE, -1)
    warehouse(x, 184, 34, 22, 9, ORANGE if i % 2 == 0 else BLUE, -1)
for i, x in enumerate((-12, -50, -88)):
    warehouse(x, 152, 30, 20, 8, BLUE, -1)
office(4, 186, 22, 14, 8, BLD_B)
office(-26, 188, 16, 14, 12, BLD_B)
office(14, 210, 9, 9, 30, BLD_TOWER)
office(-6, 214, 9, 9, 22, BLD_TOWER)
office(-62, 194, 30, 14, 7, BLD_O)
office(240, 150, 16, 26, 7, BLD_B)
office(-135, 128, 26, 10, 6, BLD_B)
silos(-200, 140)
silos(-235, 175)
for (x, y) in ((86, 126), (128, 126), (170, 126)):
    for k in range(3):
        mb = MB()
        mb.box((x + k * 4, y, 1.0), (3, 6, 2.0), 0)
        mb.obj("hut", [BLD_B])

tp = []
tr = random.Random(9)
for i in range(150):
    x = tr.uniform(-190, -80)
    y = tr.uniform(175, 260)
    if x > -150 and y < 205:
        continue
    tp.append((x, y, tr.uniform(0.8, 1.25), "round" if tr.random() < 0.7 else "cone"))
for i in range(40):
    tp.append((tr.uniform(60, 220), tr.uniform(205, 240), tr.uniform(0.8, 1.2), "round"))
for x in range(52, 236, 9):
    tp.append((x, 132, 0.75, "round"))
for y in range(140, 250, 9):
    tp.append((31, y, 0.75, "round"))
    tp.append((49, y, 0.75, "round"))
trees(tp)

# 도시 쪽 땅 칸 (공원 잔디 판)
mb = MB()
mb.box((-135, 220, 0.08), (110, 90, 0.16), 0)
mb.obj("park", [principled("lawn", (0.36, 0.52, 0.30), 0.85)], bevel=0.05)

# ================================================================= 애니메이션
# --- 배 입항 (1 → 96)
ARRIVE = 96


def ship_matrix(f):
    t = ease((f - 1) / (ARRIVE - 1))
    tt = 1 - (1 - min(1, max(0, (f - 1) / (ARRIVE - 1)))) ** 2.2
    x = lerp(ship_x_dock + 230, ship_x_dock, tt)
    y = lerp(SHIP_Y - 60, SHIP_Y, ease(min(1, (f - 1) / (ARRIVE - 10))))
    yaw = math.pi + 0.16 * (1 - ease(min(1, (f - 1) / (ARRIVE - 4))))
    bob = 0.12 * math.sin(2 * math.pi * f / (LOOP / 2))
    roll = 0.006 * math.sin(2 * math.pi * f / (LOOP / 3))
    return Matrix.Translation((x, y, bob)) @ Euler((roll, 0, yaw)).to_matrix().to_4x4()


for f in range(1, END + 1):
    M = ship_matrix(f)
    loc, rot, _ = M.decompose()
    e = rot.to_euler()
    hero_ship.location = loc
    hero_ship.rotation_euler = e
    hero_ship.keyframe_insert("location", frame=f)
    hero_ship.keyframe_insert("rotation_euler", frame=f)
linear_all(hero_ship)

# --- 크레인 하역 (96 → 264)
tro, spr, cab = cranes["sts_hero"][1:]
HIGH = 20.0
hero_local = Vector((SHIP_BAYS[HB], SHIP_ROWS[HR], DECK_Z + CH / 2 + HERO_TIER * CH))
TRUCK_START = Vector((HERO_X - TRUCK_CONT_LOCAL.x, HERO_Y_TRUCK, 0))
truck_cont_z = TRUCK_CONT_LOCAL.z
hold_off = 0.25 + 0.3 + CH / 2   # 스프레더 원점 → 컨테이너 가운데


def hoist(f):
    """(트롤리 y, 스프레더 z, 컨테이너 상태)"""
    Mf = ship_matrix(min(f, 400))
    hc = Mf @ hero_local
    pick_y, pick_top = hc.y, hc.z + hold_off
    put_top = truck_cont_z + hold_off
    seg = [
        (96, 132, "move", HERO_Y_TRUCK, pick_y, HIGH, HIGH),
        (132, 152, "down", pick_y, pick_y, HIGH, pick_top),
        (152, 160, "hold", pick_y, pick_y, pick_top, pick_top),
        (160, 182, "lift", pick_y, pick_y, pick_top, HIGH),
        (182, 216, "back", pick_y, HERO_Y_TRUCK, HIGH, HIGH),
        (216, 238, "lower", HERO_Y_TRUCK, HERO_Y_TRUCK, HIGH, put_top),
        (238, 246, "rel", HERO_Y_TRUCK, HERO_Y_TRUCK, put_top, put_top),
        (246, 264, "up", HERO_Y_TRUCK, HERO_Y_TRUCK, put_top, HIGH),
    ]
    if f < 96:
        return HERO_Y_TRUCK, HIGH, "ship"
    for (a, b, st, y0, y1, z0, z1) in seg:
        if a <= f < b:
            t = ease((f - a) / (b - a))
            state = "ship" if st in ("move", "down") else ("carry" if st in ("hold", "lift", "back", "lower") else "truck")
            return lerp(y0, y1, t), lerp(z0, z1, t), state
    return HERO_Y_TRUCK, HIGH, "truck"


# 트럭 경로: 안벽 → 오른쪽 → 북쪽 길 → 검사대 → 게이트 → 도시
hero_truck = truck("truck_hero")
hpath = Path([(TRUCK_START.x, HERO_Y_TRUCK), (40, HERO_Y_TRUCK), (40, 400)], radius=9)
S_SCAN = (hpath.length - (400 - SCAN_Y))
T_GO, T_SCAN, T_SCAN_END, T_FAR = 262, 372, 408, INTRO
S_END = S_SCAN + 120


def truck_s(f):
    if f < T_GO:
        return 0.0
    if f < T_SCAN:
        return S_SCAN * ease((f - T_GO) / (T_SCAN - T_GO))
    if f < T_SCAN_END:
        return S_SCAN
    t = (f - T_SCAN_END) / (T_FAR - T_SCAN_END)
    # 출발은 천천히, 뒤로는 일정한 속도
    return S_SCAN + (S_END - S_SCAN) * (t * t if t < 0.3 else (0.09 + (t - 0.3) * (0.91 / 0.7)))


for f in range(1, END + 1):
    ty, sz, state = hoist(f)
    set_hoist(tro, spr, cab, HERO_X, ty, sz, f)
    s = truck_s(f)
    p, hd = hpath.at(s)
    hidden = f > INTRO
    key_obj(hero_truck, f, (p.x, p.y, -50 if hidden else 0), hd)
    Mt = Matrix.Translation(p) @ Euler((0, 0, hd)).to_matrix().to_4x4()
    if state == "ship":
        M = ship_matrix(f)
        loc = M @ hero_local
        rz = ship_matrix(f).to_euler().z
    elif state == "carry":
        loc = Vector((HERO_X, ty, sz - hold_off))
        rz = math.pi
    else:
        loc = Mt @ TRUCK_CONT_LOCAL
        rz = hd
    if hidden:
        loc = Vector((0, 0, -60))
    key_obj(hero_c, f, loc, rz)
for o in (tro, spr, cab, hero_truck, hero_c):
    unwrap_angles(o)
    linear_all(o)

# 검사 빛
for f, a, s in ((T_SCAN - 2, 0.0, 0.0), (T_SCAN + 4, 0.55, 6.0), (T_SCAN_END - 6, 0.55, 6.0), (T_SCAN_END, 0.0, 0.0)):
    b = next(n for n in SCAN.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Alpha"].default_value = a
    b.inputs["Alpha"].keyframe_insert("default_value", frame=f)
    b.inputs["Emission Strength"].default_value = s
    b.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)
for f in range(T_SCAN, T_SCAN_END + 1, 2):
    t = (f - T_SCAN) / (T_SCAN_END - T_SCAN)
    key_obj(scan_o, f, (40, SCAN_Y - 8 + 16 * ((math.sin(t * math.pi * 3 - math.pi / 2) + 1) / 2), 4))

# 차단기
for f, ang in ((1, 0), (T_SCAN_END + 6, 0), (T_SCAN_END + 22, 1.35), (T_SCAN_END + 70, 1.35), (T_SCAN_END + 90, 0)):
    barrier.rotation_euler = (0, -ang, 0)
    barrier.keyframe_insert("rotation_euler", frame=f)

# --- 배경 움직임 (LOOP 주기로 되풀이)
for nm in ("sts_b", "sts_c", "sts_d", "sts_e"):
    o, t2, s2, c2 = cranes[nm]
    x = o.name and {"sts_b": 62, "sts_c": -38, "sts_d": -112, "sts_e": -156}[nm]
    ph = {"sts_b": 0.0, "sts_c": 0.35, "sts_d": 0.6, "sts_e": 0.15}[nm]
    for f in range(1, END + 1, 2):
        u = (f / LOOP + ph) % 1.0
        # 바다 쪽으로 가서 내리고, 올려서 땅 쪽으로 (한 주기)
        yv = 18 - 30 * (0.5 - 0.5 * math.cos(2 * math.pi * u))
        zv = HIGH - 7 * max(0, math.sin(2 * math.pi * (u * 2))) ** 3
        set_hoist(t2, s2, c2, x, yv, zv, f)
    for ob in (t2, s2, c2):
        linear_all(ob)

for (ro, xa, xb, ph) in rtgs:
    for f in range(1, END + 1, 4):
        u = (f / LOOP + ph) % 1.0
        key_obj(ro, f, (lerp(xa, xb, 0.5 - 0.5 * math.cos(2 * math.pi * u)), ro.location.y, 0))
    linear_all(ro)

# 장치장 순환 트럭 (같은 간격으로 돌아 한 주기 뒤 제자리)
loops = [
    Path([(-192, 40), (28, 40), (28, 102), (-192, 102)], radius=7, closed=True),
    Path([(48, 40), (230, 40), (230, 102), (48, 102)], radius=7, closed=True),
]
for li, pth in enumerate(loops):
    N = 3
    for k in range(N):
        tk = truck("truck_bg", WHITE2)
        c = inst("c", CONT, TRUCK_CONT_LOCAL, 0, rand_cmat(0.5), tk)
        for f in range(1, END + 1):
            s = ((f / LOOP) * (pth.length / N) + k * pth.length / N + li * 40) % pth.length
            p, hd = pth.at(s)
            key_obj(tk, f, (p.x, p.y, 0), hd)
        unwrap_angles(tk)
        linear_all(tk)

# ================================================================= 카메라·빛·렌더 설정
cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 38
cam_d.clip_start = 1
cam_d.clip_end = 4000
cam = bpy.data.objects.new("cam", cam_d)
col_main.objects.link(cam)
scn.camera = cam


def truck_pos(f):
    p, _ = hpath.at(truck_s(f))
    return Vector((p.x, p.y, 3))


WIDE = (Vector((38, 34, 0)), 330, -36, 34, 38)
KEYS = [
    (1, WIDE),
    (60, (Vector((90, -24, 4)), 240, -30, 27, 38)),
    (110, (Vector((24, -6, 8)), 130, -28, 22, 40)),
    (160, (Vector((20, -8, 17)), 112, -24, 19, 40)),
    (215, (Vector((20, 4, 16)), 106, -38, 22, 40)),
    (262, (Vector((24, 16, 4)), 80, -52, 32, 40)),
    (320, ("truck", 75, -62, 26, 40)),
    (380, (Vector((40, SCAN_Y, 4)), 75, -55, 26, 40)),
    (430, ("truck", 90, -45, 30, 40)),
    (470, ("truck", 130, -40, 32, 40)),
    (INTRO, WIDE),
]


def key_pose(i):
    f, (tg, d, az, el, lens) = KEYS[i]
    if isinstance(tg, str):
        tg = truck_pos(f)
    return f, [tg.x, tg.y, tg.z, d, az, el, lens]


def cr(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


poses = {}
kp = [key_pose(i) for i in range(len(KEYS))]
for i in range(len(kp) - 1):
    f0, a = kp[i]
    f1, b = kp[i + 1]
    p0 = kp[max(0, i - 1)][1]
    p3 = kp[min(len(kp) - 1, i + 2)][1]
    for f in range(f0, f1 + 1):
        t = (f - f0) / (f1 - f0)
        if i == 0:
            t = ease_in(t) * 0.5 + t * 0.5
        if i == len(kp) - 2:
            t = 1 - (1 - t) ** 2
        poses[f] = [cr(p0[j], a[j], b[j], p3[j], t) for j in range(7)]
# 부드럽게 (이동 평균)
fr = sorted(poses)
sm = {}
for f in fr:
    acc = [0.0] * 7
    wsum = 0
    for d in range(-6, 7):
        g = min(max(f + d, fr[0]), fr[-1])
        w = 1 - abs(d) / 7
        acc = [acc[j] + poses[g][j] * w for j in range(7)]
        wsum += w
    sm[f] = [v / wsum for v in acc]
for f in range(INTRO - 8, INTRO + 1):
    t = ease((f - (INTRO - 8)) / 8)
    sm[f] = [lerp(sm[f][j], kp[-1][1][j], t) for j in range(7)]


def place_cam(vals, f):
    tx, ty, tz, d, az, el, lens = vals
    az, el = math.radians(az), math.radians(el)
    tgt = Vector((tx, ty, tz))
    loc = tgt + d * Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = loc
    cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
    cam_d.lens = lens
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)
    cam_d.keyframe_insert("lens", frame=f)


for f in range(1, INTRO + 1):
    place_cam(sm[f], f)
place_cam(kp[-1][1], END)
linear_all(cam)
if cam_d.animation_data:
    for fc in cam_d.animation_data.action.fcurves:
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"
# 오일러 이어 붙이기
for fc in cam.animation_data.action.fcurves:
    if fc.data_path == "rotation_euler":
        prev = None
        for k in fc.keyframe_points:
            v = k.co[1]
            if prev is not None:
                while v - prev > math.pi:
                    v -= 2 * math.pi
                while v - prev < -math.pi:
                    v += 2 * math.pi
            k.co[1] = v
            prev = v

# 빛
sun_d = bpy.data.lights.new("sun", "SUN")
sun_d.energy = 4.2
sun_d.angle = math.radians(9)
sun_d.color = (1.0, 0.97, 0.93)
if hasattr(sun_d, "shadow_cascade_max_distance"):
    sun_d.shadow_cascade_max_distance = 700
    sun_d.shadow_cascade_count = 4
    sun_d.shadow_cascade_fade = 0.15
    sun_d.use_contact_shadow = True
sun = bpy.data.objects.new("sun", sun_d)
col_main.objects.link(sun)
sun.rotation_euler = Euler((math.radians(48), 0, math.radians(-128)))

world = bpy.data.worlds.new("world")
scn.world = world
world.use_nodes = True
wn = world.node_tree.nodes
bg = next(n for n in wn if n.type == "BACKGROUND")
grad = wn.new("ShaderNodeTexGradient")
tcw = wn.new("ShaderNodeTexCoord")
sepw = wn.new("ShaderNodeSeparateXYZ")
ramp = wn.new("ShaderNodeValToRGB")
world.node_tree.links.new(tcw.outputs["Generated"], sepw.inputs[0])
world.node_tree.links.new(sepw.outputs[2], ramp.inputs[0])
ramp.color_ramp.elements[0].position = 0.45
ramp.color_ramp.elements[0].color = (0.62, 0.68, 0.78, 1)
ramp.color_ramp.elements[1].position = 0.75
ramp.color_ramp.elements[1].color = (0.42, 0.55, 0.80, 1)
world.node_tree.links.new(ramp.outputs[0], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 1.0

# 렌더
r = scn.render
r.engine = "BLENDER_EEVEE"
r.resolution_x, r.resolution_y = W, H
r.resolution_percentage = 100
r.film_transparent = False
ee = scn.eevee
ee.taa_render_samples = 20
ee.use_gtao = True
ee.gtao_distance = 5
ee.gtao_factor = 1.25
ee.use_ssr = True
ee.use_ssr_refraction = False
ee.ssr_quality = 0.5
ee.use_soft_shadows = True
ee.shadow_cascade_size = "2048"
ee.shadow_cube_size = "1024"
ee.use_bloom = False
ee.use_volumetric_lights = False
ee.use_motion_blur = False
ee.motion_blur_shutter = 0.35
vs = scn.view_settings
try:
    vs.view_transform = "AgX"
    try:
        vs.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
except TypeError:
    vs.view_transform = "Filmic"
    vs.look = "Medium High Contrast"
vs.exposure = 0.55
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGB"

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "dash_port.blend"))
print("[build] 저장", os.path.join(HERE, "dash_port.blend"))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if argv and argv[0] == "still":
    frames = [int(a) for a in argv[1:]] or [1, 100, 170, 230, 330, 390, 450, INTRO]
    os.makedirs(os.path.join(HERE, "stills"), exist_ok=True)
    for f in frames:
        scn.frame_set(f)
        r.filepath = os.path.join(HERE, "stills", f"f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        print("[build] 그림", f)
