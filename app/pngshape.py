"""Decide whether a base64 PNG shows a rectangle, a triangle or a circle.

Pure Python on purpose. The challenge's own qna page warns that on a small free
instance it is *imports* that exhaust memory, and the statement's images are
100x100 — Pillow and numpy would cost far more than they buy. What is here is a
PNG decoder and a convex-hull classifier, about 15 ms on a 100x100 image.

The classifier works off the convex hull, so a hollow outline of a shape reads
the same as a filled one.
"""
import base64
import binascii
import math
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_BASE64 = 8 * 1024 * 1024   # 8 MB of text
MAX_DIMENSION = 4096
MAX_PIXELS = 2_000_000         # a decompression bomb is the hostile input here
MAX_RAW = 96 * 1024 * 1024     # ceiling on the decompressed scanlines
ANALYSIS_SIZE = 400            # anything larger is subsampled before analysis
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

SHAPES = ("rectangle", "triangle", "circle")


class ImageError(ValueError):
    """We could not get a shape out of what we were handed."""


# --- base64 ---------------------------------------------------------------


def decode_base64(text: str) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise ImageError("no image given")
    if len(text) > MAX_BASE64:
        raise ImageError("image is too large")
    body = text.strip()
    if body.startswith("data:"):
        _, _, body = body.partition(",")
    body = "".join(body.split())
    body = body.replace("-", "+").replace("_", "/")  # url-safe alphabet
    body += "=" * (-len(body) % 4)
    try:
        return base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("not valid base64") from None


# --- PNG ------------------------------------------------------------------


def decode_png(data: bytes):
    """-> (width, height, rgba) with rgba a flat list of (r, g, b, a) tuples.

    Subsamples on a single stride in both axes so the aspect ratio survives.
    """
    if not data.startswith(SIGNATURE):
        raise ImageError("not a PNG image")

    at, header, palette, transparency, idat = len(SIGNATURE), None, b"", b"", []
    while at + 8 <= len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        tag = data[at + 4 : at + 8]
        body = data[at + 8 : at + 8 + length]
        if len(body) < length:
            raise ImageError("truncated PNG")
        if tag == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif tag == b"PLTE":
            palette = body
        elif tag == b"tRNS":
            transparency = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        at += 12 + length

    if header is None:
        raise ImageError("PNG has no header")
    width, height, depth, colour, compression, filtering, interlace = header
    if not width or not height:
        raise ImageError("image is empty")
    if width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise ImageError("image is too large")
    if colour not in CHANNELS or compression != 0 or filtering != 0:
        raise ImageError("unsupported PNG format")
    if interlace:
        raise ImageError("interlaced PNGs are not supported")
    if depth not in (1, 2, 4, 8, 16) or (depth < 8 and colour not in (0, 3)):
        raise ImageError("unsupported PNG bit depth")
    if not idat:
        raise ImageError("PNG has no image data")

    try:
        raw = zlib.decompressobj().decompress(b"".join(idat), MAX_RAW)
    except zlib.error:
        raise ImageError("PNG image data is corrupt") from None

    channels = CHANNELS[colour]
    bits = channels * depth
    row_bytes = (width * bits + 7) // 8
    step = max(1, bits // 8)  # filters work on whole bytes, minimum one
    if len(raw) < height * (row_bytes + 1):
        raise ImageError("truncated PNG image data")

    stride = max(1, math.ceil(max(width, height) / ANALYSIS_SIZE))
    xs = list(range(0, width, stride))

    pixels = []
    previous = bytearray(row_bytes)
    offset = 0
    for y in range(height):
        kind = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + row_bytes])
        offset += row_bytes + 1
        _unfilter(kind, line, previous, step)
        if y % stride == 0:
            pixels.extend(_row_rgba(line, xs, depth, colour, palette, transparency))
        previous = line

    return len(xs), len(range(0, height, stride)), pixels


def _unfilter(kind, line, previous, step) -> None:
    if kind == 0:
        return
    if kind == 1:
        for i in range(step, len(line)):
            line[i] = (line[i] + line[i - step]) & 0xFF
    elif kind == 2:
        for i in range(len(line)):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif kind == 3:
        for i in range(len(line)):
            left = line[i - step] if i >= step else 0
            line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif kind == 4:
        for i in range(len(line)):
            left = line[i - step] if i >= step else 0
            up = previous[i]
            corner = previous[i - step] if i >= step else 0
            estimate = left + up - corner
            da, db, dc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
            best = left if (da <= db and da <= dc) else (up if db <= dc else corner)
            line[i] = (line[i] + best) & 0xFF
    else:
        raise ImageError("unsupported PNG filter")


