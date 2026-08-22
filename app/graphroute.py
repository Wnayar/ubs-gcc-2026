"""Cheapest-route planning for tool-box sheet 2, "Problem Set 2: Out after school".

The android is standing somewhere on a directed weighted map and asks, one hop
at a time, where to go next. We answer with a single node name.

The cost we are scored against is stated exactly:

    total cost = sum(edge weights) + sum(entry tolls)

so entering a node costs its toll, and folding that toll into every arc that
*ends* at the node turns the whole thing back into an ordinary shortest path.
The journey's starting node is never "entered", so its toll is not charged —
and since every route from a given start would pay it alike, that choice cannot
change which route is cheapest either way.

Four things score zero, and three of them are ours to prevent (the statement's
"WHAT SCORES ZERO"): a hop to a node that is not adjacent, a hop to a node
already visited on this journey, and running out of the hop allowance before
arriving. The fourth — setting off for the wrong place — is why the caller
resolves a place name to a marker before asking us anything.
"""
import heapq
import os
import re

import httpx

HOST = os.environ.get("TOOLBOX_HOST", "https://tool-box-2591eaa24fa3.herokuapp.com").rstrip("/")
TIMEOUT = float(os.environ.get("TOOLBOX_GRAPH_TIMEOUT", "6.0"))

STOP_LIKE = re.compile(r"^\s*stop[_\s-]?0*(\d{1,3})\s*$", re.IGNORECASE)


class RouteError(Exception):
    """No route could be planned. Reported to the android, never as a 500."""


# --- the map ---------------------------------------------------------------

_MAPS: dict[str, dict] = {}
_MAP_ORDER: list[str] = []
MAX_MAPS = 32

# The per-hop `go` tool is called with {from, to, moves_left} and no map_id, so
# the only way it can price a hop is to remember which map the journey is on.
_LAST_MAP_ID: str | None = None


def remember_map_id(map_id: str) -> None:
    global _LAST_MAP_ID
    if isinstance(map_id, str) and map_id.strip():
        _LAST_MAP_ID = map_id.strip()


def last_map_id() -> str | None:
    return _LAST_MAP_ID


def forget_map_id() -> None:
    global _LAST_MAP_ID
    _LAST_MAP_ID = None


def remember(map_id: str, graph: dict) -> dict:
    """Cache a parsed map. A journey re-reads the same map on every hop, and
    fetching it once keeps the later hops well clear of the 10 s response limit."""
    if map_id not in _MAPS:
        _MAP_ORDER.append(map_id)
        while len(_MAP_ORDER) > MAX_MAPS:
            _MAPS.pop(_MAP_ORDER.pop(0), None)
    _MAPS[map_id] = graph
    return graph


def parse_graph(payload: object) -> dict:
    """Validate {"adjacency": {u: {v: w}}, "tolls": {n: t}} into plain floats."""
    if not isinstance(payload, dict):
        raise RouteError("the map service did not return a map")
    raw_adjacency = payload.get("adjacency")
    if not isinstance(raw_adjacency, dict) or not raw_adjacency:
        raise RouteError("that map has no adjacency")

    adjacency: dict[str, dict[str, float]] = {}
    for node, edges in raw_adjacency.items():
        if not isinstance(node, str) or not isinstance(edges, dict):
            continue
        out: dict[str, float] = {}
        for target, weight in edges.items():
            if isinstance(target, str) and isinstance(weight, (int, float)) and not isinstance(
                weight, bool
            ):
                out[target] = float(weight)
        adjacency[node] = out
    if not adjacency:
        raise RouteError("that map has no usable edges")

    tolls: dict[str, float] = {}
    raw_tolls = payload.get("tolls")
    if isinstance(raw_tolls, dict):
        for node, toll in raw_tolls.items():
            if isinstance(node, str) and isinstance(toll, (int, float)) and not isinstance(
                toll, bool
            ):
                tolls[node] = float(toll)

    # every node that is only ever a destination still needs to be reachable
    for edges in list(adjacency.values()):
        for target in edges:
            adjacency.setdefault(target, {})
    return {"adjacency": adjacency, "tolls": tolls}


def load_graph(map_id: str) -> dict:
    remember_map_id(map_id)
    if map_id in _MAPS:
        return _MAPS[map_id]
    url = f"{HOST}/graph"
    try:
        response = httpx.get(url, params={"map_id": map_id}, timeout=TIMEOUT)
    except httpx.HTTPError as problem:
        raise RouteError(f"could not reach the map service ({type(problem).__name__})") from None
    if response.status_code != 200:
        raise RouteError(f"the map service rejected that map_id (HTTP {response.status_code})")
    try:
        payload = response.json()
    except ValueError:
        raise RouteError("the map service did not return JSON") from None
    return remember(map_id, parse_graph(payload))


def resolve_node(graph: dict, name: str) -> str | None:
    """Match a node the way the android might have written it."""
    if not isinstance(name, str) or not name.strip():
        return None
    nodes = graph["adjacency"]
    name = name.strip()
    if name in nodes:
        return name
    folded = {n.casefold(): n for n in nodes}
    if name.casefold() in folded:
        return folded[name.casefold()]
    like = STOP_LIKE.match(name)
    if like:
        for width in (2, 1, 3):
            candidate = f"STOP_{int(like.group(1)):0{width}d}".casefold()
            if candidate in folded:
                return folded[candidate]
    return None


# --- planning --------------------------------------------------------------

