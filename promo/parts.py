#!/usr/bin/env python3
"""Draws the pieces of the film that the page already draws, and measures the
mark the film builds its cube from.

    .venv/bin/python promo/parts.py

The two logos and the smear each one leaves belong to site/hero.py. This imports
its drawings and its smear rather than carrying copies, so a change there
reaches the page and the film alike once both scripts have run. The film needs
the logos apart where the page has them as one picture, because each slides
onto a face of the cube on its own.

The mark in site/logo.png is a cube, which the film builds in 3D. This measures
the pose that cube takes to look like the mark, and lays the mark's top face,
with its letters, flat for the cube to carry. Both come from the picture, so a
changed mark reaches the cube once this has run.

It writes into promo/assets/ and needs what hero.py needs, numpy, Pillow,
fontTools and rsvg-convert, and SciPy for fitting the cube.
"""

import json
import pathlib
import sys

import numpy
from PIL import Image
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

HERE = pathlib.Path(__file__).parent
SITE = HERE.parent / "site"
ASSETS = HERE / "assets"

sys.path.insert(0, str(SITE))
import hero

#: The corners of the mark's cube that its picture shows, by where each one
#: lies on the cube: x to the right, y up and z towards the viewer, with the
#: letters on the top face. The inner corner is the one all three faces share.
MARK_CORNERS = {
    "inner": (1, 1, 1),
    "top-left": (-1, 1, 1),
    "top": (-1, 1, -1),
    "right": (1, 1, -1),
    "bottom-right": (1, -1, -1),
    "bottom": (1, -1, 1),
    "left": (-1, -1, 1),
}

#: Where the six corners round the outside of the mark lie, as the direction
#: in which each one reaches furthest.
OUTER_DIRECTIONS = {"left": (-1, 0), "top": (0, -1), "right": (1, 0), "bottom": (0, 1), "top-left": (-1, -1), "bottom-right": (1, 1)}

#: The three fugues between the mark's faces start at these corners and meet
#: at the inner one.
FUGUE_STARTS = ("top-left", "right", "bottom")

#: How far a transparent pixel may lie from ink on either side and still be
#: part of a fugue, in the picture's pixels.
FUGUE_REACH = 12

#: How far from its corner a fugue is looked for, as a share of the mark's
#: height: less than its shortest fugue is long.
FUGUE_SEARCH = 0.2

#: How far either side of a fugue's line its pixels are taken from, in the
#: picture's pixels, and how often the line is fitted again to them.
FUGUE_HALF_WIDTH = 10
FUGUE_PASSES = 4

#: How wide the top face's picture is drawn, in pixels.
TOP_FACE_SIZE = 640


def write_logo(picture, towards, name):
    """The logo as the page draws it, and its smear beside it.

    The smear comes back at half the size it was worked out at and reaches one
    logo width past the logo, which is hero.STREAK's reach. The composition
    lines the sharp logo up with the end of its trail from that reach, which
    write_geometry passes on.
    """
    picture.save(ASSETS / f"{name}.png", optimize=True)
    trail, _ = hero.smear(picture, towards)
    trail.save(ASSETS / f"{name}-trail.png", optimize=True)


def fugue_pixels(opaque):
    """The transparent pixels inside the mark, which are its fugues: those
    with ink on both sides of them within FUGUE_REACH pixels, across or down.

    Returns:
        Their x and y in the picture's pixels, one row each.
    """
    height, width = opaque.shape
    padded = numpy.pad(opaque, FUGUE_REACH)

    def ink_within(shifts):
        found = numpy.zeros_like(opaque)
        for down, across in shifts:
            found |= padded[FUGUE_REACH + down:FUGUE_REACH + down + height, FUGUE_REACH + across:FUGUE_REACH + across + width]
        return found

    steps = range(1, FUGUE_REACH + 1)
    across = ink_within([(0, -step) for step in steps]) & ink_within([(0, step) for step in steps])
    down = ink_within([(-step, 0) for step in steps]) & ink_within([(step, 0) for step in steps])
    rows, columns = numpy.nonzero(~opaque & (across | down))
    return numpy.stack([columns, rows], axis=1).astype(float)