def _samples(line, index, count, depth):
    if depth == 8:
        start = index * count
        return line[start : start + count]
    if depth == 16:
        start = index * count * 2
        return line[start : start + count * 2 : 2]  # high byte is enough
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    shift = (per_byte - 1 - index % per_byte) * depth
    return [(line[index // per_byte] >> shift) & mask]


def _row_rgba(line, xs, depth, colour, palette, transparency):
    scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
    out = []
    for x in xs:
        values = _samples(line, x, CHANNELS[colour], depth)
        if colour == 0:
            grey = values[0] * scale
            out.append((grey, grey, grey, 255))
        elif colour == 2:
            out.append((values[0], values[1], values[2], 255))
        elif colour == 3:
            index = values[0]
            base = index * 3
            if base + 3 > len(palette):
                raise ImageError("PNG palette is incomplete")
            alpha = transparency[index] if index < len(transparency) else 255
            out.append((palette[base], palette[base + 1], palette[base + 2], alpha))
        elif colour == 4:
            grey = values[0]
            out.append((grey, grey, grey, values[1]))
        else:
            out.append((values[0], values[1], values[2], values[3]))
    return out


# --- foreground -----------------------------------------------------------


def _background(width, height, pixels):
    """The page the shape is drawn on: the commonest colour around the border."""
    counts = {}
    for x in range(width):
        for y in (0, height - 1):
            counts[pixels[y * width + x]] = counts.get(pixels[y * width + x], 0) + 1
    for y in range(height):
        for x in (0, width - 1):
            counts[pixels[y * width + x]] = counts.get(pixels[y * width + x], 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _mask(width, height, pixels):
    paper = _background(width, height, pixels)
    transparent_paper = paper[3] < 128

    def distance(pixel):
        if transparent_paper:
            return pixel[3]
        if pixel[3] < 128:
            return 0  # transparent pixels are page, not ink
        return max(abs(pixel[i] - paper[i]) for i in range(3))

    distances = [distance(pixel) for pixel in pixels]
    furthest = max(distances)
    if furthest < 24:
        raise ImageError("no shape found in the image")
    # halfway to the furthest colour, so antialiased edges fall on one side
    threshold = max(24, furthest * 0.5)
    return [d >= threshold for d in distances]


def _largest_component(width, height, mask):
    """Ignore stray marks: only the biggest blob of ink is the shape."""
    seen = [False] * len(mask)
    best = []
    for start in range(len(mask)):
        if not mask[start] or seen[start]:
            continue
        seen[start] = True
        stack, component = [start], []
        while stack:
            here = stack.pop()
            component.append(here)
            y, x = divmod(here, width)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        neighbour = ny * width + nx
                        if mask[neighbour] and not seen[neighbour]:
                            seen[neighbour] = True
                            stack.append(neighbour)
        if len(component) > len(best):
            best = component
    if not best:
        raise ImageError("no shape found in the image")
    return best


def _outline(width, component):
    """The first and last ink in every row and in every column.

    Every other pixel sits between two of these on its own row, so the convex
    hull of this handful of points is the convex hull of the whole shape — and
    taking columns as well means a wide flat edge is sampled as densely as a
    tall one, which is what keeps the roundness measure honest.
    """
    rows, columns = {}, {}
    for index in component:
        y, x = divmod(index, width)
        low, high = rows.get(y, (x, x))
        rows[y] = (min(low, x), max(high, x))
        top, bottom = columns.get(x, (y, y))
        columns[x] = (min(top, y), max(bottom, y))
    points = set()
    for y, (low, high) in rows.items():
        points.add((low, y))
        points.add((high, y))
    for x, (top, bottom) in columns.items():
        points.add((x, top))
        points.add((x, bottom))
    return sorted(points)


# --- geometry -------------------------------------------------------------


def _hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _simplify(polygon, epsilon):
    """Ramer-Douglas-Peucker round a closed polygon -> its real corners."""
    if len(polygon) < 3:
        return polygon
    # start from the two points furthest apart so no true corner is an endpoint
    start = max(range(len(polygon)), key=lambda i: _distance(polygon[i], polygon[0]))
    rotated = polygon[start:] + polygon[:start]
    end = max(range(len(rotated)), key=lambda i: _distance(rotated[i], rotated[0]))
    return _rdp(rotated[: end + 1], epsilon)[:-1] + _rdp(rotated[end:] + [rotated[0]], epsilon)[:-1]


def _rdp(points, epsilon):
    if len(points) < 3:
        return list(points)
    first, last = points[0], points[-1]
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        offset = _line_distance(points[i], first, last)
        if offset > worst:
            worst, index = offset, i
    if worst <= epsilon:
        return [first, last]
    return _rdp(points[: index + 1], epsilon)[:-1] + _rdp(points[index:], epsilon)


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _line_distance(point, start, end):
    if start == end:
        return _distance(point, start)
    (x0, y0), (x1, y1), (x2, y2) = point, start, end
    return abs((x2 - x1) * (y1 - y0) - (x1 - x0) * (y2 - y1)) / _distance(start, end)


def _on_borders(point, width, height, tolerance=4.0):
    x, y = point
    sides = set()
    if x <= tolerance:
        sides.add("left")
    if x >= width - 1 - tolerance:
        sides.add("right")
    if y <= tolerance:
        sides.add("top")
    if y >= height - 1 - tolerance:
        sides.add("bottom")
    return sides


def _beyond(point, side, width, height, margin=1.0):
    x, y = point
    return {
        "left": x < -margin,
        "right": x > width - 1 + margin,
        "top": y < -margin,
        "bottom": y > height - 1 + margin,
    }[side]


def _meet(a, b, c, d):
    """Where line ab crosses line cd, or None if they never do."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = a, b, c, d
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-9:
        return None
    first = x1 * y2 - y1 * x2
    second = x3 * y4 - y3 * x4
    return (
        (first * (x3 - x4) - (x1 - x2) * second) / denominator,
        (first * (y3 - y4) - (y1 - y2) * second) / denominator,
    )


def _unclip(polygon, width, height):
    """Put back a corner the image frame cut off.

    A shape drawn larger than its canvas arrives as a polygon with a flat edge
    lying along the border — a clipped triangle reads as a pentagon. Where the
    two edges either side of such an edge meet *outside* the image, that meeting
    point is the corner that was cut off. Where they meet inside it (a triangle
    whose base happens to sit on the border) nothing was clipped and we leave it
    alone.
    """
    for _ in range(4):  # at most one corner per side
        if len(polygon) <= 3:
            break
        for i in range(len(polygon)):
            rotated = polygon[i:] + polygon[:i]
            a, b = rotated[0], rotated[1]
            shared = _on_borders(a, width, height) & _on_borders(b, width, height)
            # a clipped-off corner leaves a short edge; a long one is a real side
            if not shared or not 2 <= _distance(a, b) <= 0.4 * _perimeter(polygon):
                continue
            corner = _meet(rotated[-1], a, b, rotated[2])
            if corner is None or not any(
                _beyond(corner, side, width, height) for side in shared
            ):
                continue
            polygon = [corner] + rotated[2:]
            break
        else:
            break
    return polygon


def _area(polygon):
    total = 0.0
    for i in range(len(polygon)):
        (x0, y0), (x1, y1) = polygon[i - 1], polygon[i]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def _perimeter(polygon):
    return sum(_distance(polygon[i - 1], polygon[i]) for i in range(len(polygon)))


def _roundness(points):
    """Spread of the distances from the middle to the edge; ~0 for a circle."""
    middle_x = sum(x for x, _ in points) / len(points)
    middle_y = sum(y for _, y in points) / len(points)
    radii = [math.hypot(x - middle_x, y - middle_y) for x, y in points]
    mean = sum(radii) / len(radii)
    if mean <= 0:
        return 1.0
    variance = sum((r - mean) ** 2 for r in radii) / len(radii)
    return math.sqrt(variance) / mean


# --- the answer -----------------------------------------------------------


def classify(image_base64: str) -> str:
    width, height, pixels = decode_png(decode_base64(image_base64))
    component = _largest_component(width, height, _mask(width, height, pixels))
    outline = _outline(width, component)
    hull = _hull(outline)
    if len(hull) < 3:
        raise ImageError("the shape is too small to identify")

    perimeter = _perimeter(hull)
    if perimeter <= 0 or _area(hull) <= 0:
        raise ImageError("the shape is too small to identify")

    # 1.5px absorbs the staircase a rotated edge leaves behind; 1% of the
    # perimeter is well under a real corner and well over pixel noise
    corners = _unclip(_simplify(hull, max(1.5, 0.01 * perimeter)), width, height)
    perimeter, area = _perimeter(corners), _area(corners)
    if perimeter <= 0 or area <= 0:
        raise ImageError("the shape is too small to identify")
    circularity = 4 * math.pi * area / (perimeter * perimeter)

    if _roundness(outline) < 0.06:  # every edge the same distance from the middle
        return "circle"
    if len(corners) == 3:
        return "triangle"
    if len(corners) == 4:
        return "circle" if circularity >= 0.90 else "rectangle"
    if circularity >= 0.82:
        return "circle"
    return "rectangle" if circularity >= 0.66 else "triangle"
