"""A local two-actor blocking stage. All views project the same world coordinates."""

import base64
import math
import struct
import zlib

from . import production

PRESETS = {"wide": (0, 7.8), "left": (18, 3.2), "right": (-18, 3.2),
           "over_left": (18, 3.2), "over_right": (-18, 3.2)}
LIMITS = {"angle": (-55, 55), "distance": (1.8, 10), "height": (-0.8, 1.2), "offset": (-1, 1)}
POSITIONS = ((-1.55, 0.1), (1.55, -0.1))


def layout(project, shot):
    cast = {a["id"]: a for a in project["assets"] if a["kind"] == "character"}
    people = [cast[k] for k in shot["asset_ids"] if k in cast]
    if not 1 <= len(people) <= 2:
        raise ValueError("请为镜头绑定一至两名角色")
    if len(people) == 1:
        return [dict(id=people[0]["id"], name=people[0]["name"], x=0, z=0)]
    # Project asset order stays stable when two shots list the same actors in reverse.
    ids = {a["id"] for a in people}
    return [
        dict(id=a["id"], name=a["name"], x=x, z=z)
        for a, (x, z) in zip((a for a in cast.values() if a["id"] in ids), POSITIONS)
    ]


def preset(name):
    angle, distance = PRESETS[name]
    return dict(view=name, angle=angle, distance=distance)


def current_camera(shot, actors):
    reference = shot.get("composition_reference", {})
    if reference.get("actors") == actors:
        return reference["camera"]
    take = production.selected_visual_take(shot) or {}
    if take.get("blocking", {}).get("actors") == actors:
        return take["blocking"]["camera"]
    speaker = next(
        (line.get("speaker_asset_id") for line in shot.get("lines") or []), None
    )
    if len(actors) == 1:
        return preset("left")
    if shot.get("framing") in ("大远景", "远景", "全景") or speaker not in {
        a["id"] for a in actors
    }:
        return preset("wide")
    return preset("left" if speaker == actors[0]["id"] else "right")


def choices(actors):
    return ('wide', 'left') if len(actors)==1 else tuple(PRESETS)


def focus_slot(view):
    return 1 if view in ('right','over_right') else 0


def visible_slots(view, count=2):
    if view in ('wide', 'over_left', 'over_right'):
        return tuple(range(count))
    return (focus_slot(view),)


def composition_spec(view, framing, portrait):
    return dict(version=2, view=view, framing=framing or '中景', portrait=portrait)