def fugue_line(gaps, corner, search):
    """The fugue that starts at a corner, as a point on it and its direction.

    Seen from the corner, every pixel of its own fugue lies at one angle, so
    the most common angle finds the fugue. Only the pixels within the search
    radius vote, because the shortest fugue has fewer pixels than the far end
    of a long one. The line through the pixels near that ray is then fitted
    again a few times, each time to the pixels near the line before, so it
    settles on the fugue's middle along its whole length.

    Args:
        gaps: fugue_pixels' result.
        corner: Where the fugue starts, in the picture's pixels.
        search: How far from the corner a pixel may lie and still vote.
    """
    offsets = gaps - corner
    nearby = offsets[numpy.linalg.norm(offsets, axis=1) < search]
    angles = numpy.arctan2(nearby[:, 1], nearby[:, 0])
    counts, edges = numpy.histogram(angles, bins=720, range=(-numpy.pi, numpy.pi))
    peak = (edges[counts.argmax()] + edges[counts.argmax() + 1]) / 2
    middle, direction = corner, numpy.array([numpy.cos(peak), numpy.sin(peak)])
    for _ in range(FUGUE_PASSES):
        normal = numpy.array([-direction[1], direction[0]])
        near = gaps[numpy.abs((gaps - middle) @ normal) < FUGUE_HALF_WIDTH]
        middle = near.mean(axis=0)
        _, _, axes = numpy.linalg.svd(near - middle)
        direction = axes[0]
    return middle, direction


def intersection(first, second):
    """Where two lines, each a point and a direction, cross."""
    (point, direction), (other_point, other_direction) = first, second
    along, _ = numpy.linalg.solve(numpy.array([direction, -other_direction]).T, other_point - point)
    return point + along * direction


def mark_corners(picture):
    """Where the mark's cube has its seven visible corners, in the picture's
    pixels, named as MARK_CORNERS names them.

    The six round the outside are the silhouette's furthest points in their
    directions. The inner corner is where the three fugues between the faces
    meet.
    """
    opaque = numpy.asarray(picture.getchannel("A")) > 128
    rows, columns = numpy.nonzero(opaque)
    points = numpy.stack([columns, rows], axis=1).astype(float)
    corners = {}
    for name, direction in OUTER_DIRECTIONS.items():
        reach = points @ numpy.array(direction, float)
        corners[name] = points[reach >= reach.max() - 2].mean(axis=0)
    gaps = fugue_pixels(opaque)
    lines = [fugue_line(gaps, corners[name], FUGUE_SEARCH * picture.height) for name in FUGUE_STARTS]
    meetings = [intersection(lines[first], lines[second]) for first, second in ((0, 1), (1, 2), (2, 0))]
    corners["inner"] = numpy.mean(meetings, axis=0)
    return corners