def _deloop(path: list[str]) -> list[str]:
    """Drop any cycle a layered search left behind; cannot raise the cost."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for node in path:
        if node in seen:
            del out[seen[node] + 1:]
            for later in [n for n, i in seen.items() if i > seen[node]]:
                del seen[later]
        else:
            seen[node] = len(out)
            out.append(node)
    return out


def path_cost(graph: dict, path: list[str]) -> float:
    """sum(edge weights) + sum(entry tolls), the statement's formula exactly."""
    tolls = graph["tolls"]
    total = 0.0
    for previous, node in zip(path, path[1:]):
        total += graph["adjacency"].get(previous, {}).get(node, 0.0)
        total += tolls.get(node, 0.0)
    return total


def cheapest_route(graph: dict, start: str, goal: str, forbidden=frozenset()) -> list[str] | None:
    """Least-cost route with no limit on hops. Dijkstra over arcs priced
    `weight + toll(destination)`, which is exactly the scored cost."""
    if start == goal:
        return [start]
    adjacency, tolls = graph["adjacency"], graph["tolls"]
    best: dict[str, float] = {start: 0.0}
    previous: dict[str, str] = {}
    queue = [(0.0, start)]
    settled: set[str] = set()
    while queue:
        cost, node = heapq.heappop(queue)
        if node in settled:
            continue
        settled.add(node)
        if node == goal:
            break
        for target, weight in adjacency.get(node, {}).items():
            if target in forbidden and target != goal:
                continue
            step = cost + weight + tolls.get(target, 0.0)
            if step < best.get(target, float("inf")):
                best[target] = step
                previous[target] = node
                heapq.heappush(queue, (step, target))
    if goal not in best:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    return path[::-1]


def cheapest_route_within(graph: dict, start: str, goal: str, hops: int,
                          forbidden=frozenset()) -> list[str] | None:
    """Least-cost route using at most `hops` edges.

    The allowance counts the edge being asked for right now, so a question
    asked with 1 left can only be answered by a node adjacent to the goal.
    Layered DP rather than Dijkstra: the cheapest route and the cheapest route
    that fits the curfew are frequently not the same route.
    """
    if start == goal:
        return [start]
    if hops <= 0:
        return None
    adjacency, tolls = graph["adjacency"], graph["tolls"]
    infinity = float("inf")
    best = [{start: 0.0}]
    previous: list[dict[str, str]] = [{}]
    for depth in range(1, hops + 1):
        layer: dict[str, float] = {}
        came: dict[str, str] = {}
        for node, cost in best[depth - 1].items():
            for target, weight in adjacency.get(node, {}).items():
                if target in forbidden and target != goal:
                    continue
                step = cost + weight + tolls.get(target, 0.0)
                if step < layer.get(target, infinity):
                    layer[target] = step
                    came[target] = node
        best.append(layer)
        previous.append(came)

    reached = [(layer.get(goal, infinity), depth) for depth, layer in enumerate(best)]
    cost, depth = min((c, d) for c, d in reached if c < infinity) if any(
        c < infinity for c, _ in reached
    ) else (infinity, 0)
    if cost == infinity:
        return None
    path = [goal]
    node = goal
    for level in range(depth, 0, -1):
        node = previous[level][node]
        path.append(node)
    return _deloop(path[::-1])


def plan(graph: dict, start: str, goal: str, hops_left: int | None = None,
         forbidden=frozenset()) -> list[str]:
    """The route we will actually walk, cheapest first and curfew-safe."""
    forbidden = frozenset(forbidden) - {start, goal}
    if hops_left is None:
        route = cheapest_route(graph, start, goal, forbidden)
        if route is None:
            raise RouteError(f"there is no route from {start} to {goal} on this map")
        return route

    route = cheapest_route_within(graph, start, goal, hops_left, forbidden)
    if route is not None:
        return route
    # Out of reach inside the curfew. Answering anyway beats refusing: our
    # reading of the allowance could be one out, and a hop toward the
    # destination can still arrive where a refusal certainly does not.
    fallback = cheapest_route(graph, start, goal, forbidden)
    if fallback is None:
        raise RouteError(f"there is no route from {start} to {goal} on this map")
    return fallback


# --- what has already been walked -----------------------------------------

_JOURNEYS: dict[tuple[str, str], list[str]] = {}
_JOURNEY_ORDER: list[tuple[str, str]] = []
MAX_JOURNEYS = 64


def visited_for(map_id: str, goal: str, current: str, graph: dict) -> list[str]:
    """The nodes this journey has already stood on, `current` last.

    Revisiting scores zero, and the android never tells us where it has been —
    but it asks us every hop, so the trail is ours to keep. Rebuilt rather than
    trusted: if it turns up somewhere our record cannot explain, we start again
    from there instead of forbidding nodes on the strength of a stale trail.
    """
    key = (map_id, goal)
    trail = _JOURNEYS.get(key)
    if trail is None:
        _JOURNEY_ORDER.append(key)
        while len(_JOURNEY_ORDER) > MAX_JOURNEYS:
            _JOURNEYS.pop(_JOURNEY_ORDER.pop(0), None)
        trail = []
    if current in trail:
        trail = trail[: trail.index(current) + 1]          # asked twice at one node
    elif trail and current in graph["adjacency"].get(trail[-1], {}):
        trail = trail + [current]                          # it moved on as told
    else:
        trail = [current]                                  # a journey we have not seen
    _JOURNEYS[key] = trail
    return trail


def record_step(map_id: str, goal: str, node: str) -> None:
    key = (map_id, goal)
    trail = _JOURNEYS.get(key)
    if trail is not None and (not trail or trail[-1] != node):
        trail.append(node)


def forget_journeys() -> None:
    _JOURNEYS.clear()
    _JOURNEY_ORDER.clear()


def forget_maps() -> None:
    _MAPS.clear()
    _MAP_ORDER.clear()
