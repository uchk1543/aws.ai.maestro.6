# 발표 영상용 부산항 장면 (실사 질감).
# 대시보드 장면(../dash_port/build_scene.py)의 모델·움직임·카메라를 그대로 쓰고,
# 재질만 Poly Haven(CC0) 실사 질감과 HDRI 하늘로 바꾼다. 해상도 1920×1080.
# 실행: blender -b -P build_real.py -- [still 프레임...]
import bpy, math, os, sys
from mathutils import Euler

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "dash_port", "build_scene.py")
PH = os.path.join(HERE, "..", "assets", "polyhaven")

# 1) 대시보드 장면을 그대로 만든다 (스틸 렌더 인자는 넘기지 않는다)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
saved_argv = sys.argv
sys.argv = [a for a in sys.argv if a != "--"][:1]
g = {"__file__": BASE, "__name__": "base"}
exec(compile(open(BASE, encoding="utf-8").read(), BASE, "exec"), g)
sys.argv = saved_argv
scn = bpy.context.scene


# 2) 실사 재질
def tex(folder, kind):
    name = f"{folder}_{ {'diff': 'diff', 'nor': 'nor_gl', 'rough': 'rough'}[kind] }_2k.jpg"
    path = os.path.join(PH, folder, name)
    img = bpy.data.images.load(path, check_existing=True)
    if kind != "diff":
        img.colorspace_settings.name = "Non-Color"
    return img


def pbr(mat, folder, tint=None, scale=0.25, rough_mul=1.0, metal=0.0, tint_mix=0.85, normal=0.6):
    """mat 의 노드를 실사 질감으로 바꾼다. 좌표는 물체 좌표 상자 투영 (UV 없이), tint 는 바탕색을 곱한다."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial")
    b = N.new("ShaderNodeBsdfPrincipled")
    L.new(b.outputs[0], out.inputs[0])
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    L.new(tc.outputs["Object"], mp.inputs[0])

    def image(kind):
        n = N.new("ShaderNodeTexImage")
        n.image = tex(folder, kind)
        n.projection = "BOX"
        n.projection_blend = 0.25
        L.new(mp.outputs[0], n.inputs[0])
        return n

    d = image("diff")
    col = d.outputs["Color"]
    if tint:
        mix = N.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = tint_mix
        L.new(col, mix.inputs[6])
        mix.inputs[7].default_value = (*tint, 1)
        col = mix.outputs[2]
    L.new(col, b.inputs["Base Color"])
    r = image("rough")
    rm = N.new("ShaderNodeMath")
    rm.operation = "MULTIPLY"
    rm.inputs[1].default_value = rough_mul
    L.new(r.outputs["Color"], rm.inputs[0])
    L.new(rm.outputs[0], b.inputs["Roughness"])
    nm = N.new("ShaderNodeNormalMap")
    nm.inputs["Strength"].default_value = normal
    L.new(image("nor").outputs["Color"], nm.inputs["Color"])
    L.new(nm.outputs[0], b.inputs["Normal"])
    b.inputs["Metallic"].default_value = metal
    return mat


def paint(mat, color, rough=0.42, grunge=0.18, metal=0.25, scale=0.3):
    """도장한 금속: 단색 + 미세한 얼룩(녹 질감을 옅게 곱함) + 거칠기 변화."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial")
    b = N.new("ShaderNodeBsdfPrincipled")
    L.new(b.outputs[0], out.inputs[0])
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    L.new(tc.outputs["Object"], mp.inputs[0])
    dirt = N.new("ShaderNodeTexImage")
    dirt.image = tex("rusty_metal_02", "diff")
    dirt.projection = "BOX"
    dirt.projection_blend = 0.3
    L.new(mp.outputs[0], dirt.inputs[0])
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = grunge
    mix.inputs[6].default_value = (*color, 1)
    L.new(dirt.outputs["Color"], mix.inputs[7])
    L.new(mix.outputs[2], b.inputs["Base Color"])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 6
    L.new(mp.outputs[0], nz.inputs["Vector"])
    mr = N.new("ShaderNodeMapRange")
    L.new(nz.outputs["Fac"], mr.inputs[0])
    mr.inputs[3].default_value = rough - 0.12
    mr.inputs[4].default_value = rough + 0.12
    L.new(mr.outputs[0], b.inputs["Roughness"])
    b.inputs["Metallic"].default_value = metal
    return mat