def render(camera, actors, portrait=False, framing='中景'):
    if not isinstance(camera, dict) or camera.get("view") not in choices(actors):
        raise ValueError("请选择有效机位")
    if set(camera) - {'view', 'positions', 'gaze', *LIMITS}:
        raise ValueError('机位包含未知参数')
    for key, (lo, hi) in LIMITS.items():
        value = camera.get(key, 0) if key in ('height','offset') else camera.get(key)
        if type(value) not in (int, float) or not lo <= value <= hi:
            raise ValueError("机位参数超出范围")
    positions = camera.get('positions', {})
    gaze = camera.get('gaze', {})
    ids = {actor.get('id') for actor in actors}
    if not isinstance(positions,dict) or not set(positions)<=ids or any(
            not isinstance(pos, dict) or set(pos)!={'x','z'} or any(
                type(n) not in (int,float) or not -3<=n<=3 for n in pos.values()) for pos in positions.values()):
        raise ValueError('走位超出预演范围')
    if not isinstance(gaze,dict) or not set(gaze)<=ids or any(v not in ('left','right') for v in gaze.values()):
        raise ValueError('请选择有效的画内视线方向')
    actors = [dict(actor, **positions.get(actor.get('id'), {})) for actor in actors]
    w, h = (540, 960) if portrait else (960, 540)
    rows = [
        bytearray(bytes((31 + y * 32 // h, 49 + y * 36 // h, 68 + y * 36 // h)) * w)
        for y in range(h)
    ]
    wide = camera["view"] == "wide"
    slot = focus_slot(camera['view'])
    target = (sum(actor['x'] for actor in actors)/len(actors) if wide else actors[slot]['x']) + camera.get('offset',0)
    aim_y = 1.0 if wide else 1.46
    zoom = 1.0
    center_x = w / 2
    if not wide:
        zoom, aim_y = {"中近景": (1.25, 1.47), "近景": (1.5, 1.53),
                       "特写": (2, 1.62), "大特写": (2.5, 1.68)}.get(framing, (1, 1.36))
        center_x = w * (0.42 if slot==0 else 0.58)
    aim_y += camera.get("height",0)
    yaw = math.radians(camera["angle"])
    co, si = math.cos(yaw), math.sin(yaw)

    def transform(p):
        x, y, z = p
        x -= target
        return x * co + z * si, y - aim_y, camera["distance"] + x * si - z * co

    def polygon(points, color):
        vertices = [transform(p) for p in points]
        clipped = []
        for a, b in zip(vertices[-1:] + vertices[:-1], vertices):
            if (a[2] > 0.2) != (b[2] > 0.2):
                t = (0.2 - a[2]) / (b[2] - a[2])
                clipped.append(
                    (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0.2)
                )
            if b[2] > 0.2:
                clipped.append(b)
        if len(clipped) < 3:
            return
        scale = w * 0.98 if wide else min(w, h * 1.78) * 1.25 * zoom
        pts = [(center_x + scale * x / z, h / 2 - scale * y / z) for x, y, z in clipped]
        edges = list(zip(pts[-1:] + pts[:-1], pts))
        rgb = bytes.fromhex(color)
        for y in range(
            max(0, math.floor(min(y for _, y in pts))),
            min(h, math.ceil(max(y for _, y in pts))),
        ):
            scan = y + 0.5
            hits = sorted(
                a + (scan - b) * (c - a) / (d - b)
                for (a, b), (c, d) in edges
                if min(b, d) <= scan < max(b, d)
            )
            for i in range(0, len(hits) - 1, 2):
                l = max(0, math.ceil(hits[i]))
                r = min(w, math.ceil(hits[i + 1]))
                if r > l:
                    rows[y][3 * l : 3 * r] = rgb * (r - l)

    # A neutral floor conveys depth without supplying an unintended story location.
    polygon([(-40, 0, -14), (40, 0, -14), (40, 0, 15), (-40, 0, 15)], "425462")
    for n in sorted(
        (range(len(actors)) if wide else (slot,)), key=lambda i: -transform((actors[i]["x"], 1, actors[i]["z"]))[2]
    ):
        x, z = actors[n]["x"], actors[n]["z"]
        sign = 1 if gaze.get(actors[n].get("id"), "right" if n==0 else "left")=="right" else -1

        def shape(points, color, x=x, z=z, sign=sign):
            polygon([(x + sign * dx, y, z + dz) for dx, y, dz in points], color)

        for dx in (-0.12, 0.10):
            shape(
                [
                    (dx - 0.06, 0.04, 0),
                    (dx + 0.06, 0.04, 0),
                    (dx + 0.09, 0.86, 0),
                    (dx - 0.08, 0.86, 0),
                ],
                "20313c",
            )
        shape(
            [
                (-0.24, 0.69, 0),
                (0.23, 0.70, 0),
                (0.20, 1.40, 0),
                (0.08, 1.51, 0),
                (-0.12, 1.49, 0),
                (-0.23, 1.37, 0),
            ],
            "548999" if n == 0 else "bb7952",
        )
        shape(
            [
                (-0.24, 0.69, 0),
                (-0.14, 0.74, 0.12),
                (-0.11, 1.43, 0.08),
                (-0.22, 1.37, 0),
            ],
            "3c677b" if n == 0 else "8d5746",
        )
        shape(
            [
                (-0.09, 1.44, 0.01),
                (0.09, 1.46, 0.02),
                (0.12, 1.56, 0.03),
                (0.18, 1.61, 0.02),
                (0.14, 1.65, 0.02),
                (0.13, 1.76, 0),
                (-0.08, 1.8, 0),
                (-0.16, 1.69, 0),
            ],
            "e0af8d",
        )
        shape(
            [
                (-0.14, 1.57, 0),
                (-0.19, 1.69, 0),
                (-0.13, 1.81, 0),
                (0.05, 1.85, 0),
                (0.15, 1.77, 0),
                (0.12, 1.72, 0.03),
                (-0.02, 1.74, 0.04),
                (-0.07, 1.62, 0.04),
            ],
            "252f39",
        )
        shape(
            [
                (0.09, 1.68, 0.04),
                (0.13, 1.68, 0.04),
                (0.13, 1.69, 0.04),
                (0.09, 1.69, 0.04),
            ],
            "443c40",
        )

    if camera['view'].startswith('over_'):
        # The foreground silhouette is a framing guide. The focus actor remains on their mark.
        for y in range(h // 2, h):
            length = int(w * min(.28, .09 + (y - h / 2) / h * .55))
            edge = 0 if slot==1 else w-length
            rows[y][edge*3:(edge+length)*3] = bytes.fromhex('202e39') * length

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = b"".join(b"\0" + r for r in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels, 3))
        + chunk(b"IEND", b"")
    )


def preview(image):
    return "data:image/png;base64," + base64.b64encode(image).decode("ascii")
