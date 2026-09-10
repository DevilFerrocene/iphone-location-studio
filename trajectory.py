import bisect
import math
import random

RADIUS = 6371008.8


def distance(a, b):
    p, q = map(math.radians, (a[0], b[0]))
    dp, dl = q - p, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dl / 2) ** 2
    return 2 * RADIUS * math.asin(min(1, math.sqrt(h)))


def interpolate(a, b, f):
    def vector(point):
        lat, lon = map(math.radians, point)
        return [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    av, bv = vector(a), vector(b)
    omega = distance(a, b) / RADIUS
    if omega < 1e-10:
        return list(a)
    weights = math.sin((1-f)*omega)/math.sin(omega), math.sin(f*omega)/math.sin(omega)
    x, y, z = [weights[0]*u + weights[1]*v for u, v in zip(av, bv)]
    return [math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))]


def offset(point, bearing, meters):
    lat, lon = map(math.radians, point)
    angle = meters / RADIUS
    result_lat = math.asin(max(-1, min(1, math.sin(lat)*math.cos(angle) + math.cos(lat)*math.sin(angle)*math.cos(bearing))))
    result_lon = lon + math.atan2(math.sin(bearing)*math.sin(angle)*math.cos(lat), math.cos(angle)-math.sin(lat)*math.sin(result_lat))
    return [math.degrees(result_lat), (math.degrees(result_lon)+180)%360-180]


def curve_path(a, b, bend):
    if bend == 0:
        return [a, b], [0, distance(a, b)]
    lat1, lat2 = map(math.radians, [a[0], b[0]])
    dl = math.radians(b[1]-a[1])
    bearing = math.atan2(math.sin(dl)*math.cos(lat2), math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dl))
    control = offset(interpolate(a, b, .5), bearing-math.pi/2, 2*bend)
    path = [interpolate(interpolate(a, control, i/128), interpolate(control, b, i/128), i/128) for i in range(129)]
    lengths = [0.0]
    for start, end in zip(path, path[1:]):
        lengths.append(lengths[-1]+distance(start, end))
    return path, lengths


class Pace:
    """带持续节奏、轻微波动和加速度约束的速度过程。"""
    def __init__(self, rng):
        self.rng = rng
        self.velocity = None
        self.bounds = None
        self.hold = 0
        self.fast = False
        self.wobble = 0.0

    def advance(self, dt, low, high):
        span = high - low
        if self.bounds != (low, high):
            self.velocity = low + .25*span if self.velocity is None else min(high, max(low, self.velocity))
            self.bounds = (low, high)
            self.hold = 0
        remaining, travelled = dt, 0.0
        while remaining > 1e-10:
            step = min(.25, remaining)
            if self.hold <= 0:
                self.fast = not self.fast
                fraction = self.rng.uniform(.62, .88) if self.fast else self.rng.uniform(.12, .38)
                self.target = low + fraction*span
                self.hold = self.rng.uniform(25, 65) if self.fast else self.rng.uniform(15, 40)
            alpha = math.exp(-step/4)
            self.wobble = alpha*self.wobble + math.sqrt(1-alpha*alpha)*self.rng.gauss(0, min(.035*span, .06))
            target = min(high, max(low, self.target+self.wobble))
            change = (target-self.velocity)*(1-math.exp(-step/5))
            acceleration = min(.12, max(.01, span*.08))
            velocity = min(high, max(low, self.velocity+max(-acceleration*step, min(acceleration*step, change))))
            travelled += (self.velocity+velocity)*.5*step
            self.velocity = velocity
            self.hold -= step
            remaining -= step
        return travelled/dt


def generate(data):
    points = data.get('points')
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError('请在地图上至少选 2 个路线点')
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('路线点格式错误')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
            raise ValueError('坐标必须是有限数字')
        if not -85 <= point[0] <= 85 or not -180 <= point[1] <= 180:
            raise ValueError('坐标超出地图范围')
    keys = ('speed', 'interval', 'noise', 'bend', 'speed_min', 'speed_max')
    defaults = {k: data.get(k, value) for k, value in zip(keys, (1.4, 1, 2, 0, 0, 0))}
    overrides = data.get('segments', [None] * (len(points) - 1))
    if not isinstance(overrides, list) or len(overrides) != len(points) - 1:
        raise ValueError('每两个相邻路线点必须对应一段参数')
    rng = random.Random(int(data.get('seed', 42)))
    pace = Pace(random.Random(int(data.get('seed', 42)) + 1))
    samples, sections = [], []
    total = duration = 0.0
    for segment, (a, b) in enumerate(zip(points, points[1:])):
        override = overrides[segment]
        if override is not None and not isinstance(override, dict):
            raise ValueError(f'第 {segment+1} 段参数格式错误')
        settings = {**defaults, **(override or {})}
        speed, interval, noise, bend, low, high = (float(settings[k]) for k in keys)
        if not all(math.isfinite(v) for v in (speed, interval, noise, bend, low, high)):
            raise ValueError(f'第 {segment+1} 段参数必须是有限数字')
        if speed <= 0 or interval <= 0 or noise < 0:
            raise ValueError(f'第 {segment+1} 段：速度和间隔必须大于零，噪声必须非负')
        if (low != 0 or high != 0) and not 0 < low <= high:
            raise ValueError(f'第 {segment+1} 段：随机速度需满足 0 < 最低 ≤ 最高；均为 0 使用固定速度')
        path, lengths = curve_path(a, b, bend)
        length = lengths[-1]
        if length == 0:
            sections.append({'index': segment, 'distance': 0, 'duration': 0, **settings})
            continue
        east = north = local_time = travel = 0.0
        current_speed = min(high, max(low, pace.velocity)) if low and pace.velocity is not None else (low+.25*(high-low) if low else speed)
        if not samples:
            samples.append({'t': duration, 'lat': a[0], 'lon': a[1], 'segment': segment, 'speed': current_speed})
        while travel < length:
            if low:
                current_speed = pace.advance(interval, low, high)
            else:
                pace.velocity = speed
                pace.bounds = None
            dt = min(interval, (length-travel)/current_speed)
            next_travel = min(length, travel + current_speed*dt)
            if next_travel <= travel or local_time + dt <= local_time:
                raise ValueError('数值超出浮点精度，请调整速度或间隔')
            travel = next_travel
            local_time += dt
            section = min(bisect.bisect_right(lengths, travel)-1, len(path)-2)
            fraction = (travel-lengths[section])/(lengths[section+1]-lengths[section])
            lat, lon = interpolate(path[section], path[section+1], fraction)
            alpha = math.exp(-dt/5)
            east = alpha*east + (1-alpha)*rng.uniform(-noise, noise)
            north = alpha*north + (1-alpha)*rng.uniform(-noise, noise)
            # 每段两端的偏移平滑收敛为零，共用途经点只发送一次。
            envelope = min(1, travel/(current_speed*5), (length-travel)/(current_speed*5))
            lat += math.degrees(north*envelope/RADIUS)
            lon += math.degrees(east*envelope/(RADIUS*math.cos(math.radians(lat))))
            lon = (lon+180)%360-180
            samples.append({'t': duration+local_time, 'lat': lat, 'lon': lon, 'segment': segment, 'speed': current_speed})
        sections.append({'index': segment, 'distance': length, 'duration': local_time, **settings})
        total += length
        duration += local_time
    if not samples:
        raise ValueError('路线太短，请选择不同的位置')
    return {'samples': samples, 'distance': total, 'duration': duration, 'segments': sections}