M = bpy.data.materials
# 바닥: 닳은 콘크리트
pbr(M["ground"], "concrete_floor_worn_001", tint=(0.92, 0.9, 0.86), scale=0.09, normal=0.5)
# 차선: 흰 페인트 (살짝 닳음)
pbr(M["line"], "concrete_floor_worn_001", tint=(1.6, 1.58, 1.5), scale=0.3, tint_mix=1.0, normal=0.2)
# 컨테이너: 골판 강판에 도장색 (무채색 쪽으로 낮춘 실제 컨테이너 색)
pbr(M["blue"], "corrugated_iron_02", tint=(0.10, 0.22, 0.45), scale=0.35, metal=0.3, normal=0.7)
pbr(M["blue2"], "corrugated_iron_02", tint=(0.16, 0.30, 0.34), scale=0.35, metal=0.3, normal=0.7)
pbr(M["orange"], "corrugated_iron_02", tint=(0.62, 0.16, 0.06), scale=0.35, metal=0.3, normal=0.7)
pbr(M["orange2"], "corrugated_iron_02", tint=(0.70, 0.42, 0.10), scale=0.35, metal=0.3, normal=0.7)
# 크레인 도장: 붉은 주황 도장 금속 (조금 녹)
CRANE = paint(bpy.data.materials.new("crane_paint"), (0.62, 0.14, 0.04), rough=0.4, grunge=0.22)
# 흰 도장 금속 (기계실·트럭·건물 장식)
paint(M["white"], (0.72, 0.72, 0.70), rough=0.45, grunge=0.15)
paint(M["white2"], (0.80, 0.80, 0.78), rough=0.4, grunge=0.12)
# 창고 지붕: 골판 강판
ROOF = pbr(bpy.data.materials.new("roof_metal"), "corrugated_iron_02", tint=(0.62, 0.64, 0.66), scale=0.3, metal=0.5)
ROOF_B = pbr(bpy.data.materials.new("roof_blue"), "corrugated_iron_02", tint=(0.22, 0.32, 0.48), scale=0.3, metal=0.5)
RUST = pbr(bpy.data.materials.new("rust"), "rusty_metal_02", scale=0.4)

for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    mats = o.data.materials
    if o.name.startswith("sts_") and not any(k in o.name for k in ("_trolley", "_spreader", "_cables")):
        mats[0] = CRANE  # 크레인 몸체 (주황 칸)
    elif o.name.startswith("warehouse") and len(mats) > 1:
        mats[1] = ROOF if mats[1].name == "orange" else ROOF_B
    elif o.name.startswith("barrier"):
        mats[0] = CRANE

# 건물: 벽 콘크리트색, 창은 어두운 유리, 지붕은 회색
for name in ("bld_blue", "bld_orange", "bld_white", "bld_tower", "ship_win"):
    nt = M[name].node_tree
    mixes = [n for n in nt.nodes if n.type == "MIX"]
    mixes[0].inputs[6].default_value = (0.62, 0.62, 0.6, 1)
    mixes[0].inputs[7].default_value = (0.03, 0.045, 0.06, 1)
    mixes[1].inputs[7].default_value = {"bld_blue": (0.18, 0.26, 0.38, 1), "bld_orange": (0.42, 0.20, 0.12, 1)}.get(name, (0.42, 0.42, 0.42, 1))

# 선체: 짙은 남색 몸, 흰 줄, 붉은 갈색 갑판
hull = M["hull"].node_tree
ramp = next(n for n in hull.nodes if n.type == "VALTORGB").color_ramp
ramp.elements[0].color = (0.015, 0.03, 0.07, 1)
ramp.elements[1].color = (0.75, 0.75, 0.75, 1)
ramp.elements[2].color = (0.015, 0.03, 0.07, 1)
next(n for n in hull.nodes if n.type == "MIX").inputs[7].default_value = (0.20, 0.07, 0.05, 1)
next(n for n in hull.nodes if n.type == "BSDF_PRINCIPLED").inputs["Roughness"].default_value = 0.5

# 바다: 짙은 청록, 반사
wb = next(n for n in M["water"].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
wb.inputs["Base Color"].default_value = (0.006, 0.025, 0.03, 1)
wb.inputs["Roughness"].default_value = 0.04
sea = bpy.data.objects["sea"].modifiers["ocean"]
sea.wave_scale = 0.6
sea.choppiness = 1.3

# 하늘: HDRI + 햇빛
world = scn.world
wn = world.node_tree.nodes
wn.clear()
env = wn.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(os.path.join(PH, "kloofendal_28d_misty_puresky", "kloofendal_28d_misty_puresky_2k.hdr"))
mp = wn.new("ShaderNodeMapping")
tcw = wn.new("ShaderNodeTexCoord")
world.node_tree.links.new(tcw.outputs["Generated"], mp.inputs[0])
mp.inputs["Rotation"].default_value = (0, 0, math.radians(120))
world.node_tree.links.new(mp.outputs[0], env.inputs[0])
bgn = wn.new("ShaderNodeBackground")
bgn.inputs["Strength"].default_value = 0.65
outw = wn.new("ShaderNodeOutputWorld")
world.node_tree.links.new(env.outputs[0], bgn.inputs[0])
world.node_tree.links.new(bgn.outputs[0], outw.inputs[0])
sun = bpy.data.objects["sun"]
sun.data.energy = 5.5
sun.data.color = (1.0, 0.95, 0.88)
sun.data.angle = math.radians(2.5)
sun.rotation_euler = Euler((math.radians(52), 0, math.radians(-140)))

r = scn.render
r.resolution_x, r.resolution_y = 1920, 1080
ee = scn.eevee
ee.taa_render_samples = 16  # 32 와 눈으로 차이 없음, 두 배 이상 빠름
ee.gtao_distance = 3
ee.gtao_factor = 1.0
ee.use_bloom = True
ee.bloom_intensity = 0.02
ee.use_motion_blur = False  # 카메라가 느려 차이 없음
vs = scn.view_settings
vs.exposure = 0.15
try:
    vs.look = "AgX - Medium High Contrast"
except TypeError:
    pass

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "real_port.blend"))
print("[real] 저장")

if argv and argv[0] == "still":
    os.makedirs(os.path.join(HERE, "stills"), exist_ok=True)
    for f in [int(a) for a in argv[1:]] or [1, 160, 230, 390, 450, 576]:
        scn.frame_set(f)
        r.filepath = os.path.join(HERE, "stills", f"f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        print("[real] 그림", f)
