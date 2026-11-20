"""Tripo 등에서 받은 무거운 GLB(150만 삼각형, 4K 텍스처)를 장면에 넣기 좋게 가볍게 만든다.

blender -b --factory-startup --python blender/prep_asset.py -- <입력.glb> <출력.blend> <이름> <목표 삼각형 수> [텍스처 크기]
예) ... -- blender/assets/incoming/worker.glb blender/assets/worker_lite.blend worker 150000 2048

결과 .blend 안에는 GEO-<이름>_tripo 오브젝트 하나와 MAT-<이름>_tripo 재질이 있다.
메시는 Blender 좌표(Z 위)로 회전을 적용했고, 바닥 중심이 원점이 되게 옮겼다. 크기는 원본 그대로다.
"""
import sys
import time

import bpy

argv = sys.argv[sys.argv.index('--') + 1:]
src, dst, name, target = argv[0], argv[1], argv[2], int(argv[3])
tex = int(argv[4]) if len(argv) > 4 else 2048
t0 = time.time()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects:
    o.select_set(o in meshes)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
for o in list(bpy.data.objects):
    if o != obj:
        bpy.data.objects.remove(o)
obj.parent = None
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
tris0 = sum(len(p.vertices) - 2 for p in obj.data.polygons)

ratio = min(1.0, target / max(tris0, 1))
if ratio < 1.0:
    md = obj.modifiers.new('DEC', 'DECIMATE')
    md.ratio = ratio
    md.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=md.name)
tris1 = sum(len(p.vertices) - 2 for p in obj.data.polygons)

# 바닥 중심을 원점으로
xs = [v.co.x for v in obj.data.vertices]
ys = [v.co.y for v in obj.data.vertices]
zs = [v.co.z for v in obj.data.vertices]
cx, cy, z0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)
for v in obj.data.vertices:
    v.co.x -= cx
    v.co.y -= cy
    v.co.z -= z0
for p in obj.data.polygons:
    p.use_smooth = True

obj.name = f'GEO-{name}_tripo'
obj.data.name = f'ME-{name}_tripo'
for i, m in enumerate(obj.data.materials):
    m.name = f'MAT-{name}_tripo' + (f'.{i}' if i else '')

for img in bpy.data.images:
    if img.size[0] > tex or img.size[1] > tex:
        img.scale(tex, tex)
    img.name = f'IMG-{name}_' + img.name
    img.pack()

dims = obj.dimensions
bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True)
print(f'PREP {name}: tris {tris0} -> {tris1}, dims {dims.x:.3f} x {dims.y:.3f} x {dims.z:.3f}, {time.time() - t0:.0f}s')
