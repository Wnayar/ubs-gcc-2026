import json
import heapq
from datetime import datetime, timedelta, timezone
from fractions import Fraction

INF = float("inf")


class Debug:
    def __init__(self, on=False):
        self.on = on

    def show(self, *bits):
        if self.on:
            print("[debug]", *bits)


log = Debug()


def read_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def write_time(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# speed on this road at time t, and the next moment it changes.
# windows run [start, end) and the worst one wins, so a 0.0 beats a 0.5
def traffic(windows, t):
    factor = Fraction(1)
    change = None
    for begin, end, f in windows:
        if begin <= t < end and f < factor:
            factor = f
        for moment in (begin, end):
            if moment > t and (change is None or moment < change):
                change = moment
    return factor, change


# time of coming out the far end after setting off down this road at t.
# the road takes `base` seconds of progress, and a factor of f earns
# f seconds of progress for every real second
def drive(base, windows, t):
    # a road that is shut on arrival is a dead end, because waiting at a
    # junction is not allowed
    if traffic(windows, t)[0] == 0:
        return None

    left = Fraction(base)
    while left > 0:
        factor, change = traffic(windows, t)
        # shut partway along, so sit it out and carry on from there
        if factor == 0:
            t = change
            continue
        if change is None or left <= (change - t) * factor:
            return t + left / factor
        left -= (change - t) * factor
        t = change
    return t


# plain dijkstra on the empty network: travel time from every junction to the
# target, and the road to take next on the way there
def base_times(graph, target):
    time_to = {target: Fraction(0)}
    step = {}
    queue = [(Fraction(0), target)]
    while queue:
        so_far, here = heapq.heappop(queue)
        if so_far > time_to[here]:
            continue
        for edge_id, nb, base in graph.get(here, ()):
            total = so_far + base
            if total < time_to.get(nb, INF):
                time_to[nb] = total
                step[nb] = (here, edge_id)
                heapq.heappush(queue, (total, nb))
    return time_to, step


def solve(data: str) -> str:
    # parse_float=Fraction keeps the speed factors exact. on ordinary floats
    # 20 / 0.2 lands on 99.99999999999999 and the visited set stops matching
    job = json.loads(data, parse_float=Fraction)

    no_route = json.dumps({"total_duration_sec": None, "arrival_time": None, "path": []})

    start = tuple(job["start_coordinate"])
    finish = tuple(job["end_coordinate"])
    depart = read_time(job["start_time"])

    # roads run both ways for the same duration, so each one goes in twice
    graph = {}
    spots = {tuple(n) for n in job.get("nodes", [])}
    for e in job.get("edges", []):
        a, b = tuple(e["node1"]), tuple(e["node2"])
        graph.setdefault(a, []).append((e["edge_id"], b, e["base_duration_sec"]))
        graph.setdefault(b, []).append((e["edge_id"], a, e["base_duration_sec"]))
        spots.add(a)
        spots.add(b)

    # example 2 asks for a destination that is not on the map at all
    if start not in spots or finish not in spots:
        return no_route

    # obstructions only bite one way round, so they hang off the direction.
    # times become seconds since departure to save juggling dates later on
    blocks = {}
    all_clear = Fraction(0)
    for o in job.get("obstructions", []):
        begin = Fraction(int((read_time(o["start_time"]) - depart).total_seconds()))
        end = Fraction(int((read_time(o["end_time"]) - depart).total_seconds()))
        if end <= begin:
            continue
        way = (o["edge_id"], tuple(o["edge"]["from"]), tuple(o["edge"]["to"]))
        blocks.setdefault(way, []).append((begin, end, Fraction(o["speed_factor"])))
        all_clear = max(all_clear, end)

    time_to, step = base_times(graph, finish)

    # dijkstra normally only tracks which junction, but a road that is shut
    # now might be open in a minute, so arriving early can be worse than
    # arriving late. the state has to carry the clock as well
    best = None
    best_state = None
    run_in = None
    came_from = {}
    seen = {(start, Fraction(0))}
    queue = [(Fraction(0), start)]

    while queue:
        now, here = heapq.heappop(queue)

        # the queue only moves forwards in time, so anything still sat in it
        # has already lost
        if best is not None and now >= best:
            break
        if here == finish:
            best, best_state, run_in = now, (here, now), None
            break
        if time_to.get(here, INF) == INF:
            continue

        # past the last obstruction nothing changes again, so the rest of the
        # trip is just the empty-network time
        if now >= all_clear:
            done = now + time_to[here]
            if best is None or done < best:
                best, best_state, run_in = done, (here, now), here
            continue

        for edge_id, nb, base in graph.get(here, ()):
            then = drive(base, blocks.get((edge_id, here, nb), ()), now)
            if then is None or (nb, then) in seen:
                continue
            if best is not None and then >= best:
                continue
            seen.add((nb, then))
            came_from[(nb, then)] = (here, now, edge_id)
            heapq.heappush(queue, (then, nb))

    if best is None:
        return no_route

    path = []
    state = best_state
    while state in came_from:
        here, now, edge_id = came_from[state]
        path.append(edge_id)
        state = (here, now)
    path.reverse()

    # tack on the last stretch if the trip finished on the empty network
    while run_in is not None and run_in != finish:
        run_in, edge_id = step[run_in]
        path.append(edge_id)

    duration = int(best) if best.denominator == 1 else float(best)
    return json.dumps({
        "total_duration_sec": duration,
        "arrival_time": write_time(depart + timedelta(seconds=float(best))),
        "path": path,
    })