def mark_pose(corners):
    """The pose of a cube that, seen in perspective, puts its corners closest
    to where the mark has them.

    The mark is drawn rather than projected, so no cube fits it exactly, and
    the best one lies within a few percent of its height. The film shows the
    mark's own picture wherever it holds still and turns this cube everywhere
    else.

    Returns:
        The rotations of three nested elements in degrees, outermost first,
        as CSS turns them: about z, about x and about y. The half edge in the
        picture's pixels, the camera's distance in half edges, the picture
        pixel the cube's middle lands on, and how far each corner misses, in
        pixels.
    """
    names = list(MARK_CORNERS)
    cube = numpy.array([MARK_CORNERS[name] for name in names], float)
    seen = numpy.array([corners[name] for name in names])

    def project(parameters):
        rotation = Rotation.from_rotvec(parameters[:3]).as_matrix()
        across, down, half_edge, distance = parameters[3:]
        turned = cube @ rotation.T
        depth = distance / (distance - turned[:, 2])
        return numpy.stack([across + half_edge * turned[:, 0] * depth, down - half_edge * turned[:, 1] * depth], axis=1)

    # The fit has more than one valley, so it starts from many places and
    # keeps the deepest. The generator is seeded, so it keeps the same one.
    generator = numpy.random.default_rng(1)
    size = numpy.ptp(seen, axis=0).max()
    fits = [
        least_squares(
            lambda parameters: (project(parameters) - seen).ravel(),
            numpy.concatenate([generator.normal(0, 1.2, 3), seen.mean(axis=0), [size / 3, generator.uniform(4, 30)]]),
            bounds=([-10, -10, -10, -numpy.inf, -numpy.inf, 1, 2.5], [10, 10, 10, numpy.inf, numpy.inf, numpy.inf, 500]))
        for _ in range(40)
    ]
    best = min(fits, key=lambda fit: fit.cost)
    across, down, half_edge, distance = best.x[3:]

    # The fit's axes have y up; CSS has it down, so the rotation is turned
    # into CSS's axes before it is split into three turns.
    flip = numpy.diag([1.0, -1.0, 1.0])
    rotation = flip @ Rotation.from_rotvec(best.x[:3]).as_matrix() @ flip
    about_z, about_x, about_y = Rotation.from_matrix(rotation).as_euler("ZXY", degrees=True)
    misses = numpy.linalg.norm(project(best.x) - seen, axis=1)
    return {
        "rotationZ": round(float(about_z), 3),
        "rotationX": round(float(about_x), 3),
        "rotationY": round(float(about_y), 3),
        "halfEdge": round(float(half_edge), 3),
        "distance": round(float(distance), 3),
        "center": [round(float(across), 2), round(float(down), 2)],
        "misses": dict(zip(names, (round(float(miss), 1) for miss in misses), strict=True)),
    }


def write_top_face(picture, corners):
    """The mark's top face, with its letters, as a flat square for the film's
    cube to carry.

    The square's top left is the face's far corner, its top right the right
    corner, its bottom right the inner corner and its bottom left the top-left
    corner, which is how the cube's top face lies on it in CSS: its own down
    runs towards the front face and its own right towards the right face.
    """
    quad = [*corners["top"], *corners["top-left"], *corners["inner"], *corners["right"]]
    face = picture.transform((TOP_FACE_SIZE, TOP_FACE_SIZE), Image.Transform.QUAD, [float(value) for value in quad], Image.Resampling.BICUBIC)
    face.save(ASSETS / "cube-top.png", optimize=True)


def write_geometry(pose):
    """What the stage needs to know about the drawings: the size of each logo
    and of the mark, how far a smear reaches, and the mark's pose, in the mark
    picture's pixels, which the film scales to the size it shows the mark at.
    The stage reads all of it from here rather than measuring a second time.

    Args:
        pose: mark_pose's result, without the misses it reports.
    """
    geometry = {
        "pi": dict(zip(("width", "height"), Image.open(ASSETS / "pi.png").size, strict=True)),
        "cube": dict(zip(("width", "height"), Image.open(ASSETS / "cube.png").size, strict=True)),
        "streak": {"reach": hero.STREAK["reach"], "opacity": hero.STREAK["opacity"]},
        "mark": dict(zip(("width", "height"), Image.open(SITE / "logo.png").size, strict=True)),
        "markPose": pose,
    }
    (ASSETS / "parts.js").write_text(
        "// Written by promo/parts.py. Change that and run it again.\n"
        f"window.PARTS = {json.dumps(geometry)};\n")
    print(f"parts.js: {geometry}")


def main():
    ASSETS.mkdir(exist_ok=True)
    write_logo(hero.pi_picture(), "left", "pi")
    write_logo(hero.cube_picture(), "right", "cube")
    mark = Image.open(SITE / "logo.png").convert("RGBA")
    corners = mark_corners(mark)
    write_top_face(mark, corners)
    pose = mark_pose(corners)
    print(f"The cube misses the mark's corners by {pose.pop('misses')} pixels.")
    write_geometry(pose)


if __name__ == "__main__":
    main()
