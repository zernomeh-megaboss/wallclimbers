"""
Wall Climbers — простой прототип на Pygame.
Игрок сам идёт вперёд и назад по стене:
  W / стрелка вверх    — вперёд (вверх),  S / стрелка вниз — назад (вниз)
  на телефоне          — две кнопки на экране
  пробел / тап         — прыжок вдоль той же стены (перепрыгнуть шипы)
  прыжок в воздухе     — перелёт на другую стену
Посередине иногда есть стена: к ней и обратно хватает ОДНОГО прыжка.
Когда центральная стена кончается, игрок перелетает на противоположную боковую.
Снизу поднимается ЛАВА — стоять на месте нельзя. Монетки отодвигают лаву и копятся.
Угрозы: выдвижные и скользящие шипы, пилы, огненные шары, крошащаяся стена.
Меню: выбор сложности (обычная / сложная), настройки громкости музыки и звуков ползунками.
Звук: M — включить/выключить (или значок динамика сверху справа). Музыка у каждой зоны своя.
Графика пиксельная: всё рисуется на холсте 240x400 и увеличивается в 2 раза; каждые 700 очков — новая зона.
"""
import array
import asyncio
import json
import math
import os
import random
import sys
import time

import pygame

# ---------- Настройки ----------
W, H = 480, 800            # логический размер экрана (портрет)
WALL = 40                  # толщина стен
PLAYER = 34                # размер игрока
MOVE_SPEED = 200           # скорость игрока вперёд/назад (px/s), постоянная
HOP_VEL = 460              # с какой скоростью отрываемся от стены при прыжке
HOP_PULL = 1200            # как сильно стена притягивает обратно
CROSS_VX = 650             # скорость перелёта на другую стену
SPIKE_W, SPIKE_H = 26, 48
INPUT_BUFFER = 0.15        # сек: тап чуть раньше приземления не пропадёт

# центральная стена
PILLAR_W = 36
PILLAR_MIN_LEN, PILLAR_MAX_LEN = 380, 620
PILLAR_GAP_MIN, PILLAR_GAP_MAX = 500, 1100   # расстояние между стенами
PILLAR_SPIKE_CHANCE = 0.5                     # шанс, что на стене будут шипы
# за сколько секунд игрок долетает от боковой стены до центральной
PILLAR_REACH_T = (W // 2 - PILLAR_W // 2 - PLAYER - WALL) / CROSS_VX

# монетки
COIN_R = 13
COIN_CHANCE = 0.55         # шанс монетки у каждой группы шипов
HOP_APEX = HOP_VEL ** 2 / (2 * HOP_PULL)      # макс. отход от стены в прыжке

# честная генерация: уровень всегда должен быть проходим
SEP_BASE = 160             # пустое место вокруг шипа на ДРУГИХ поверхностях, px ...
SEP_TIME = 0.6             # ... плюс столько секунд бега (растёт со скоростью)
SAME_GAP_TIME = 0.95       # шипы на одной поверхности: минимум столько секунд друг от друга
EXIT_TIME = 0.4            # зона без шипов на боковых стенах над концом центральной стены
CLUSTER_GAP = 95           # расстояние между шипами в группе

# усложнение со счётом: значения плавно идут от обычных к "HARD" к DIFF_RAMP очкам
DIFF_RAMP = 4000                 # счёт, на котором сложность достигает максимума
SEP_BASE_HARD = 130              # (см. SEP_BASE)
SEP_TIME_HARD = 0.45             # (см. SEP_TIME)
SAME_GAP_TIME_HARD = 0.8         # (см. SAME_GAP_TIME)
GAP_SCALE_HARD = 0.7             # множитель случайного промежутка 200-300 px между группами
CLUSTER_CHANCE = 0.3             # шанс, что вместо одного шипа будет группа
CLUSTER_CHANCE_HARD = 0.75
CLUSTER_STEPS = ((100, 2), (800, 3), (1800, 4), (3000, 5))   # (счёт, макс. шипов в группе)
PILLAR_SPIKE_CHANCE_HARD = 0.8   # шанс шипов на центральной стене при максимальной сложности

# лава
LAVA_START_GAP = 380       # на сколько ниже игрока лава в начале, px
LAVA_MAX_GAP = 300         # дальше этого расстояния лава не отстаёт от игрока
LAVA_BASE = 40             # скорость подъёма лавы, px/s: BASE + GAIN * счёт (не больше MAX)
LAVA_GAIN = 0.02
LAVA_MAX_SPEED = 110
LAVA_COIN_PUSH = 80        # одна монетка отодвигает лаву вниз на столько px
LAVA_SLACK_DECAY = 20      # как быстро лава «навёрстывает» отодвинутое, px/s

# новые угрозы
CRUMBLE_TIME = 0.55                          # сколько секунд можно стоять на крошащейся стене
HAZARD_GAP_MIN, HAZARD_GAP_MAX = 550, 850    # расстояние между угрозами, px
HAZARD_TABLE = (                             # (с какого счёта появляется, тип, вес)
    (100, "pulse", 3),      # выдвижной шип
    (300, "slide", 3),      # скользящий вдоль стены шип
    (500, "saw", 3),        # пила, ездящая поперёк коридора
    (700, "crumble", 2),    # крошащаяся стена
    (900, "fire", 2),       # огненный шар
)
DEATH_TEXT = {"pulse": "Выдвижной шип", "slide": "Скользящий шип",
              "saw": "Пила", "fire": "Огненный шар"}

# ---------- сложность ----------
# «Обычная» собирается из констант выше (так игра выглядела до появления выбора).
# «Сложная» — те же ключи с другими значениями. Новую сложность можно добавить здесь же.
NORMAL = dict(
    name="ОБЫЧНАЯ", info="Как задумано",
    lava_start_gap=LAVA_START_GAP, lava_max_gap=LAVA_MAX_GAP, lava_base=LAVA_BASE, lava_gain=LAVA_GAIN,
    lava_max_speed=LAVA_MAX_SPEED, lava_coin_push=LAVA_COIN_PUSH,
    crumble_time=CRUMBLE_TIME, hazard_gap=(HAZARD_GAP_MIN, HAZARD_GAP_MAX), hazard_table=HAZARD_TABLE,
    diff_ramp=DIFF_RAMP, cluster_chance=CLUSTER_CHANCE, cluster_chance_hard=CLUSTER_CHANCE_HARD,
    cluster_steps=CLUSTER_STEPS, pillar_chance=PILLAR_SPIKE_CHANCE, pillar_chance_hard=PILLAR_SPIKE_CHANCE_HARD,
    coin_chance=COIN_CHANCE, coin_value=1, hz_speed=1.0, sep_scale=1.0,
    gap_scale_hard=GAP_SCALE_HARD, same_gap_hard=SAME_GAP_TIME_HARD, hazard_sep_scale=1.0)
HARD = dict(
    NORMAL, name="СЛОЖНАЯ", info="Больше шипов и угроз,\nлава быстрее, монеты x2",
    lava_start_gap=320, lava_max_gap=240, lava_base=62, lava_gain=0.03, lava_max_speed=150, lava_coin_push=60,
    crumble_time=0.45, hazard_gap=(400, 620),
    hazard_table=((60, "pulse", 3), (180, "slide", 3), (320, "saw", 3), (450, "crumble", 2), (600, "fire", 2)),
    diff_ramp=2500, cluster_chance=0.5, cluster_chance_hard=0.9,
    cluster_steps=((60, 2), (400, 3), (1000, 4), (1800, 5), (2800, 6)),
    pillar_chance=0.7, pillar_chance_hard=0.9, coin_chance=0.45, coin_value=2, hz_speed=1.2, sep_scale=0.9,
    gap_scale_hard=0.55, same_gap_hard=0.74, hazard_sep_scale=0.7)
DIFFICULTIES = {"normal": NORMAL, "hard": HARD}
DIFF_ORDER = ("normal", "hard")

BG = (60, 25, 10)
WALL_COLOR = (200, 55, 0)
WALL_LINE = (48, 54, 88)
PLAYER_COLOR = (255, 222, 0)
SPIKE_COLOR = (239, 71, 111)
COIN_COLOR = (255, 238, 120)
COIN_EDGE = (255, 150, 0)
LAVA_COLOR = (235, 75, 10)
LAVA_GLOW = (255, 200, 70)
LAVA_DEEP = (150, 30, 5)
WARN_COLOR = (255, 170, 70)
SOCKET_COLOR = (110, 30, 0)
TRACK_COLOR = (110, 35, 5)
SLIDER_COLOR = (255, 120, 90)
SAW_COLOR = (225, 230, 240)
CRUMBLE_COLOR = (235, 125, 55)
TEXT = (240, 240, 250)

try:
    SAVE_FILE = os.path.join(os.environ.get("ANDROID_PRIVATE") or os.path.dirname(os.path.abspath(__file__)),
                             "wall_climbers_save.json")
except NameError:
    SAVE_FILE = "wall_climbers_save.json"


def load_save():
    """Читает сохранение: рекорды по сложностям, монеты, настройки звука и последнюю сложность."""
    default = dict(bests={"normal": 0, "hard": 0}, coins=0, muted=False, music=1.0, sfx=1.0,
                   difficulty="normal")
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        bests = dict(default["bests"])
        if isinstance(data.get("best"), int):               # старый формат: один рекорд
            bests["normal"] = data["best"]
        if isinstance(data.get("bests"), dict):
            for key in bests:
                bests[key] = int(data["bests"].get(key, 0))
        clamp = lambda v: max(0.0, min(1.0, float(v)))
        return dict(bests=bests, coins=int(data.get("coins", 0)), muted=bool(data.get("muted", False)),
                    music=clamp(data.get("music", 1.0)), sfx=clamp(data.get("sfx", 1.0)),
                    difficulty=str(data.get("difficulty", "normal")))
    except Exception:
        return default


def write_save(data):
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass   # например, в браузере файлы недоступны


# ---------- Угрозы ----------
def circle_hits_rect(cx, cy, r, rect):
    nx = max(rect.left, min(cx, rect.right))
    ny = max(rect.top, min(cy, rect.bottom))
    return (cx - nx) ** 2 + (cy - ny) ** 2 <= r * r


def spike_rect(fx, n, y):
    x = fx if n == 1 else fx - SPIKE_W
    return pygame.Rect(int(x), int(y), SPIKE_W, SPIKE_H)


def spike_poly(fx, n, top, length):
    """Треугольник шипа: основание на стене fx, остриё на расстоянии length."""
    return [(fx, top), (fx + n * length, top + SPIKE_H / 2), (fx, top + SPIKE_H)]


class Hazard:
    """Базовая угроза. top/bottom — зона, которую она занимает (для проверки проходимости)."""
    kind = ""
    top = bottom = 0

    def update(self, g, dt):
        pass

    def hits(self, g, hit):
        return False


class Pulse(Hazard):
    """Шип, который выдвигается и прячется по ритму (перед выдвижением мигает предупреждение)."""
    kind = "pulse"

    def __init__(self, n, fx, y, count, period, phase):
        self.n, self.fx, self.y, self.count = n, fx, y, count
        self.period, self.phase = period, phase
        self.top = y - (count - 1) * CLUSTER_GAP
        self.bottom = y + SPIKE_H

    def ext(self, t):
        p = ((t + self.phase) % self.period) / self.period
        if p < 0.45:
            return 1.0
        if p < 0.55:
            return 1.0 - (p - 0.45) / 0.10
        if p < 0.80:
            return 0.0
        if p < 0.92:
            return 0.3                       # предупреждение: торчит кончик
        return 0.3 + 0.7 * (p - 0.92) / 0.08

    def hits(self, g, hit):
        if self.ext(g.time) < 0.6:
            return False
        return any(hit.colliderect(spike_rect(self.fx, self.n, self.y - i * CLUSTER_GAP).inflate(-6, -14))
                   for i in range(self.count))


class Slider(Hazard):
    """Шип, который ездит вверх-вниз вдоль стены."""
    kind = "slide"

    def __init__(self, n, fx, y0, amp, period, phase):
        self.n, self.fx, self.y0, self.amp = n, fx, y0, amp
        self.period, self.phase = period, phase
        self.top = y0 - amp
        self.bottom = y0 + amp + SPIKE_H

    def pos_y(self, t):
        return self.y0 + self.amp * math.sin(2 * math.pi * (t + self.phase) / self.period)

    def hits(self, g, hit):
        return hit.colliderect(spike_rect(self.fx, self.n, self.pos_y(g.time)).inflate(-6, -14))


class Saw(Hazard):
    """Пила, которая ездит из стороны в сторону поперёк коридора."""
    kind = "saw"
    R = 20
    XMIN = WALL + 20
    XMAX = W - WALL - 20

    def __init__(self, y, speed, phase):
        self.y, self.speed, self.phase = y, speed, phase
        self.top = y - self.R
        self.bottom = y + self.R

    def pos_x(self, t):
        span = self.XMAX - self.XMIN
        u = (self.speed * (t + self.phase)) % (2 * span)
        return self.XMIN + (u if u <= span else 2 * span - u)

    def hits(self, g, hit):
        return circle_hits_rect(self.pos_x(g.time), self.y, self.R - 3, hit)


class Fireball(Hazard):
    """Огненный шар: сначала мигает предупреждение у стены, потом шар пролетает поперёк коридора."""
    kind = "fire"
    R = 11

    def __init__(self, y, direction, period, phase, speed=320):
        self.y, self.dir, self.period, self.phase = y, direction, period, phase
        self.warn = 0.9
        self.speed = speed
        self.travel = (W - 2 * WALL) / self.speed
        self.top = y - self.R - 6
        self.bottom = y + self.R + 6

    def state(self, t):
        p = (t + self.phase) % self.period
        if p < self.warn:
            return "warn", p / self.warn
        if p < self.warn + self.travel:
            return "fly", (p - self.warn) / self.travel
        return "idle", 0.0

    def pos_x(self, u):
        a, b = (WALL, W - WALL) if self.dir == 1 else (W - WALL, WALL)
        return a + (b - a) * u

    def hits(self, g, hit):
        st, u = self.state(g.time)
        return st == "fly" and circle_hits_rect(self.pos_x(u), self.y, self.R - 2, hit)


class Crumble(Hazard):
    """Крошащаяся стена: если стоять на ней дольше CRUMBLE_TIME, она обваливается
    и выбрасывает игрока на противоположную сторону. Дыра остаётся — встать на неё нельзя."""
    kind = "crumble"

    def __init__(self, n, y, h, limit=CRUMBLE_TIME):
        self.n = n
        self.limit = limit          # сколько секунд можно стоять до обвала
        self.x0 = WALL if n == 1 else W - WALL - PLAYER     # где стоит игрок на этой стене
        self.ctop, self.h = y, h
        self.state = "intact"
        self.timer = 0.0
        self.top = y - 170          # зона с запасом: туда игрок приземлится после вылета
        self.bottom = y + h + 40

    def player_on(self, g):
        return (g.mode == "run" and g.pillar is None and g.n == self.n and g.x0 == self.x0
                and g.y + PLAYER > self.ctop and g.y < self.ctop + self.h)

    def update(self, g, dt):
        on = self.player_on(g)
        if self.state == "intact":
            if on:
                self.timer += dt
                if self.timer >= self.limit:
                    self.state = "broken"
                    g.burst(WALL / 2 if self.n == 1 else W - WALL / 2, self.ctop + self.h / 2)
                    g.start_cross()
            else:
                self.timer = max(0.0, self.timer - dt * 0.5)
        elif on:
            g.start_cross()         # на дыре стоять нельзя


class Game:
    def __init__(self):
        data = load_save()
        self.bests, self.total_coins, self.muted = data["bests"], data["coins"], data["muted"]
        self.music_level, self.sfx_level = data["music"], data["sfx"]
        self.difficulty = data["difficulty"] if data["difficulty"] in DIFFICULTIES else "normal"
        self.cfg = DIFFICULTIES[self.difficulty]
        self.best = self.bests[self.difficulty]
        self.state = "menu"   # menu / play / dead
        self.dead_timer = 0.0
        self.move_dir = 0     # 1 — вперёд (W), -1 — назад (S), 0 — стоим
        self.record = False   # включают, когда нужны события для эффектов (см. Renderer)
        self.events = []
        self.reset()

    def reset(self):
        # "поверхность", на которой стоит игрок
        self.x0 = float(WALL)          # x игрока, когда он прижат к поверхности
        self.n = 1                     # куда смотрит поверхность: 1 — вправо, -1 — влево
        self.pillar = None             # Rect центральной стены, если бежим по ней
        self.mode = "run"              # run / hop / cross
        self.off = 0.0                 # отступ от поверхности во время прыжка
        self.off_v = 0.0
        self.x = float(WALL)           # используется только при перелёте
        self.vx = 0.0
        self.direction = 1             # куда летим при перелёте
        self.y = 0.0
        self.start_y = 0.0
        self.buffer = 0.0
        self.vy = 0.0                  # вертикальная скорость (по нажатым W/S)
        self.top_y = self.y            # самая высокая точка: по ней считается счёт
        self.cam_y = self.y - H * 0.65
        self.spikes = []               # (Rect в мировых координатах, n)
        self.pillars = []              # Rect-ы центральных стен
        self.coins = []                # (x, y)
        self.next_spike_y = -400.0
        self.next_pillar_y = -1000.0
        self.score = 0
        self.run_coins = 0
        self.time = 0.0
        self.hazards = []              # динамические угрозы (шипы-ловушки, пилы, ...)
        self.zones = []                # (top, bottom) зоны угроз — для проверки проходимости
        self.debris = []               # осколки (только красота)
        self.next_hazard_y = -700.0
        self.death_reason = ""
        self.lava_y = self.y + PLAYER + self.cfg["lava_start_gap"]
        self.lava_slack = 0.0

    # ---------- Ввод ----------
    def tap(self):
        if self.state == "menu":
            self.start_game()
        elif self.state == "play":
            if self.mode == "run":
                self.jump_from_run()
            elif self.mode == "hop":
                self.start_cross()
            else:
                self.buffer = INPUT_BUFFER
        elif self.state == "dead" and self.dead_timer > 0.4:
            self.start_game()

    def start_game(self):
        self.reset()
        self.state = "play"
        self.emit("start")

    def to_menu(self):
        self.reset()
        self.state = "menu"

    def set_difficulty(self, key):
        self.difficulty = key
        self.cfg = DIFFICULTIES[key]
        self.best = self.bests[key]
        if self.state == "menu":
            self.reset()

    def start_hop(self):
        self.mode = "hop"
        self.off = 0.0
        self.off_v = HOP_VEL
        self.buffer = 0.0
        self.emit("hop", self.pos_x() + PLAYER / 2, self.y + PLAYER / 2, self.n)

    def start_cross(self, direction=None):
        self.x = self.pos_x()
        # по умолчанию летим туда, куда смотрит поверхность
        self.direction = self.n if direction is None else direction
        self.vx = self.direction * CROSS_VX
        self.pillar = None
        self.mode = "cross"
        self.emit("cross", self.x + PLAYER / 2, self.y + PLAYER / 2, self.direction)

    def land(self, x0, n, pillar):
        self.x0 = float(x0)
        self.n = n
        self.pillar = pillar
        self.off = 0.0
        self.off_v = 0.0
        self.mode = "run"
        self.emit("land", self.x0 + PLAYER / 2, self.y + PLAYER / 2, n)
        if self.buffer > 0:
            self.buffer = 0.0
            self.jump_from_run()

    def pillar_beside(self):
        """Есть ли рядом центральная стена, до которой хватит одного прыжка."""
        if self.pillar is not None:          # мы уже на центральной стене
            return True
        ya = self.y + self.vy * PILLAR_REACH_T       # где будет игрок к моменту долёта
        return any(ya < p.bottom and ya + PLAYER > p.top for p in self.pillars)

    def jump_from_run(self):
        if self.pillar_beside():
            self.start_cross()               # один прыжок — на соседнюю поверхность
        else:
            self.start_hop()                 # иначе прыжок вдоль стены

    # ---------- Логика ----------
    def right_x(self):
        return W - WALL - PLAYER

    def pos_x(self):
        if self.mode == "cross":
            return self.x
        return self.x0 + self.n * self.off

    def player_rect(self):
        return pygame.Rect(int(self.pos_x()), int(self.y), PLAYER, PLAYER)

    def add_spike(self, fx, n, y):
        """fx — x поверхности, n — в какую сторону торчит шип."""
        x = fx if n == 1 else fx - SPIKE_W
        self.spikes.append((pygame.Rect(int(x), int(y), SPIKE_W, SPIKE_H), n))

    def add_coin(self, x, y):
        self.coins.append((x, y))

    def near_pillar(self, x, y):
        return any(p.inflate(90, 60).collidepoint(int(x), int(y)) for p in self.pillars)

    def speed_at(self, y):
        """Скорость игрока (постоянная): по ней считаются безопасные расстояния между шипами."""
        return MOVE_SPEED

    @staticmethod
    def surface(rect, n):
        """Ключ поверхности, на которой стоит шип: левая/правая стена или грань центральной."""
        return (rect.left if n == 1 else rect.right, n)

    @staticmethod
    def lerp(a, b, t):
        return a + (b - a) * t

    def difficulty_at(self, y):
        """Сложность от 0 до 1: растёт вместе со счётом до DIFF_RAMP очков."""
        return min(1.0, max(0.0, (self.start_y - y) / 10 / self.cfg["diff_ramp"]))

    def sep_at(self, y):
        """Свободное место вокруг шипа на других поверхностях."""
        d = self.difficulty_at(y)
        return (self.lerp(SEP_BASE, SEP_BASE_HARD, d) +
                self.lerp(SEP_TIME, SEP_TIME_HARD, d) * self.speed_at(y)) * self.cfg["sep_scale"]

    def same_gap(self, y):
        """Минимальный промежуток между группами на одной поверхности."""
        d = self.difficulty_at(y)
        return self.lerp(SAME_GAP_TIME, self.cfg["same_gap_hard"], d) * self.speed_at(y)

    def gap_scale(self, y):
        return self.lerp(1.0, self.cfg["gap_scale_hard"], self.difficulty_at(y))

    def cluster_size(self, y):
        """Сколько шипов подряд будет в группе: растёт со счётом."""
        score = (self.start_y - y) / 10
        top = 1
        for need, size in self.cfg["cluster_steps"]:
            if score >= need:
                top = size
        if top == 1:
            return 1
        d = self.difficulty_at(y)
        if random.random() > self.lerp(self.cfg["cluster_chance"], self.cfg["cluster_chance_hard"], d):
            return 1
        return random.randint(max(2, top - 2), top)

    def exit_zone_conflict(self, top, bottom):
        """Зона над верхним краем центральной стены: сюда игрок приземляется после вылета."""
        for pr in self.pillars:
            zone_top = pr.top - (EXIT_TIME * self.speed_at(pr.top) + 160)
            if top < pr.top + 50 and bottom > zone_top:
                return True
        return False

    def spike_ok(self, fx, n, y):
        """Можно ли поставить шип, не создав непроходимого места."""
        sep = self.sep_at(y)
        me = (fx, n)
        # 1) на всех остальных поверхностях вокруг шипа должно быть свободно —
        #    туда игрок сможет уйти
        for rect, rn in self.spikes:
            if self.surface(rect, rn) != me and \
                    y < rect.bottom + sep and y + SPIKE_H > rect.top - sep:
                return False
        # 2) вокруг динамических угроз тоже должно быть свободно
        for zt, zb in self.zones:
            if y < zb + sep and y + SPIKE_H > zt - sep:
                return False
        # 3) над верхним краем центральной стены боковые стены должны быть чистыми
        if fx in (WALL, W - WALL) and self.exit_zone_conflict(y, y + SPIKE_H):
            return False
        return True

    # ---------- генерация угроз ----------
    def pick_hazard(self, score):
        pool = [(kind, w) for need, kind, w in self.cfg["hazard_table"] if score >= need]
        if not pool:
            return None
        kinds, weights = zip(*pool)
        return random.choices(kinds, weights)[0]

    def make_hazard(self, kind, y):
        n = random.choice((1, -1))
        fx = WALL if n == 1 else W - WALL
        d = self.difficulty_at(y)
        hz = self.cfg["hz_speed"]                 # на сложной всё движется быстрее
        if kind == "pulse":
            count = 2 if random.random() < 0.5 * d else 1
            return Pulse(n, fx, y, count, random.uniform(2.2, 3.0) / hz, random.uniform(0, 3))
        if kind == "slide":
            return Slider(n, fx, y, random.randint(70, 130), random.uniform(3.0, 4.2) / hz, random.uniform(0, 4))
        if kind == "saw":
            return Saw(y, random.uniform(120, 170) * hz, random.uniform(0, 6))
        if kind == "crumble":
            return Crumble(n, y, random.randint(120, 170), self.cfg["crumble_time"])
        return Fireball(y, random.choice((1, -1)), random.uniform(2.8, 3.6) / hz, random.uniform(0, 3), 320 * hz)

    def hazard_ok(self, h):
        """Вокруг угрозы должно быть пусто: и от шипов, и от других угроз."""
        sep = self.sep_at(h.top)
        for rect, _ in self.spikes:
            if h.top < rect.bottom + sep and h.bottom > rect.top - sep:
                return False
        hs = sep * self.cfg["hazard_sep_scale"]          # между самими угрозами можно поближе
        for zt, zb in self.zones:
            if h.top < zb + hs and h.bottom > zt - hs:
                return False
        if self.exit_zone_conflict(h.top, h.bottom):
            return False
        if h.kind in ("saw", "fire"):        # поперёк коридора центральной стены быть не должно
            for pr in self.pillars:
                if h.top < pr.bottom + 120 and h.bottom > pr.top - 120:
                    return False
        return True

    def spawn_hazards(self):
        while self.next_hazard_y > self.cam_y - 900:     # заранее, чтобы шипы обходили зоны угроз
            y0 = self.next_hazard_y
            kind = self.pick_hazard((self.start_y - y0) / 10)
            placed = None
            if kind:
                for attempt in range(8):
                    h = self.make_hazard(kind, y0 - attempt * 50)
                    if self.hazard_ok(h):
                        placed = h
                        break
            if placed is None:
                self.next_hazard_y = y0 - 150
                continue
            self.hazards.append(placed)
            self.zones.append((placed.top, placed.bottom))
            if placed.kind in ("saw", "fire") and random.random() < 0.45:
                self.add_coin(W / 2, (placed.top + placed.bottom) / 2)    # монетка прямо в опасной зоне
            d = self.difficulty_at(placed.top)
            self.next_hazard_y = placed.top - random.randint(*self.cfg["hazard_gap"]) \
                * self.lerp(1.0, 0.6, d)

    def emit(self, *event):
        if self.record:
            self.events.append(event)

    def burst(self, cx, cy):
        self.emit("crumble", cx, cy)
        for _ in range(10):
            self.debris.append((cx + random.uniform(-15, 15), cy + random.uniform(-30, 30),
                                random.uniform(-90, 90), random.uniform(-160, -20), 0.9))

    def spawn_pillars(self):
        while self.next_pillar_y > self.cam_y - 1400:
            length = random.randint(PILLAR_MIN_LEN, PILLAR_MAX_LEN)
            bottom = int(self.next_pillar_y)
            top = bottom - length
            pr = pygame.Rect(W // 2 - PILLAR_W // 2, top, PILLAR_W, length)
            self.pillars.append(pr)
            if random.random() < self.lerp(self.cfg["pillar_chance"], self.cfg["pillar_chance_hard"],
                                           self.difficulty_at(top)):
                y = top + 140
                while y < bottom - 160:
                    faces = [1, -1]
                    random.shuffle(faces)
                    for n in faces:
                        fx = pr.right if n == 1 else pr.left
                        if self.spike_ok(fx, n, y):
                            self.add_spike(fx, n, y)
                            if random.random() < 0.5:
                                self.add_coin(fx + n * (HOP_APEX + PLAYER / 2), y + SPIKE_H / 2)
                            y += max(random.randint(190, 260) * self.gap_scale(y), self.same_gap(y))
                            break
                    else:
                        y += 40                  # место занято — пробуем чуть ниже
            self.next_pillar_y = top - random.randint(PILLAR_GAP_MIN, PILLAR_GAP_MAX)

    def spawn_spikes(self):
        while self.next_spike_y > self.cam_y - 300:
            y0 = self.next_spike_y
            n = random.choice((1, -1))           # сторона 50 на 50: 1 — левая стена, -1 — правая
            fx = WALL if n == 1 else W - WALL
            # если рядом шип на другой поверхности — сдвигаем новый выше, пока не освободится место
            y = y0
            while y > y0 - 700 and not self.spike_ok(fx, n, y):
                y -= 20
            if not self.spike_ok(fx, n, y):
                self.next_spike_y = y0 - 100     # не нашли место — пробуем выше
                continue
            count = self.cluster_size(y)
            self.add_spike(fx, n, y)
            y_last = y
            # группа из нескольких шипов подряд: чем больше счёт, тем она длиннее
            for i in range(1, count):
                yi = y - i * CLUSTER_GAP
                if not self.spike_ok(fx, n, yi):
                    break
                self.add_spike(fx, n, yi)
                y_last = yi
            hop_cy = y + SPIKE_H / 2 if count >= 3 else None
            self.spawn_coin_near(fx, n, (y + y_last) / 2 + SPIKE_H / 2, hop_cy)
            self.next_spike_y = y_last - max(random.randint(200, 300) * self.gap_scale(y_last),
                                             self.same_gap(y_last))

    def spawn_coin_near(self, fx, n, cy, hop_cy=None):
        """Монетки кладём так, чтобы их было непросто взять."""
        if random.random() > self.cfg["coin_chance"]:
            return
        if random.random() < 0.5 and not self.near_pillar(W / 2, cy):
            # посреди коридора: надо перелетать в нужный момент
            self.add_coin(W / 2, cy)
        else:
            # рядом с шипом, в верхней точке прыжка: надо прыгать точно вовремя
            self.add_coin(fx + n * (HOP_APEX + PLAYER / 2), cy if hop_cy is None else hop_cy)

    def check_landing(self):
        prect = pygame.Rect(int(self.x), int(self.y), PLAYER, PLAYER)
        for pr in self.pillars:
            if prect.colliderect(pr):
                if prect.centerx < pr.centerx:
                    return self.land(pr.left - PLAYER, -1, pr)
                return self.land(pr.right, 1, pr)
        if self.direction == 1 and self.x >= self.right_x():
            self.land(self.right_x(), -1, None)
        elif self.direction == -1 and self.x <= WALL:
            self.land(WALL, 1, None)

    def update(self, dt):
        if self.state == "dead":
            self.dead_timer += dt
            return
        if self.state != "play":
            return
        self.time += dt

        # движение по вертикали: вперёд (вверх) / назад (вниз) / стоим
        self.vy = -self.move_dir * MOVE_SPEED
        self.y += self.vy * dt
        # назад можно уйти только в пределах экрана (камера вниз не едет)
        self.y = min(self.y, self.cam_y + H * 0.85 - PLAYER)

        if self.mode == "hop":
            self.off_v -= HOP_PULL * dt
            self.off += self.off_v * dt
            if self.off <= 0:
                self.land(self.x0, self.n, self.pillar)
        elif self.mode == "cross":
            self.x += self.vx * dt
            self.check_landing()
        self.buffer = max(0.0, self.buffer - dt)

        # центральная стена закончилась (сверху или снизу) — летим на противоположную боковую
        if self.mode in ("run", "hop") and self.pillar is not None \
                and (self.y + PLAYER <= self.pillar.top or self.y >= self.pillar.bottom):
            self.start_cross(-self.n)

        # камера едет только вверх; счёт — по самой высокой точке
        self.cam_y = min(self.cam_y, self.y - H * 0.55)
        self.top_y = min(self.top_y, self.y)
        self.score = int((self.start_y - self.top_y) / 10)

        # лава поднимается; если игрок далеко ушёл вперёд, она подтягивается следом
        cfg = self.cfg
        lava_speed = min(cfg["lava_max_speed"], cfg["lava_base"] + cfg["lava_gain"] * self.score)
        self.lava_y -= lava_speed * dt
        self.lava_slack = max(0.0, self.lava_slack - LAVA_SLACK_DECAY * dt)
        self.lava_y = min(self.lava_y, self.y + PLAYER + cfg["lava_max_gap"] + self.lava_slack)

        # генерация и очистка
        self.spawn_pillars()
        self.spawn_spikes()
        self.spawn_hazards()
        limit = self.cam_y + H + 100
        self.spikes = [s for s in self.spikes if s[0].y < limit]
        self.pillars = [p for p in self.pillars if p.top < limit]
        self.coins = [c for c in self.coins if c[1] < limit]
        self.hazards = [h for h in self.hazards if h.bottom < limit]
        self.zones = [z for z in self.zones if z[1] < limit]

        # угрозы с состоянием (крошащаяся стена) и осколки
        for h in self.hazards:
            h.update(self, dt)
        self.debris = [(x + vx * dt, y + vy * dt, vx, vy + 900 * dt, life - dt)
                       for x, y, vx, vy, life in self.debris if life > dt]

        # монетки
        prect = self.player_rect().inflate(-4, -4)
        left = []
        for c in self.coins:
            coin_rect = pygame.Rect(int(c[0] - COIN_R), int(c[1] - COIN_R), COIN_R * 2, COIN_R * 2)
            if prect.colliderect(coin_rect):
                value = self.cfg["coin_value"]
                self.run_coins += value
                self.total_coins += value
                self.emit("coin", c[0], c[1], value)
                # монетка отодвигает лаву вниз
                push = self.cfg["lava_coin_push"]
                self.lava_y += push
                self.lava_slack = min(self.lava_slack + push, 3 * push)
            else:
                left.append(c)
        self.coins = left

        # шипы
        hit = self.player_rect().inflate(-6, -6)
        for rect, _ in self.spikes:
            if hit.colliderect(rect.inflate(-6, -14)):
                self.die("Шипы")
                return
        # угрозы и лава
        for h in self.hazards:
            if h.hits(self, hit):
                self.die(DEATH_TEXT.get(h.kind, "Ловушка"))
                return
        if self.y + PLAYER - 6 >= self.lava_y:
            self.die("Лава")

    def die(self, reason="Шипы"):
        self.emit("die", self.pos_x() + PLAYER / 2, self.y + PLAYER / 2)
        self.death_reason = reason
        self.state = "dead"
        self.dead_timer = 0.0
        self.best = max(self.best, self.score)
        self.bests[self.difficulty] = self.best
        self.save()

    def save(self):
        write_save(dict(bests=self.bests, coins=self.total_coins, muted=self.muted, music=self.music_level,
                        sfx=self.sfx_level, difficulty=self.difficulty))


# ---------- Управление ----------
BTN_R = 54                      # радиус экранных кнопок
BTN_DOWN = (78, H - 92)               # кнопка «назад» (внизу слева)
BTN_UP = (78, H - 92 - 140)           # кнопка «вперёд» — прямо над кнопкой «назад»
SHOW_BUTTONS = True             # на компьютере можно выключить


def in_button(pos, center):
    dx, dy = pos[0] - center[0], pos[1] - center[1]
    return dx * dx + dy * dy <= (BTN_R * 1.2) ** 2


def finger_pos(event):
    """Координаты пальца в координатах игры (учитываем масштаб и поля окна SCALED)."""
    try:
        ww, wh = pygame.display.get_window_size()
        scale = min(ww / W, wh / H)
        ox, oy = (ww - W * scale) / 2, (wh - H * scale) / 2
        return ((event.x * ww - ox) / scale, (event.y * wh - oy) / scale)
    except Exception:
        return (event.x * W, event.y * H)


def on_buttons(pos):
    return in_button(pos, BTN_UP) or in_button(pos, BTN_DOWN)


# ======================================================================
#                          ПИКСЕЛЬНАЯ ГРАФИКА
# ======================================================================
# Вся картинка рисуется на маленьком холсте CW x CH и увеличивается в PX раз
# без сглаживания — так получаются настоящие «крупные пиксели».
PX = 2
CW, CH = W // PX, H // PX         # холст 240 x 400
WALL_C = WALL // PX               # толщина боковой стены в пикселях холста
PIL_C = PILLAR_W // PX            # толщина центральной стены
TILE_H = 80                       # высота повторяющегося куска стены
SPIKE_H_C = SPIKE_H // PX
KEY = (255, 0, 255)               # «прозрачный» цвет для слоёв фона

# палитра: вулканическая пещера
P_OUT = (22, 10, 28)
P_BG_TOP = (20, 14, 44)
P_BG_BOT = (58, 22, 58)
P_ROCK_FAR = (15, 9, 32)
P_ROCK_NEAR = (30, 15, 48)
P_STONE = [(106, 50, 58), (120, 58, 62), (94, 44, 54), (128, 64, 64)]
P_CRUMBLE = [(170, 100, 66), (184, 112, 72), (158, 90, 62), (194, 122, 78)]
P_STONE_HI = (178, 98, 74)
P_STONE_LO = (64, 28, 46)
P_MORTAR = (36, 15, 32)
P_RIM = (196, 108, 66)
P_STEEL = ((58, 64, 96), (152, 164, 198), (238, 244, 255))
P_HOT = ((112, 16, 40), (234, 60, 72), (255, 178, 152))
P_WARN = ((150, 72, 20), (255, 162, 52), (255, 228, 132))
P_VIOLET = ((64, 28, 114), (152, 92, 234), (228, 194, 255))
P_BODY = (255, 206, 62)
P_BODY_SH = (230, 142, 36)
P_BODY_HI = (255, 244, 164)
P_SCARF = (234, 58, 66)
P_SCARF_SH = (160, 28, 52)
P_GLOVE = (92, 76, 122)
P_BOOT = (104, 56, 42)
P_LAVA = [(255, 236, 120), (255, 154, 42), (234, 78, 24), (170, 38, 28), (114, 24, 32)]
P_TEXT = (255, 244, 226)
P_GOLD = (255, 204, 40)
P_GOLD_HI = (255, 244, 152)
P_GOLD_LO = (208, 130, 22)
P_PANEL = (30, 16, 46)
P_PANEL_EDGE = (196, 108, 66)
P_DUST = [(190, 160, 140), (160, 128, 116), (222, 196, 170)]
P_FLAME = [(255, 236, 130), (255, 160, 40), (236, 80, 28)]

# зоны: каждые ZONE_LEN очков меняется оформление (переход плавный)
ZONE_LEN = 700
THEMES = [
    dict(name="Вулкан",
         bg_top=(20, 14, 44), bg_bot=(58, 22, 58), rock_far=(15, 9, 32), rock_near=(30, 15, 48),
         stone=[(106, 50, 58), (120, 58, 62), (94, 44, 54), (128, 64, 64)],
         hi=(178, 98, 74), lo=(64, 28, 46), mortar=(36, 15, 32), rim=(196, 108, 66),
         crystals=((74, 214, 196), (226, 96, 190)),
         embers=((255, 150, 60), (200, 96, 56), (255, 210, 120))),
    dict(name="Кристальные пещеры",
         bg_top=(10, 22, 54), bg_bot=(24, 56, 98), rock_far=(8, 16, 40), rock_near=(16, 36, 68),
         stone=[(70, 92, 132), (82, 106, 148), (60, 80, 118), (94, 120, 160)],
         hi=(150, 192, 232), lo=(34, 48, 84), mortar=(18, 28, 54), rim=(122, 202, 232),
         crystals=((130, 234, 255), (196, 156, 255)),
         embers=((150, 224, 255), (92, 152, 224), (224, 248, 255))),
    dict(name="Ядовитые недра",
         bg_top=(12, 28, 24), bg_bot=(32, 64, 42), rock_far=(8, 20, 16), rock_near=(18, 42, 30),
         stone=[(80, 102, 64), (92, 116, 72), (68, 90, 56), (102, 128, 78)],
         hi=(168, 198, 114), lo=(38, 54, 36), mortar=(20, 32, 24), rim=(172, 212, 92),
         crystals=((194, 255, 92), (255, 232, 84)),
         embers=((194, 255, 104), (122, 192, 72), (242, 255, 164))),
]


def lerp_col(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def pix_blob(surf, x, y, w, h, col):
    """Прямоугольник со срезанными углами (пиксельное скругление)."""
    pygame.draw.rect(surf, col, (x + 1, y, w - 2, h))
    pygame.draw.rect(surf, col, (x, y + 1, w, h - 2))


class Renderer:
    """Рисует игру в пиксельном стиле. Логику игры не трогает — только читает состояние Game."""

    def __init__(self):
        rnd = random.Random(7)               # свой генератор, чтобы не трогать игровой random
        self.canvas = pygame.Surface((CW, CH))
        self.big = None
        self.f_xs = pygame.font.Font(None, 13)
        self.f_s = pygame.font.Font(None, 15)
        self.f_m = pygame.font.Font(None, 20)
        self.f_l = pygame.font.Font(None, 30)
        self.f_xl = pygame.font.Font(None, 46)
        self.text_cache = {}
        self.t = 0.0
        self.camq = 0
        self.prev_camc = None
        self.shake = 0.0
        self.particles = []     # (x, y, vx, vy, life, maxlife, color, size, gravity) в мировых координатах
        self.floaters = []      # всплывающие надписи: (x, y, life, текст)
        self.embers = [[rnd.uniform(0, CW), rnd.uniform(0, CH), rnd.uniform(5, 16),
                        rnd.uniform(0, 6.28), rnd.randint(0, 2)] for _ in range(26)]
        self.bubbles = [(rnd.uniform(4, CW - 4), rnd.uniform(0, 1)) for _ in range(14)]
        self.zone = 0
        self.banner_t = 0.0
        self.banner_text = ""
        self.mix = (0, 1, 0.0)
        self.cur = THEMES[0]
        self.wall_l, self.wall_r, self.pillar_tile = [], [], []
        self.crumble_l, self.crumble_r = [], []
        self.bg_grad, self.bg_far, self.bg_near = [], [], []
        for th in THEMES:
            wl = self._wall_tile(WALL_C, "L", th)
            self.wall_l.append(wl)
            self.wall_r.append(pygame.transform.flip(wl, True, False))
            self.pillar_tile.append(self._wall_tile(PIL_C, "B", th))
            cl = self._wall_tile(WALL_C, "L", th, crumble=True, height=96)
            self.crumble_l.append(cl)
            self.crumble_r.append(pygame.transform.flip(cl, True, False))
            self.bg_grad.append(self._bg_gradient(th))
            self.bg_far.append(self._bg_layer(th, far=True))
            self.bg_near.append(self._bg_layer(th, far=False))
        self.lava_glow = self._lava_glow()
        self.coin_frames = self._coin_frames()
        self.btn = self._make_buttons()
        self.dim_main = pygame.Surface((CW, CH), pygame.SRCALPHA)
        self.dim_main.fill((12, 6, 20, 80))
        self.dim_sub = pygame.Surface((CW, CH), pygame.SRCALPHA)
        self.dim_sub.fill((12, 6, 20, 175))

    # ------------------------------------------------------------------
    # заготовки картинок (рисуются один раз)
    # ------------------------------------------------------------------
    def _wall_tile(self, width, edge, th, crumble=False, height=TILE_H):
        rnd = random.Random(31 + width + (5 if crumble else 0))
        s = pygame.Surface((width, height))
        s.fill(th["mortar"])
        if crumble:
            pal = [lerp_col(col, (255, 222, 160), 0.38) for col in th["stone"]]
            hi = lerp_col(th["hi"], (255, 240, 200), 0.4)
            lo = lerp_col(th["lo"], (140, 90, 70), 0.5)
        else:
            pal, hi, lo = th["stone"], th["hi"], th["lo"]
        bh, bw = (12 if crumble else 10), 10
        for r in range(height // bh):
            y = r * bh
            x = -(bw // 2) if r % 2 else 0
            while x < width:
                x0, x1 = max(x + 1, 0), min(x + bw, width)
                if x1 - x0 > 0:
                    col = rnd.choice(pal)
                    pygame.draw.rect(s, col, (x0, y + 1, x1 - x0, bh - 1))
                    pygame.draw.rect(s, hi, (x0, y + 1, x1 - x0, 1))
                    pygame.draw.rect(s, lo, (x0, y + bh - 1, x1 - x0, 1))
                    if x + 1 >= 0:
                        pygame.draw.rect(s, hi, (x + 1, y + 1, 1, bh - 1))
                    if x + bw <= width:
                        pygame.draw.rect(s, lo, (x + bw - 1, y + 1, 1, bh - 1))
                    for _ in range(3):      # крапинки
                        sx_, sy_ = rnd.randint(x0, x1 - 1), rnd.randint(y + 2, y + bh - 2)
                        pygame.draw.rect(s, rnd.choice((hi, lo, col)), (sx_, sy_, 1, 1))
                x += bw
        if crumble:                          # трещины
            for k in range(3):
                x = rnd.randint(2, width - 3)
                y = rnd.randint(0, height - 20)
                pts = [(x, y)]
                for _ in range(4):
                    x += rnd.randint(-2, 2)
                    y += rnd.randint(3, 6)
                    pts.append((max(0, min(width - 1, x)), y))
                pygame.draw.lines(s, P_OUT, False, pts, 1)
        # внутренняя кромка: тёмный контур и тёплая подсветка
        cols = [width - 1] if edge == "L" else [0, width - 1]
        for cx in cols:
            pygame.draw.rect(s, P_OUT, (cx, 0, 1, height))
            rim = cx - 1 if cx == width - 1 else cx + 1
            for y in range(0, height, 2):
                pygame.draw.rect(s, th["rim"], (rim, y, 1, 1))
        return s

    def _bg_gradient(self, th):
        s = pygame.Surface((CW, CH))
        bands = 20
        cols = [lerp_col(th["bg_top"], th["bg_bot"], i / (bands - 1)) for i in range(bands)]
        for i in range(bands):
            y0, y1 = int(i * CH / bands), int((i + 1) * CH / bands)
            pygame.draw.rect(s, cols[i], (0, y0, CW, y1 - y0))
            if i:                            # дизеринг на границе полос
                for x in range(0, CW, 2):
                    pygame.draw.rect(s, cols[i - 1], (x + 1, y0, 1, 1))
                    pygame.draw.rect(s, cols[i - 1], (x, y0 + 1, 1, 1))
        return s

    def _bg_layer(self, th, far):
        rnd = random.Random(1 if far else 2)       # одинаковая форма скал во всех зонах
        bgh = 480 if far else 400
        s = pygame.Surface((CW, bgh))
        s.fill(KEY)
        s.set_colorkey(KEY)
        col = th["rock_far"] if far else th["rock_near"]
        for _ in range(9 if far else 11):
            w = rnd.randint(18, 46) if far else rnd.randint(10, 26)
            x = rnd.randint(WALL_C - 4, CW - WALL_C - w + 4)
            y = rnd.randint(0, bgh - 1)
            h = rnd.randint(80, 190) if far else rnd.randint(36, 100)
            left, right = [], []
            for k in range(7):
                yy = y + h * k // 6
                left.append((x + rnd.randint(-3, 3), yy))
                right.append((x + w + rnd.randint(-3, 3), yy))
            pts = left + right[::-1]
            for dy in (0, -bgh):
                pygame.draw.polygon(s, col, [(px_, py_ + dy) for px_, py_ in pts])
        if not far:                          # светящиеся кристаллы
            for _ in range(9):
                cx, cy = rnd.randint(WALL_C + 6, CW - WALL_C - 6), rnd.randint(0, bgh - 1)
                tone = rnd.choice(th["crystals"])
                dark = lerp_col(tone, P_OUT, 0.55)
                for k in range(rnd.randint(2, 3)):
                    bx = cx + k * 3 - 2
                    hh = rnd.randint(5, 10)
                    pygame.draw.polygon(s, dark, [(bx, cy), (bx + 3, cy), (bx + 1, cy - hh)])
                    pygame.draw.line(s, tone, (bx + 1, cy - 1), (bx + 1, cy - hh + 1), 1)
        return s

    def _lava_glow(self):
        s = pygame.Surface((CW, 22), pygame.SRCALPHA)
        for dy in range(22):
            for x in range(CW):
                if dy >= 17:
                    on = (x + dy) % 2 == 0
                elif dy >= 11:
                    on = x % 2 == 0 and dy % 2 == 0
                elif dy >= 5:
                    on = x % 4 == 0 and dy % 4 == 1
                else:
                    on = False
                if on:
                    pygame.draw.rect(s, (255, 130, 44), (x, dy, 1, 1))
        return s

    def _coin_frames(self):
        frames = []
        for w in (11, 9, 6, 3, 6, 9):
            s = pygame.Surface((11, 11), pygame.SRCALPHA)
            x = 5 - w // 2
            pygame.draw.ellipse(s, P_OUT, (x, 0, w, 11))
            if w >= 3:
                pygame.draw.ellipse(s, P_GOLD_LO, (x + 1, 1, w - 2, 9))
                pygame.draw.ellipse(s, P_GOLD, (x + 1, 1, max(1, w - 3), 8))
            if w >= 6:
                pygame.draw.rect(s, P_GOLD_HI, (x + 2, 2, 1, 3))
            if w >= 9:
                pygame.draw.rect(s, P_GOLD_LO, (4, 4, 3, 3))
                pygame.draw.rect(s, P_GOLD_HI, (5, 5, 1, 1))
            frames.append(s)
        return frames

    def _make_buttons(self):
        r = BTN_R // PX
        out = {}
        for up in (True, False):
            for pressed in (False, True):
                s = pygame.Surface((2 * r + 1, 2 * r + 1), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 244, 226, 150 if pressed else 70), (r, r), r)
                pygame.draw.circle(s, (255, 244, 226, 220), (r, r), r, 2)
                k = 9
                pts = ([(r, r - k), (r - k, r + 5), (r + k, r + 5)] if up
                       else [(r, r + k), (r - k, r - 5), (r + k, r - 5)])
                pygame.draw.polygon(s, (22, 10, 28, 235), pts)
                inner = ([(r, r - k + 3), (r - k + 4, r + 3), (r + k - 4, r + 3)] if up
                         else [(r, r + k - 3), (r - k + 4, r - 3), (r + k - 4, r - 3)])
                pygame.draw.polygon(s, (255, 244, 226, 255 if pressed else 200), inner)
                out[(up, pressed)] = s
        return out

    # ------------------------------------------------------------------
    # вспомогательное
    # ------------------------------------------------------------------
    def sx(self, x):
        return int(math.floor(x / PX))

    def sy(self, y):
        return int(math.floor((y - self.camq) / PX))

    def text(self, s, font, color, x, y, align="center"):
        key = (s, id(font), color)
        img = self.text_cache.get(key)
        if img is None:
            if len(self.text_cache) > 300:
                self.text_cache.clear()
            base = font.render(s, False, color)
            dark = font.render(s, False, P_OUT)
            w, h = base.get_size()
            img = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2), (0, 2), (2, 2), (0, 0), (2, 0)):
                img.blit(dark, (dx, dy))
            img.blit(base, (1, 1))
            self.text_cache[key] = img
        w, h = img.get_size()
        if align == "center":
            x -= w // 2
        elif align == "right":
            x -= w
        self.canvas.blit(img, (int(x), int(y - h // 2)))

    def text_fit(self, s, fonts, color, x, y, maxw):
        """Нарисовать текст самым крупным из шрифтов, который влезает в maxw."""
        for font in fonts:
            if font.size(s)[0] + 2 <= maxw:
                break
        self.text(s, font, color, x, y)

    def panel(self, x, y, w, h):
        c = self.canvas
        pix_blob(c, x, y, w, h, P_OUT)
        pix_blob(c, x + 1, y + 1, w - 2, h - 2, P_PANEL_EDGE)
        pix_blob(c, x + 2, y + 2, w - 4, h - 4, P_PANEL)
        for cx, cy in ((x + 4, y + 4), (x + w - 5, y + 4), (x + 4, y + h - 5), (x + w - 5, y + h - 5)):
            pygame.draw.rect(c, P_STONE_HI, (cx, cy, 1, 1))

    # ------------------------------------------------------------------
    # эффекты (частицы)
    # ------------------------------------------------------------------
    def burst_particles(self, x, y, count, palette, speed, life, grav=0.0, size=(1, 2), dirx=None, spread=1.0):
        for _ in range(count):
            if dirx is None:
                ang = random.uniform(0, 6.2832)
                sp = random.uniform(0.3, 1.0) * speed
                vx, vy = math.cos(ang) * sp, math.sin(ang) * sp
            else:
                vx = dirx * random.uniform(0.3, 1.0) * speed + random.uniform(-20, 20) * spread
                vy = random.uniform(-40, 30) * spread
            ml = life * random.uniform(0.7, 1.2)
            self.particles.append((x + random.uniform(-4, 4), y + random.uniform(-4, 4), vx, vy,
                                   ml, ml, random.choice(palette), random.randint(size[0], size[1]), grav))

    def update(self, g, dt):
        self.t += dt
        for ev in g.events:
            kind = ev[0]
            if kind == "hop":
                self.burst_particles(ev[1] - ev[3] * PLAYER / 2, ev[2] + PLAYER / 2, 6, P_DUST, 70, 0.35, dirx=ev[3])
            elif kind == "land":
                self.burst_particles(ev[1] - ev[3] * PLAYER / 2, ev[2] + PLAYER / 2, 8, P_DUST, 90, 0.4, dirx=ev[3])
            elif kind == "cross":
                self.burst_particles(ev[1], ev[2], 8, P_FLAME, 60, 0.3, dirx=-ev[3], spread=2.0)
            elif kind == "coin":
                self.burst_particles(ev[1], ev[2], 12, (P_GOLD, P_GOLD_HI, (255, 255, 255)), 120, 0.5)
                self.floaters.append((ev[1], ev[2], 0.8, "+%d" % (ev[3] if len(ev) > 3 else 1)))
            elif kind == "die":
                self.burst_particles(ev[1], ev[2], 34, (P_BODY, P_BODY_SH, P_SCARF, (255, 255, 255)),
                                     220, 0.9, grav=320, size=(1, 3))
                self.shake = 7.0
            elif kind == "crumble":
                self.burst_particles(ev[1], ev[2], 16, P_CRUMBLE, 150, 0.8, grav=420, size=(1, 3))
                self.shake = 4.0
        del g.events[:]
        # лавовые искры
        if g.lava_y - g.cam_y < H and random.random() < 0.5:
            self.particles.append((random.uniform(WALL, W - WALL), g.lava_y, random.uniform(-14, 14),
                                   random.uniform(-110, -50), 1.1, 1.1,
                                   random.choice(P_FLAME), 1, -30.0))
        self.particles = [(x + vx * dt, y + vy * dt, vx, vy + gr * dt, life - dt, ml, col, sz, gr)
                          for (x, y, vx, vy, life, ml, col, sz, gr) in self.particles if life > dt]
        self.floaters = [(x, y - 26 * dt, life - dt, s) for (x, y, life, s) in self.floaters if life > dt]
        # парящие искры фона
        camc = int(math.floor(g.cam_y / PX))
        shift = 0 if self.prev_camc is None else (self.prev_camc - camc) * 0.6
        self.prev_camc = camc
        for e in self.embers:
            e[1] += -e[2] * dt + shift
            e[0] += math.sin(self.t * 1.3 + e[3]) * 9 * dt
            if e[1] < -2 or e[1] > CH + 2:
                e[1] = CH + 2 if e[1] < 0 else -2
                e[0] = random.uniform(WALL_C, CW - WALL_C)
        self.shake = max(0.0, self.shake - 22 * dt)
        # смена зоны
        zone = 0 if g.state == "menu" else g.score // ZONE_LEN
        if zone > self.zone and g.state == "play":
            self.banner_t = 3.0
            self.banner_text = THEMES[zone % len(THEMES)]["name"]
        self.zone = zone
        self.banner_t = max(0.0, self.banner_t - dt)

    # ------------------------------------------------------------------
    # отрисовка кадра
    # ------------------------------------------------------------------
    def draw(self, g, up=False, down=False, ui=None):
        c = self.canvas
        self.camq = int(math.floor(g.cam_y / PX)) * PX
        camc = self.camq // PX
        self.mix = self._mix(g)
        self.cur = THEMES[self.mix[0]]
        self._themed(self.bg_grad, (0, 0))
        self._layer(self.bg_far, camc, 0.18)
        self._layer(self.bg_near, camc, 0.40)
        for ex, ey, _, _, ci in self.embers:
            pygame.draw.rect(c, self.cur["embers"][ci], (int(ex), int(ey), 1, 1))
        self._walls(camc)
        for pr in g.pillars:
            self._pillar(pr, camc)
        for h in g.hazards:
            getattr(self, "_hz_" + h.kind)(h, g)
        for rect, n in g.spikes:
            self._spike(rect.left if n == 1 else rect.right, n, rect.y, SPIKE_W, P_STEEL)
        for x, y, *_ in g.debris:
            pygame.draw.rect(c, P_CRUMBLE[int(x) % 4], (self.sx(x), self.sy(y), 3, 3))
        for x, y in g.coins:
            self._coin(x, y)
        self._particles()
        if g.state != "menu":
            self._player(g)
            self._lava(g)
        self._floaters()
        self._hud(g)
        if g.state == "menu":
            self._menu(g, ui)
        elif g.state == "dead":
            self._dead(g, ui)
        if SHOW_BUTTONS and g.state == "play":
            r = BTN_R // PX
            c.blit(self.btn[(True, bool(up))], (BTN_UP[0] // PX - r, BTN_UP[1] // PX - r))
            c.blit(self.btn[(False, bool(down))], (BTN_DOWN[0] // PX - r, BTN_DOWN[1] // PX - r))

    def present(self, screen):
        if self.shake > 0.5:
            if self.big is None:
                self.big = pygame.Surface((W, H))
            pygame.transform.scale(self.canvas, (W, H), self.big)
            amp = int(self.shake)
            screen.fill(P_OUT)
            screen.blit(self.big, (random.randint(-amp, amp), random.randint(-amp, amp)))
        else:
            pygame.transform.scale(self.canvas, (W, H), screen)

    # ---------- фон и стены ----------
    def _mix(self, g):
        """Какая тема сейчас, какая следующая и насколько уже идёт переход (0..1)."""
        score = 0 if g.state == "menu" else g.score
        zone = score // ZONE_LEN
        a, b = zone % len(THEMES), (zone + 1) % len(THEMES)
        p = (score % ZONE_LEN) / ZONE_LEN
        return a, b, max(0.0, min(1.0, (p - 0.8) / 0.2))

    def _themed(self, tiles, pos):
        """Нарисовать картинку текущей темы и поверх неё (с прозрачностью) картинку следующей."""
        a, b, f = self.mix
        self.canvas.blit(tiles[a], pos)
        if f > 0.02:
            t = tiles[b]
            t.set_alpha(int(255 * f))
            self.canvas.blit(t, pos)
            t.set_alpha(255)

    def _layer(self, tiles, camc, factor):
        a, b, f = self.mix
        tile = tiles[a if f < 0.5 else b]
        h = tile.get_height()
        off = int(camc * factor) % h
        self.canvas.blit(tile, (0, -off))
        self.canvas.blit(tile, (0, -off + h))

    def _walls(self, camc):
        y = (-camc) % TILE_H - TILE_H
        while y < CH:
            self._themed(self.wall_l, (0, y))
            self._themed(self.wall_r, (CW - WALL_C, y))
            y += TILE_H

    def _pillar(self, pr, camc):
        c = self.canvas
        th = self.cur
        x = pr.x // PX
        yt, yb = self.sy(pr.top), self.sy(pr.bottom)
        if yb < -8 or yt > CH + 8:
            return
        c.set_clip(pygame.Rect(x, yt, PIL_C, max(1, yb - yt)))
        y = (-camc) % TILE_H - TILE_H
        while y < CH:
            self._themed(self.pillar_tile, (x, y))
            y += TILE_H
        c.set_clip(None)
        # верхний и нижний края: тупые каменные «шапки» (без острых зубцов, чтобы не путать с шипами)
        for yy in (yt - 2, yb - 2):
            pix_blob(c, x - 3, yy - 1, PIL_C + 6, 6, P_OUT)
            pix_blob(c, x - 2, yy, PIL_C + 4, 4, th["stone"][2])
            pygame.draw.rect(c, th["hi"], (x - 1, yy, PIL_C + 2, 1))
            pygame.draw.rect(c, th["lo"], (x - 1, yy + 3, PIL_C + 2, 1))
            for k in range(2):
                pygame.draw.rect(c, th["lo"], (x + 3 + k * 8, yy + 1, 2, 1))

    # ---------- шипы и угрозы ----------
    def _spike(self, fx, n, top, length, pal, plate=True):
        c = self.canvas
        fxc, tc = fx // PX, self.sy(top)
        hh = SPIKE_H_C
        if tc > CH or tc + hh < 0:
            return
        dark, mid, light = pal
        if plate:       # металлическая пластина на стене с гнездом
            px_ = fxc - 4 if n == 1 else fxc
            pygame.draw.rect(c, P_OUT, (px_, tc + 1, 4, hh - 2))
            pygame.draw.rect(c, pal[1] if pal is not P_STEEL else (110, 120, 154), (px_ + 1, tc + 2, 2, hh - 4))
            pygame.draw.rect(c, P_OUT, (px_ + 1, tc + hh // 2 - 2, 2, 4))
            pygame.draw.rect(c, light, (px_ + 1, tc + 2, 1, 1))
            pygame.draw.rect(c, light, (px_ + 1, tc + hh - 3, 1, 1))
        lc = int(length) // PX
        if lc < 2:
            return
        pygame.draw.polygon(c, P_OUT, [(fxc, tc), (fxc + n * lc, tc + hh // 2), (fxc, tc + hh - 1)])
        if lc >= 5:
            pygame.draw.polygon(c, mid, [(fxc, tc + 2), (fxc + n * (lc - 3), tc + hh // 2), (fxc, tc + hh - 3)])
            pygame.draw.polygon(c, dark, [(fxc, tc + hh // 2), (fxc + n * (lc - 3), tc + hh // 2),
                                          (fxc, tc + hh - 3)])
            pygame.draw.line(c, light, (fxc + n, tc + 3), (fxc + n * (lc - 4), tc + hh // 2 - 1), 1)

    def _hz_pulse(self, h, g):
        e = h.ext(g.time)
        for i in range(h.count):
            top = h.y - i * CLUSTER_GAP
            self._spike(h.fx, h.n, top, max(0, SPIKE_W * e), P_HOT if e >= 0.6 else P_WARN)
            if 0.02 < e < 0.6 and int(self.t * 10) % 2 == 0:       # мигающий кончик-предупреждение
                tc = self.sy(top) + SPIKE_H_C // 2
                pygame.draw.rect(self.canvas, P_WARN[2], (h.fx // PX + h.n * 4 - 1, tc - 1, 2, 2))

    def _hz_slide(self, h, g):
        c = self.canvas
        fxc = h.fx // PX
        y0, y1 = self.sy(h.top), self.sy(h.bottom)
        gx = fxc if h.n == 1 else fxc - 2
        pygame.draw.rect(c, P_OUT, (gx, y0, 2, y1 - y0))
        for yy in range(y0 + 2, y1, 8):
            pygame.draw.rect(c, P_RIM, (gx, yy, 1, 1))
        for yy in (y0, y1 - 2):
            pygame.draw.rect(c, P_VIOLET[1], (gx - 1 if h.n == 1 else gx, yy, 3, 2))
        self._spike(h.fx, h.n, h.pos_y(g.time), SPIKE_W, P_VIOLET)

    def _hz_saw(self, h, g):
        c = self.canvas
        sy_ = self.sy(h.y)
        for x in range(WALL_C + 2, CW - WALL_C - 2, 6):                 # пунктир-рельса
            pygame.draw.rect(c, (92, 40, 60), (x, sy_, 3, 1))
        cx = self.sx(h.pos_x(g.time))
        ang = g.time * 9
        r_out, r_in = h.R // PX + 2, h.R // PX - 3
        def ring(ro, ri, col, teeth=12):
            pts = []
            for i in range(teeth * 2):
                r = ro if i % 2 == 0 else ri
                a = ang + i * math.pi / teeth
                pts.append((cx + int(round(r * math.cos(a))), sy_ + int(round(r * math.sin(a)))))
            pygame.draw.polygon(c, col, pts)
        ring(r_out + 1, r_in + 1, P_OUT)
        ring(r_out, r_in, P_STEEL[1])
        pygame.draw.circle(c, P_STEEL[0], (cx, sy_), r_in - 1)
        pygame.draw.circle(c, P_STEEL[2], (cx, sy_), 3)
        pygame.draw.circle(c, P_OUT, (cx, sy_), 1)

    def _warn_sign(self, x, y):
        c = self.canvas
        pygame.draw.polygon(c, P_OUT, [(x - 8, y + 7), (x + 8, y + 7), (x, y - 8)])
        pygame.draw.polygon(c, P_WARN[1], [(x - 6, y + 6), (x + 6, y + 6), (x, y - 5)])
        pygame.draw.rect(c, P_OUT, (x - 1, y - 2, 2, 5))
        pygame.draw.rect(c, P_OUT, (x - 1, y + 4, 2, 1))

    def _hz_fire(self, h, g):
        c = self.canvas
        st, u = h.state(g.time)
        sy_ = self.sy(h.y)
        if st == "warn":
            for x in range(WALL_C + 3, CW - WALL_C - 3, 5):           # предупреждающий пунктир
                pygame.draw.rect(c, (150, 60, 50), (x, sy_, 2, 1))
            if int(u * 8) % 2 == 0:
                x0 = WALL_C + 10 if h.dir == 1 else CW - WALL_C - 10
                self._warn_sign(x0, sy_)
        elif st == "fly":
            x = self.sx(h.pos_x(u))
            for k in range(1, 5):
                tx = x - h.dir * k * 5
                ty = sy_ + int(round(math.sin(self.t * 25 + k) * 1.5))
                pygame.draw.circle(c, P_FLAME[2] if k > 2 else P_FLAME[1], (tx, ty), max(1, 6 - k))
            fl = 1 if int(self.t * 20) % 2 else 0
            pygame.draw.circle(c, P_OUT, (x, sy_), 7 + fl)
            pygame.draw.circle(c, P_FLAME[2], (x, sy_), 6 + fl)
            pygame.draw.circle(c, P_FLAME[1], (x, sy_), 4)
            pygame.draw.circle(c, P_FLAME[0], (x, sy_), 2)

    def _hz_crumble(self, h, g):
        c = self.canvas
        x = 0 if h.n == 1 else CW - WALL_C
        y0 = self.sy(h.ctop)
        hc = h.h // PX
        if y0 > CH or y0 + hc < 0:
            return
        if h.state == "broken":
            pygame.draw.rect(c, (14, 6, 18), (x, y0, WALL_C, hc))
            edge = WALL_C - 1 if h.n == 1 else 0
            pygame.draw.rect(c, P_OUT, (x + edge, y0, 1, hc))
            for k in range(0, hc, 5):                                  # неровные края дыры
                pygame.draw.rect(c, self.cur["stone"][k % 4], (x + (0 if h.n == 1 else WALL_C - 3), y0 + k, 3, 2))
                pygame.draw.rect(c, self.cur["stone"][(k + 1) % 4], (x + (WALL_C - 3 if h.n == 1 else 0), y0 + k + 2, 3, 2))
            return
        if h.timer > 0 and int(g.time * 40) % 2:
            x += 1
        tile = (self.crumble_l if h.n == 1 else self.crumble_r)[self.mix[0]]
        c.blit(tile, (x, y0), (0, 0, WALL_C, hc))
        pygame.draw.rect(c, P_OUT, (x, y0, WALL_C, 1))
        pygame.draw.rect(c, P_OUT, (x, y0 + hc - 1, WALL_C, 1))
        prog = min(1.0, h.timer / h.limit)
        for k in range(int(prog * 6)):                                  # трещин всё больше
            yy = y0 + 4 + k * (hc // 6)
            pygame.draw.line(c, P_OUT, (x + 2, yy), (x + WALL_C - 3, yy + 4 + (k % 2) * 3), 1)

    # ---------- мелочи ----------
    def _coin(self, x, y):
        idx = int(self.t * 9 + x * 0.02) % 6
        cx, cy = self.sx(x), self.sy(y)
        self.canvas.blit(self.coin_frames[idx], (cx - 5, cy - 5))
        if int(self.t * 3 + x * 0.05) % 6 == 0:                          # блик
            pygame.draw.rect(self.canvas, (255, 255, 255), (cx + 3, cy - 5, 1, 3))
            pygame.draw.rect(self.canvas, (255, 255, 255), (cx + 2, cy - 4, 3, 1))

    def _particles(self):
        c = self.canvas
        for x, y, _, _, life, ml, col, sz, _ in self.particles:
            k = life / ml
            if k < 0.35:
                col = lerp_col(P_BG_BOT, col, k / 0.35)
            pygame.draw.rect(c, col, (self.sx(x), self.sy(y), sz, sz))

    def _floaters(self):
        for x, y, life, s in self.floaters:
            self.text(s, self.f_m, P_GOLD_HI, self.sx(x), self.sy(y) - 8)

    # ---------- игрок ----------
    def _player(self, g, at=None):
        c = self.canvas
        px, py = at if at else (self.sx(g.pos_x()), self.sy(g.y))
        f = g.direction if g.mode == "cross" else g.n          # куда смотрит (в сторону пустоты)
        t = self.t
        dead = g.state == "dead"
        moving = g.state == "play" and g.move_dir != 0
        bob = 1 if (g.mode == "run" and not moving and not dead and int(t * 2.2) % 2) else 0

        def R(col, dx, dy, w, h):
            x = px + dx if f == 1 else px + 17 - dx - w
            pygame.draw.rect(c, col, (x, py + dy, w, h))

        def B(col, dx, dy, w, h):
            R(col, dx + 1, dy, w - 2, h)
            R(col, dx, dy + 1, w, h - 2)

        body = P_BODY if not dead else (196, 176, 156)
        shade = P_BODY_SH if not dead else (146, 126, 114)
        # шарф
        if g.mode == "cross":
            w = 1 if int(t * 24) % 2 else 0
            R(P_SCARF, -3, 9 + w, 3, 2)
            R(P_SCARF_SH, -6, 10 - w, 3, 2)
            R(P_SCARF, -9, 9 + w, 3, 2)
            for k, yy in enumerate((3, 13)):
                R((255, 222, 170), -5 - k * 4, yy, 4, 1)
        else:
            sway = 1 if int(t * 5) % 2 else 0
            R(P_SCARF, -1, 10 + bob, 2, 3 + sway)
            R(P_SCARF_SH, -1, 13 + bob + sway, 2, 2)
        # ботинки
        ph = int(t * 7) % 2
        if g.mode == "hop":
            R(P_BOOT, 3, 14, 4, 2)
            R(P_BOOT, 9, 14, 4, 2)
        else:
            lift = 1 if (moving and g.mode == "run") else 0
            R(P_BOOT, 3, 15 - (lift if ph else 0), 4, 2)
            R(P_BOOT, 9, 15 - (lift if not ph else 0), 4, 2)
        # тело
        B(P_OUT, 1, 1 + bob, 15, 14)
        B(body, 2, 2 + bob, 13, 12)
        R(shade, 3, 12 + bob, 11, 2)
        R(shade, 13, 4 + bob, 1, 8)
        R(P_BODY_HI if not dead else (226, 210, 190), 4, 3 + bob, 3, 1)
        R(P_BODY_HI if not dead else (226, 210, 190), 3, 4 + bob, 1, 2)
        # повязка
        R(P_SCARF, 2, 9 + bob, 13, 2)
        R(P_SCARF_SH, 2, 11 + bob, 13, 1)
        # клюв и хохолок
        if not dead:
            R(P_OUT, 15, 6, 3, 4)
            R((255, 150, 42), 15, 7, 2, 2)
        R(P_OUT, 7, -1 + bob, 4, 2)
        R(body, 8, 0 + bob, 2, 1)
        # глаз
        if dead:
            for dx, dy in ((9, 4), (10, 5), (11, 6), (12, 7), (12, 4), (11, 5), (10, 6), (9, 7)):
                R(P_OUT, dx, dy + bob, 1, 1)
        else:
            R((255, 255, 255), 9, 4 + bob, 4, 5)
            look = 0 if g.move_dir == 1 else (3 if g.move_dir == -1 else 1)
            R(P_OUT, 11 if g.mode != "cross" else 12, 4 + look + bob, 2, 2 if look != 1 else 3)
        # руки в перчатках
        if g.mode == "cross":
            R(P_GLOVE, 14, 1, 3, 3)
            R(P_GLOVE, 14, 11, 3, 3)
        else:
            if g.mode == "hop":
                ya, yb = 1, 5
            elif moving:
                ya, yb = (3, 9) if ph == 0 else (6, 12)
            else:
                ya, yb = 4, 10
            for yy in (ya, yb):
                R(P_OUT, -1, yy - 1, 4, 5)
                R(P_GLOVE, 0, yy, 3, 3)
                R((150, 132, 182), 1, yy, 1, 1)

    # ---------- лава ----------
    def _lava(self, g):
        c = self.canvas
        top = self.sy(g.lava_y)
        if top >= CH:
            return
        c.blit(self.lava_glow, (0, top - 22))
        for x in range(0, CW, 2):
            h = int(round(2.0 * math.sin(x * 0.12 + self.t * 2.4) + 1.4 * math.sin(x * 0.27 - self.t * 1.9)))
            y0 = top + h
            pygame.draw.rect(c, P_LAVA[0], (x, y0, 2, 2))
            pygame.draw.rect(c, P_LAVA[1], (x, y0 + 2, 2, 4))
            pygame.draw.rect(c, P_LAVA[2], (x, y0 + 6, 2, 9))
            pygame.draw.rect(c, P_LAVA[3], (x, y0 + 15, 2, 12))
            pygame.draw.rect(c, P_LAVA[4], (x, y0 + 27, 2, CH))
        for bx, ph in self.bubbles:                                        # пузыри
            p = (self.t * 0.5 + ph) % 1.0
            by = top + 14 - int(p * 12)
            if p < 0.85:
                pygame.draw.rect(c, P_LAVA[0], (int(bx), by, 2, 2))
            else:
                pygame.draw.circle(c, P_LAVA[0], (int(bx), top + 2), 3, 1)

    # ---------- интерфейс ----------
    def _hud(self, g):
        c = self.canvas
        if g.state != "menu":
            self.text(str(g.score), self.f_l, P_TEXT, CW // 2, 20)
            if g.difficulty != "normal" and g.state == "play":
                self.text(g.cfg["name"], self.f_xs, (255, 120, 120), WALL_C + 6, 33, align="left")
        self._speaker(g.muted)
        c.blit(self.coin_frames[int(self.t * 9) % 6], (WALL_C + 6, 8))
        self.text(str(g.total_coins), self.f_m, P_GOLD_HI, WALL_C + 21, 14, align="left")
        if g.state == "play" and g.lava_y - (g.y + PLAYER) < 150 and int(self.t * 6) % 2 == 0:
            self._warn_sign(CW // 2 - 52, 48)
            self._warn_sign(CW // 2 + 52, 48)
            self.text("ЛАВА БЛИЗКО!", self.f_m, (255, 130, 90), CW // 2, 48)
        if self.banner_t > 0 and g.state == "play":
            self.text("ЗОНА %d" % (self.zone + 1), self.f_s, P_TEXT, CW // 2, 70)
            self.text_fit(self.banner_text, (self.f_l, self.f_m, self.f_s), self.cur["rim"],
                          CW // 2, 90, CW - 2 * WALL_C - 8)

    def _speaker(self, muted):
        c = self.canvas
        cx, cy = SPK_POS[0] // PX, SPK_POS[1] // PX

        def shape(dx, dy, col):
            pygame.draw.rect(c, col, (cx - 6 + dx, cy - 2 + dy, 3, 5))
            pygame.draw.polygon(c, col, [(cx - 3 + dx, cy - 2 + dy), (cx + 1 + dx, cy - 6 + dy),
                                         (cx + 1 + dx, cy + 6 + dy), (cx - 3 + dx, cy + 3 + dy)])
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shape(dx, dy, P_OUT)
        shape(0, 0, P_TEXT)
        if muted:
            for a, b in (((cx + 3, cy - 4), (cx + 9, cy + 4)), ((cx + 9, cy - 4), (cx + 3, cy + 4))):
                pygame.draw.line(c, P_OUT, a, b, 3)
            for a, b in (((cx + 3, cy - 4), (cx + 9, cy + 4)), ((cx + 9, cy - 4), (cx + 3, cy + 4))):
                pygame.draw.line(c, P_SCARF, a, b, 1)
        else:
            for x, h in ((cx + 4, 2), (cx + 7, 4)):
                pygame.draw.rect(c, P_OUT, (x - 1, cy - h - 1, 3, 2 * h + 3))
                pygame.draw.rect(c, P_TEXT, (x, cy - h, 1, 2 * h + 1))

    def _button(self, rect, label, font=None, selected=False, pressed=False, accent=None):
        """Пиксельная кнопка по прямоугольнику rect (в координатах игры)."""
        c = self.canvas
        x, y, w, h = rect.x // PX, rect.y // PX, rect.w // PX, rect.h // PX
        if pressed:
            y += 1
        base = accent or ((200, 110, 52) if selected else (74, 42, 84))
        if selected:
            pix_blob(c, x - 2, y - 2, w + 4, h + 4, P_GOLD)
        pix_blob(c, x, y + 1, w, h, P_OUT)
        pix_blob(c, x, y, w, h, P_OUT)
        pix_blob(c, x + 1, y + 1, w - 2, h - 2, lerp_col(base, P_OUT, 0.45))
        pix_blob(c, x + 1, y + 1, w - 2, h - 4, base)
        pygame.draw.rect(c, lerp_col(base, (255, 255, 255), 0.4), (x + 3, y + 2, w - 6, 1))
        self.text_fit(label, ((font or self.f_m), self.f_s, self.f_xs), P_TEXT if not selected else (255, 252, 230),
                      x + w // 2, y + h // 2, w - 8)

    def _slider(self, name, label, value, color, dragging):
        """Ползунок громкости: подпись, процент, дорожка и ручка."""
        c = self.canvas
        r = SETTINGS_RECTS[name]
        x0, x1 = SLIDER_X0 // PX, SLIDER_X1 // PX
        top = r.y // PX
        cy = top + 20
        self.text(label, self.f_m, P_TEXT, x0, top + 4, align="left")
        self.text("%d%%" % round(value * 100), self.f_m, P_GOLD_HI, x1, top + 4, align="right")
        pix_blob(c, x0 - 3, cy - 5, x1 - x0 + 6, 11, P_OUT)
        pix_blob(c, x0 - 2, cy - 4, x1 - x0 + 4, 9, (52, 28, 60))
        fx = x0 + int((x1 - x0) * value)
        if fx > x0:
            pix_blob(c, x0 - 2, cy - 4, fx - x0 + 4, 9, color)
            pygame.draw.rect(c, lerp_col(color, (255, 255, 255), 0.45), (x0 - 1, cy - 3, max(1, fx - x0 + 2), 1))
        for k in range(1, 4):                                           # засечки 25 / 50 / 75 %
            pygame.draw.rect(c, P_OUT, (x0 + (x1 - x0) * k // 4, cy + 6, 1, 3))
        knob = (255, 244, 200) if dragging else (236, 226, 208)
        pix_blob(c, fx - 5, cy - 10, 11, 21, P_OUT)
        pix_blob(c, fx - 4, cy - 9, 9, 19, knob)
        pygame.draw.rect(c, lerp_col(knob, P_OUT, 0.4), (fx - 3, cy + 6, 7, 2))
        for k in (-1, 0, 1):
            pygame.draw.rect(c, lerp_col(knob, P_OUT, 0.5), (fx + k * 2, cy - 4, 1, 8))

    def _menu(self, g, ui):
        screen = ui.screen if ui else "main"
        self.canvas.blit(self.dim_main if screen == "main" else self.dim_sub, (0, 0))
        {"main": self._menu_main, "settings": self._menu_settings, "howto": self._menu_howto}[screen](g, ui)

    def _menu_main(self, g, ui):
        pressed = ui.pressed if ui else None
        bob = int(round(2 * math.sin(self.t * 2.0)))
        for word, y in (("WALL", 44), ("CLIMBERS", 76)):
            self.text(word, self.f_xl, P_LAVA[3], CW // 2, y + bob + 2)
            self.text(word, self.f_xl, P_LAVA[1], CW // 2, y + bob)
        self._player(_Pose(1), (WALL_C, 104 + bob))                      # птенцы-талисманы на стенах
        self._player(_Pose(-1), (CW - WALL_C - 17, 108 - bob))
        self.text("СЛОЖНОСТЬ", self.f_s, P_TEXT, CW // 2, 114)
        for key, name in (("diff_normal", "normal"), ("diff_hard", "hard")):
            self._button(MENU_RECTS[key], DIFFICULTIES[name]["name"], self.f_m,
                         selected=g.difficulty == name, pressed=pressed == key)
        for i, line in enumerate(g.cfg["info"].split("\n")):
            self.text_fit(line, (self.f_s, self.f_xs), P_WARN[2], CW // 2, 170 + i * 13, CW - 20)
        self._button(MENU_RECTS["play"], "ИГРАТЬ", self.f_l, accent=(232, 150, 40), pressed=pressed == "play")
        self._button(MENU_RECTS["settings"], "НАСТРОЙКИ", self.f_m, pressed=pressed == "settings")
        self._button(MENU_RECTS["howto"], "КАК ИГРАТЬ", self.f_m, pressed=pressed == "howto")
        self.text("Рекорд: %d" % g.best, self.f_m, P_GOLD_HI, CW // 2, 308)
        self.text("Пробел — играть,  M — звук", self.f_xs, P_TEXT, CW // 2, 384)

    def _menu_settings(self, g, ui):
        pressed = ui.pressed if ui else None
        drag = ui.drag[1] if ui and ui.drag else None
        self.text("НАСТРОЙКИ", self.f_l, P_TEXT, CW // 2, 46)
        self.panel(10, 76, CW - 20, 190)
        self._slider("music", "Музыка", g.music_level, P_GOLD, drag == "music")
        self._slider("sfx", "Эффекты", g.sfx_level, P_WARN[1], drag == "sfx")
        self.text_fit("Отпусти ползунок — услышишь пример", (self.f_xs,), P_TEXT, CW // 2, 197, CW - 30)
        self._button(SETTINGS_RECTS["mute"], "ЗВУК: ВЫКЛ" if g.muted else "ЗВУК: ВКЛ", self.f_m,
                     selected=not g.muted, pressed=pressed == "mute")
        self._button(SETTINGS_RECTS["back"], "НАЗАД", self.f_l, pressed=pressed == "back")

    def _menu_howto(self, g, ui):
        pressed = ui.pressed if ui else None
        self.text("КАК ИГРАТЬ", self.f_l, P_TEXT, CW // 2, 40)
        self.panel(10, 66, CW - 20, 268)
        lines = ("W / S или кнопки — вперёд / назад", "Пробел или тап — прыжок вдоль стены",
                 "Прыжок в воздухе — на другую стену", "К центральной стене — один прыжок",
                 "Лава поднимается — не стой на месте!", "Монетки отодвигают лаву",
                 "Не касайся шипов, пил и огня", "M — звук вкл/выкл, Esc — назад")
        for i, line in enumerate(lines):
            self.text_fit(line, (self.f_s, self.f_xs), P_TEXT, CW // 2, 92 + i * 28, CW - 36)
        self._button(HOWTO_RECTS["back"], "НАЗАД", self.f_l, pressed=pressed == "back")

    def _dead(self, g, ui):
        pressed = ui.pressed if ui else None
        self.panel(30, 90, CW - 60, 156)
        self.text("КОНЕЦ ИГРЫ", self.f_l, P_SCARF, CW // 2, 112)
        self.text_fit(g.death_reason, (self.f_s, self.f_xs), P_WARN[2], CW // 2, 136, CW - 50)
        self.text("Счёт: %d" % g.score, self.f_m, P_TEXT, CW // 2, 162)
        self.text("Рекорд: %d  (%s)" % (g.best, g.cfg["name"].lower()), self.f_s, P_TEXT, CW // 2, 186)
        self.text_fit("Монеты: +%d  (всего %d)" % (g.run_coins, g.total_coins), (self.f_s, self.f_xs),
                      P_GOLD_HI, CW // 2, 208, CW - 50)
        if g.dead_timer > 0.4:
            self._button(DEAD_RECTS["again"], "ЕЩЁ РАЗ", self.f_m, accent=(232, 150, 40), pressed=pressed == "again")
            self._button(DEAD_RECTS["menu"], "В МЕНЮ", self.f_m, pressed=pressed == "menu")
            self.text("Тап в любом месте — ещё раз", self.f_xs, P_TEXT, CW // 2, 306)


# ======================================================================
#                              ЗВУК И МУЗЫКА
# ======================================================================
# Весь звук синтезируется кодом при запуске — внешних файлов не нужно.
# У каждой зоны своя музыка: тональность, темп, ударные и мелодия.
MUSIC_VOL = 0.40          # громкость музыки (0..1)
SFX_VOL = 0.80            # громкость звуковых эффектов (0..1)
SPK_POS = (W - 2 * (WALL_C + 14), 28)      # значок звука (центр, в координатах игры)

CHORDS = {"m": (0, 3, 7), "M": (0, 4, 7)}
RHYTHMS = (                                 # (начало, длина) в восьмых долях такта
    ((0, 2), (2, 1), (3, 1), (4, 2), (6, 1), (7, 1)),
    ((0, 1), (1, 1), (2, 2), (4, 1), (5, 1), (6, 2)),
    ((0, 3), (3, 1), (4, 2), (6, 2)),
    ((0, 2), (2, 2), (4, 1), (5, 1), (6, 2)),
    ((1, 1), (2, 1), (3, 1), (4, 4)),
    ((0, 4), (4, 2), (6, 2)),
)
ZONE_MUSIC = (
    # 1. Вулкан: ля минор (гармонический), драйвовый
    dict(bpm=132, root=45, scale=(0, 2, 3, 5, 7, 8, 11), seed=3,
         prog=((0, "m"), (0, "m"), (8, "M"), (8, "M"), (3, "M"), (3, "M"), (10, "M"), (7, "M")),
         bass=(0, 12, 0, 12, 0, 12, 7, 12), bass_duty=0.25, lead_duty=0.5, arp_div=2, arp_up=0,
         drums="drive", echo=False, rh=(0, 1, 2, 3, 4)),
    # 2. Кристальные пещеры: ре дорийский, лёгкий, с эхом и искрящимися арпеджио
    dict(bpm=118, root=50, scale=(0, 2, 3, 5, 7, 9, 10), seed=8,
         prog=((0, "m"), (0, "m"), (10, "M"), (10, "M"), (8, "M"), (8, "M"), (10, "M"), (10, "M")),
         bass=(0, None, 0, 12, None, 0, 7, None), bass_duty=0.5, lead_duty=0.25, arp_div=2, arp_up=12,
         drums="light", echo=True, rh=(0, 2, 3, 5)),
    # 3. Ядовитые недра: фа-диез фригийский, тяжёлый и тревожный
    dict(bpm=104, root=42, scale=(0, 1, 3, 5, 7, 8, 10), seed=5,
         prog=((0, "m"), (0, "m"), (1, "M"), (1, "M"), (0, "m"), (0, "m"), (10, "M"), (10, "M")),
         bass=(0, None, 0, None, 12, None, 7, None), bass_duty=0.125, lead_duty=0.5, arp_div=1, arp_up=0,
         drums="half", echo=True, rh=(2, 5, 4)),
)


class Synth:
    """Маленький синтезатор на чистом Python (numpy не нужен)."""

    def __init__(self, sr):
        self.sr = sr
        rnd = random.Random(5)
        self.noise = [rnd.uniform(-1.0, 1.0) for _ in range(sr)]
        self._env_cache = {}

    @staticmethod
    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    # ---- волны ----
    def pulse(self, f, n, duty=0.5):
        st, dc = f / self.sr, 2 * duty - 1.0          # dc — убираем смещение нуля у узких импульсов
        return [(1.0 if (i * st) % 1.0 < duty else -1.0) - dc for i in range(n)]

    def tri(self, f, n):
        st = f / self.sr
        return [4.0 * abs((i * st) % 1.0 - 0.5) - 1.0 for i in range(n)]

    def noise_seg(self, n, off=0):
        nz, m = self.noise, len(self.noise)
        return [nz[(off + i) % m] for i in range(n)]

    def sweep(self, f0, f1, n, shape="square", duty=0.5, curve=1.0):
        """Тон, частота которого плавно меняется от f0 к f1."""
        out, ph = [], 0.0
        for i in range(n):
            ph += (f0 + (f1 - f0) * (i / n) ** curve) / self.sr
            x = ph % 1.0
            if shape == "square":
                out.append((1.0 if x < duty else -1.0) - (2 * duty - 1.0))
            elif shape == "tri":
                out.append(4.0 * abs(x - 0.5) - 1.0)
            else:
                out.append(math.sin(2 * math.pi * x))
        return out

    def env(self, n, attack=0.002, tau=0.1, release=0.004):
        key = (n, attack, tau, release)
        e = self._env_cache.get(key)
        if e is None:
            a, r = max(1, int(attack * self.sr)), max(1, int(release * self.sr))
            d, v, e = math.exp(-1.0 / (tau * self.sr)), 1.0, []
            for i in range(n):
                e.append(min(1.0, (i + 1) / a) * v * min(1.0, (n - i) / r))
                v *= d
            self._env_cache[key] = e
        return e

    def voice(self, wave, vol, env):
        return [w * x * vol for w, x in zip(wave, env)]

    @staticmethod
    def lowpass(x, a):
        y, out = 0.0, []
        for s in x:
            y += a * (s - y)
            out.append(y)
        return out

    @staticmethod
    def highpass(x):
        prev, out = 0.0, []
        for s in x:
            out.append(s - prev)
            prev = s
        return out

    @staticmethod
    def add(buf, start, seg):
        """Подмешать seg в buf с позиции start (хвост заходит в начало — цикл без стыка)."""
        n, L = len(buf), len(seg)
        start %= n
        end = start + L
        if end <= n:
            buf[start:end] = [a + b for a, b in zip(buf[start:end], seg)]
        else:
            k = n - start
            buf[start:] = [a + b for a, b in zip(buf[start:], seg[:k])]
            buf[:end - n] = [a + b for a, b in zip(buf[:end - n], seg[k:])]

    @staticmethod
    def normalized(x, peak):
        m = max(1e-9, max(abs(v) for v in x))
        k = peak / m
        return [v * k for v in x]

    @staticmethod
    def loop_fade(b, n, xf):
        """Сделать из b (длиной n+xf) бесшовный цикл длиной n."""
        out = b[:n]
        for i in range(xf):
            t = i / xf
            out[i] = b[i] * t + b[n + i] * (1.0 - t)
        return out

    # ---- звуковые эффекты ----
    def build_sfx(self):
        sr, S = self.sr, {}

        def put(name, x, peak=0.9, vol=1.0):
            S[name] = (self.normalized(x, peak), vol)

        def tones(notes, wave="pulse", duty=0.25, tau=0.06, gap=1.0):
            out = []
            for m, dur in notes:
                n = int(dur * sr)
                w = self.pulse(self.hz(m), n, duty) if wave == "pulse" else self.tri(self.hz(m), n)
                out += self.voice(w, 1.0, self.env(n, 0.002, tau))
            return out

        n = int(0.10 * sr)                                              # прыжок
        put("hop", self.voice(self.sweep(260, 580, n), 1.0, self.env(n, 0.002, 0.07)), 0.7, 0.8)
        n = int(0.24 * sr)                                              # перелёт: свист
        tone, wind = self.sweep(300, 1300, n, "tri"), self.lowpass(self.noise_seg(n, 1000), 0.3)
        e = self.env(n, 0.02, 0.14)
        put("cross", [(a * 0.6 + b * 1.4) * x for a, b, x in zip(tone, wind, e)], 0.7, 0.85)
        n = int(0.13 * sr)                                              # приземление: глухой стук
        thud, puff = self.sweep(150, 55, n, "sine"), self.lowpass(self.noise_seg(n, 3000), 0.15)
        e = self.env(n, 0.001, 0.04)
        put("land", [(a * 0.9 + b * 0.8) * x for a, b, x in zip(thud, puff, e)], 0.8, 0.7)
        put("coin", tones([(83, 0.06), (88, 0.20)], tau=0.09), 0.75, 0.9)    # монетка: си - ми
        n = int(0.75 * sr)                                              # смерть
        fall, boom = self.sweep(520, 50, n, "square", 0.5, 0.6), self.lowpass(self.noise_seg(n, 5000), 0.25)
        e1, e2 = self.env(n, 0.002, 0.30), self.env(n, 0.002, 0.14)
        put("die", [a * x * 0.5 + b * y * 1.6 for a, b, x, y in zip(fall, boom, e1, e2)], 0.95, 1.0)
        n = int(0.55 * sr)                                              # обвал стены
        rumble, crack = self.lowpass(self.noise_seg(n, 7000), 0.08), self.highpass(self.noise_seg(n, 9000))
        e1, e2 = self.env(n, 0.004, 0.20), self.env(n, 0.001, 0.025)
        put("crumble", [r * x * 3.0 + c * y * 0.35 for r, c, x, y in zip(rumble, crack, e1, e2)], 0.9, 0.9)
        put("start", tones([(69, 0.07), (72, 0.07), (76, 0.07), (81, 0.18)], tau=0.1), 0.7, 0.8)
        put("zone", tones([(72, 0.11), (76, 0.11), (79, 0.11), (84, 0.45)], "tri", tau=0.5), 0.8, 0.9)
        n = int(0.10 * sr)                                              # предупреждение о лаве
        put("warn", self.voice(self.pulse(880, n, 0.5), 1.0, self.env(n, 0.002, 0.08)), 0.6, 0.7)
        n = int(0.10 * sr)                                              # шип выдвинулся
        tone, hiss = self.sweep(1500, 3200, n, "tri"), self.highpass(self.noise_seg(n, 2000))
        e = self.env(n, 0.002, 0.04)
        put("shing", [(a * 0.8 + b * 0.5) * x for a, b, x in zip(tone, hiss, e)], 0.5, 0.6)
        n = int(0.65 * sr)                                              # огненный шар
        a_, b_ = self.lowpass(self.noise_seg(n, 4000), 0.06), self.lowpass(self.noise_seg(n, 4000), 0.35)
        put("fire", [(p * (1 - i / n) * 3 + q * (i / n)) * math.sin(math.pi * (i / n) ** 0.6)
                     for i, (p, q) in enumerate(zip(a_, b_))], 0.8, 0.7)
        n = int(0.06 * sr)                                              # потрескивание
        put("crack", [v * x for v, x in zip(self.highpass(self.noise_seg(n, 6000)), self.env(n, 0.001, 0.015))],
            0.6, 0.6)
        n = int(0.05 * sr)                                              # щелчок интерфейса
        put("click", self.voice(self.pulse(1200, n, 0.5), 1.0, self.env(n, 0.001, 0.03)), 0.5, 0.7)
        # пила: бесшовный гул (целое число периодов)
        n = int(0.5 * sr)
        saw = [(2 * ((i * 200 / sr) % 1.0) - 1) * (0.65 + 0.35 * math.sin(2 * math.pi * 20 * i / sr))
               for i in range(2 * n)]
        put("saw", self.lowpass(saw, 0.45)[n:], 0.8, 1.0)
        # лава: бесшовное низкое урчание
        n, xf = 2 * sr, int(0.08 * sr)
        low = self.lowpass(self.noise_seg(n + xf, 12000), 0.05)
        loop = self.loop_fade(low, n, xf)
        put("lava", [v * (0.7 + 0.3 * math.sin(2 * math.pi * i / sr)) for i, v in enumerate(loop)], 0.9, 1.0)
        return S


def build_music(sy, spec):
    """Пошаговая сборка музыкальной петли (генератор: отдаёт управление после каждого куска)."""
    sr = sy.sr
    eighth = int(sr * 30 / spec["bpm"])
    prog, root, rnd = spec["prog"], spec["root"], random.Random(spec["seed"])
    bars = len(prog)
    N = eighth * 8 * bars
    add = Synth.add
    low = lambda cr: cr if cr <= 6 else cr - 12         # бас играет аккордовый корень в нижней октаве

    # --- ударные ---
    n = int(0.15 * sr)
    ph, kick = 0.0, []
    for i in range(n):
        ph += (45 + 115 * math.exp(-i / (0.03 * sr))) / sr
        kick.append(math.sin(2 * math.pi * ph))
    kick = sy.voice(kick, 0.95, sy.env(n, 0.001, 0.07))
    n = int(0.14 * sr)
    snare = [a * 0.8 + b * 0.5 for a, b in
             zip(sy.noise_seg(n, 500), [math.sin(2 * math.pi * 190 * i / sr) for i in range(n)])]
    snare = sy.voice(snare, 0.5, sy.env(n, 0.001, 0.045))
    n = int(0.05 * sr)
    hat = sy.voice(sy.highpass(sy.noise_seg(n, 12000)), 0.28, sy.env(n, 0.001, 0.012))
    pat = dict(
        drive=dict(kick=(0, 4), kick2=(6,), snare=(2, 6), hat=tuple(range(8)), hv=0.55),
        light=dict(kick=(0, 4), kick2=(), snare=(2, 6), hat=(1, 3, 5, 7), hv=0.75),
        half=dict(kick=(0,), kick2=(5,), snare=(4,), hat=(2, 6), hv=0.9),
    )[spec["drums"]]
    drums = [0.0] * N
    for b in range(bars):
        base = b * 8
        for k in pat["kick"]:
            add(drums, (base + k) * eighth, kick)
        if b % 2 == 1:
            for k in pat["kick2"]:
                add(drums, (base + k) * eighth, kick)
        for k in pat["snare"]:
            add(drums, (base + k) * eighth, snare)
        for k in pat["hat"]:
            add(drums, (base + k) * eighth, [v * pat["hv"] for v in hat])
        yield

    # --- бас ---
    bass = [0.0] * N
    for b, (cr, q) in enumerate(prog):
        for k, off in enumerate(spec["bass"]):
            if off is None:
                continue
            nn = int(eighth * 0.9)
            w = sy.pulse(sy.hz(root + low(cr) + off), nn, spec["bass_duty"])
            add(bass, (b * 8 + k) * eighth, sy.voice(w, 0.34, sy.env(nn, 0.003, 0.13)))
        yield

    # --- арпеджио ---
    arp = [0.0] * N
    step = eighth // spec["arp_div"]
    per_bar = 8 * spec["arp_div"]
    for b, (cr, q) in enumerate(prog):
        tones = CHORDS[q]
        for k in range(per_bar):
            midi = root + 12 + cr + tones[(0, 1, 2, 1)[k % 4]] + (12 if k % 8 >= 4 else 0) + spec["arp_up"]
            nn = int(step * 0.85)
            w = sy.pulse(sy.hz(midi), nn, 0.125)
            add(arp, (b * per_bar + k) * step, sy.voice(w, 0.13, sy.env(nn, 0.002, 0.05)))
            if k % 4 == 3:
                yield

    # --- мелодия ---
    pool = sorted(root + 12 * o + d for o in (1, 2, 3) for d in spec["scale"]
                  if root + 19 <= root + 12 * o + d <= root + 36)
    idx = min(range(len(pool)), key=lambda i: abs(pool[i] - (root + 26)))
    rs = [RHYTHMS[i] for i in rnd.sample(spec["rh"], min(4, len(spec["rh"])))]
    while len(rs) < 4:
        rs.append(rs[-1])
    order = (0, 1, 0, 2, 0, 1, 0, 3)
    lead = [0.0] * N
    for b, (cr, q) in enumerate(prog):
        chord = {(root + cr + t) % 12 for t in CHORDS[q]}
        for j, (start, dur) in enumerate(rs[order[b % len(order)]]):
            if j == 0:      # на сильной доле — звук аккорда
                cands = [i for i, m in enumerate(pool) if m % 12 in chord]
                idx = min(cands, key=lambda i: abs(i - idx))
            else:
                idx = max(0, min(len(pool) - 1, idx + rnd.choice((-2, -1, -1, 0, 1, 1, 2))))
            nn = int(dur * eighth * 0.92)
            w = sy.pulse(sy.hz(pool[idx]), nn, spec["lead_duty"])
            add(lead, (b * 8 + start) * eighth, sy.voice(w, 0.22, sy.env(nn, 0.004, 0.30)))
        yield
    if spec["echo"]:
        d1, d2 = eighth * 3, eighth * 6
        e1, e2 = lead[-d1:] + lead[:-d1], lead[-d2:] + lead[:-d2]
        lead = [a + 0.33 * b + 0.15 * c for a, b, c in zip(lead, e1, e2)]
        yield

    # --- сведение и перевод в 16 бит (кусками, чтобы не подвешивать игру) ---
    mix, chunk = [0.0] * N, 40000
    for s in range(0, N, chunk):
        mix[s:s + chunk] = [a + b + c + d for a, b, c, d in
                            zip(drums[s:s + chunk], bass[s:s + chunk], arp[s:s + chunk], lead[s:s + chunk])]
        yield
    k = 0.85 * 32767 / max(1e-9, max(abs(v) for v in mix))
    pcm = array.array("h")
    for s in range(0, N, chunk):
        pcm.extend([int(v * k) for v in mix[s:s + chunk]])
        yield
    return pcm


class TrackBuilder:
    def __init__(self, sy, spec):
        self.gen = build_music(sy, spec)
        self.result = None

    def step(self):
        try:
            next(self.gen)
            return False
        except StopIteration as stop:
            self.result = stop.value
            return True


def in_speaker(pos):
    dx, dy = pos[0] - SPK_POS[0], pos[1] - SPK_POS[1]
    return dx * dx + dy * dy <= 30 * 30


class Audio:
    """Звуковые эффекты и музыка. Если звука в системе нет — молча ничего не делает."""

    def __init__(self, muted=False, music_level=1.0, sfx_level=1.0):
        self.ok = False
        self.muted = muted
        self.music_level, self.sfx_level = music_level, sfx_level      # положение ползунков (0..1)
        self.sfx_base = {}
        self.t = 0.0
        self.last = {}
        self.track = None
        self.music_ch = 1
        self.zone = 0
        self.prev_blink = False
        self.hz_state = {}
        self.loops = {"saw": False, "lava": False}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(22050, -16, 1, 512)
            freq, fmt, ch = pygame.mixer.get_init()
            if fmt != -16 or ch not in (1, 2):
                return                          # нестандартный формат — не рискуем
            pygame.mixer.set_num_channels(16)
            pygame.mixer.set_reserved(4)        # 0-1 музыка, 2 пила, 3 лава
            self.channels = ch
            self.sy = Synth(freq)
            self.sfx = {}
            for name, (x, vol) in self.sy.build_sfx().items():
                self.sfx_base[name] = vol * SFX_VOL
                self.sfx[name] = self._sound(x, vol * SFX_VOL * self.sfx_level)
            self.builders = [TrackBuilder(self.sy, spec) for spec in ZONE_MUSIC]
            self.tracks = [None] * len(ZONE_MUSIC)
            while not self.builders[0].step():  # первую музыку собираем сразу, остальные — по ходу игры
                pass
            self._finish_builders()
            self.ok = True
        except Exception:
            self.ok = False

    # ---------- подготовка звуков ----------
    def _sound(self, x, vol):
        pcm = array.array("h", [int(max(-1.0, min(1.0, v)) * 32767) for v in x])
        return self._to_sound(pcm, vol)

    def _to_sound(self, pcm, vol):
        if self.channels == 2:
            st = array.array("h", [0]) * (2 * len(pcm))
            st[0::2] = pcm
            st[1::2] = pcm
            pcm = st
        if sys.byteorder == "big":
            pcm.byteswap()
        snd = pygame.mixer.Sound(buffer=pcm.tobytes())
        snd.set_volume(vol)
        return snd

    def _finish_builders(self):
        for i, b in enumerate(self.builders):
            if self.tracks[i] is None and b.result is not None:
                self.tracks[i] = self._to_sound(b.result, MUSIC_VOL * self.music_level)

    def _build(self, budget):
        """Достраиваем музыку следующих зон понемногу, чтобы не было лагов."""
        end = time.perf_counter() + budget
        for b in self.builders:
            while b.result is None and time.perf_counter() < end:
                b.step()
            if b.result is None:
                break
        self._finish_builders()

    # ---------- управление ----------
    def set_muted(self, muted):
        self.muted = muted
        if not self.ok:
            return
        if muted:
            pygame.mixer.stop()
            self.track = None
            self.loops = {"saw": False, "lava": False}
        else:
            self.play("click")

    def set_levels(self, music, sfx):
        """Ползунки громкости: music и sfx от 0 до 1. Музыка меняется сразу, пока играет."""
        self.music_level, self.sfx_level = music, sfx
        if not self.ok:
            return
        for name, snd in self.sfx.items():
            snd.set_volume(self.sfx_base[name] * sfx)       # шум пилы и лавы подстраивается каждый кадр
        for snd in self.tracks:
            if snd is not None:
                snd.set_volume(MUSIC_VOL * music)

    def play(self, name, vol=1.0):
        if not self.ok or self.muted:
            return
        if self.t - self.last.get(name, -9.0) < 0.04:
            return
        self.last[name] = self.t
        ch = self.sfx[name].play()
        if ch is not None and vol != 1.0:
            ch.set_volume(vol)

    def _switch_music(self, want):
        old = pygame.mixer.Channel(self.music_ch)
        if old.get_busy():
            old.fadeout(1200)
        self.music_ch = 1 - self.music_ch
        pygame.mixer.Channel(self.music_ch).play(self.tracks[want], loops=-1, fade_ms=1200)
        self.track = want

    def _loop(self, name, ch_index, volume):
        snd = self.sfx[name]
        if volume > 0.02:
            if not self.loops[name]:
                pygame.mixer.Channel(ch_index).play(snd, loops=-1)
                self.loops[name] = True
            snd.set_volume(volume * SFX_VOL * self.sfx_level)
        elif self.loops[name]:
            pygame.mixer.Channel(ch_index).stop()
            self.loops[name] = False

    def update(self, g, events, dt):
        """Вызывается каждый кадр: события игры -> звуки, музыка зон, шум пилы и лавы."""
        if not self.ok:
            return
        self.t += dt
        self._build(0.003)
        if self.muted:
            return
        for ev in events:
            k = ev[0]
            if k == "hop":
                self.play("hop")
            elif k == "cross":
                self.play("cross")
            elif k == "land":
                self.play("land")
            elif k == "coin":
                self.play("coin")
            elif k == "crumble":
                self.play("crumble")
            elif k == "start":
                self.play("start")
                self.zone = 0
            elif k == "die":
                self.play("die")
                pygame.mixer.Channel(self.music_ch).fadeout(700)
                self.track = None
        playing = g.state == "play"
        # музыка: в меню и на уровне играет трек текущей зоны
        if g.state in ("menu", "play"):
            want = 0 if g.state == "menu" else (g.score // ZONE_LEN) % len(self.tracks)
            if want != self.track and self.tracks[want] is not None:
                self._switch_music(want)
        # фанфары при входе в новую зону
        if playing:
            z = g.score // ZONE_LEN
            if z > self.zone:
                self.play("zone")
            self.zone = z
        # угрозы на экране
        self._hazard_sounds(g, playing)
        # лава
        gap = g.lava_y - (g.y + PLAYER)
        close = max(0.0, min(1.0, (320 - gap) / 320))
        self._loop("lava", 3, (0.20 + 0.80 * close) * 0.55 if playing else 0.0)
        blink = playing and gap < 150 and int(g.time * 6) % 2 == 0
        if blink and not self.prev_blink:
            self.play("warn")
        self.prev_blink = blink

    def _hazard_sounds(self, g, playing):
        top, bot = g.cam_y - 40, g.cam_y + H + 40
        seen, saw_dist = set(), None
        py = g.y + PLAYER / 2
        for h in g.hazards if playing else ():
            key = id(h)
            seen.add(key)
            prev = self.hz_state.get(key)
            if h.kind == "fire":
                flying = h.state(g.time)[0] == "fly"
                if flying and not prev and top <= h.y <= bot:
                    self.play("fire", 0.8)
                self.hz_state[key] = flying
            elif h.kind == "pulse":
                out = h.ext(g.time) >= 0.6
                if out and not prev and top <= h.y <= bot:
                    self.play("shing", 0.7)
                self.hz_state[key] = out
            elif h.kind == "crumble":
                cracking = h.state == "intact" and h.timer > 0
                if cracking and not prev:
                    self.play("crack")
                self.hz_state[key] = cracking
            elif h.kind == "saw":
                d = abs(h.y - py)
                saw_dist = d if saw_dist is None else min(saw_dist, d)
        for key in list(self.hz_state):
            if key not in seen:
                del self.hz_state[key]
        vol = 0.0 if saw_dist is None else 0.5 * max(0.0, 1.0 - saw_dist / 380.0) ** 2
        self._loop("saw", 2, vol)


# ---------- Меню: расположение кнопок (координаты игры) ----------
MENU_RECTS = {
    "diff_normal": pygame.Rect(28, 256, 208, 60), "diff_hard": pygame.Rect(244, 256, 208, 60),
    "play": pygame.Rect(90, 392, 300, 84),
    "settings": pygame.Rect(28, 512, 208, 60), "howto": pygame.Rect(244, 512, 208, 60),
}
SETTINGS_RECTS = {
    "music": pygame.Rect(48, 192, 384, 64), "sfx": pygame.Rect(48, 312, 384, 64),
    "mute": pygame.Rect(90, 440, 300, 64), "back": pygame.Rect(90, 676, 300, 68),
}
HOWTO_RECTS = {"back": pygame.Rect(90, 700, 300, 68)}
DEAD_RECTS = {"again": pygame.Rect(28, 524, 208, 60), "menu": pygame.Rect(244, 524, 208, 60)}
SLIDER_X0, SLIDER_X1 = 72, 408          # края дорожки ползунка


class _Pose:
    """Минимальное состояние птенца — чтобы нарисовать талисман в меню."""
    mode, move_dir, state = "run", 0, "menu"

    def __init__(self, n):
        self.n = self.direction = n


class UI:
    """Экраны меню (главное, настройки, «как играть») и кнопки на экране смерти."""

    def __init__(self, game, audio, toggle_sound):
        self.game, self.audio, self.toggle_sound = game, audio, toggle_sound
        self.screen = "main"
        self.drag = None          # (указатель, "music" / "sfx"), пока тянут ползунок
        self.pressed = None       # имя нажатой кнопки — для подсветки

    def rects(self):
        g = self.game
        if g.state == "menu":
            return {"main": MENU_RECTS, "settings": SETTINGS_RECTS, "howto": HOWTO_RECTS}[self.screen]
        if g.state == "dead" and g.dead_timer > 0.4:
            return DEAD_RECTS
        return {}

    def press(self, pos, pid="mouse"):
        """Нажатие. True — если попали в кнопку меню (тогда игра это нажатие не обрабатывает)."""
        for name, r in self.rects().items():
            if r.collidepoint(int(pos[0]), int(pos[1])):
                self.pressed = name
                self._activate(name, pos, pid)
                return True
        return False

    def move(self, pos, pid="mouse"):
        if self.drag and self.drag[0] == pid:
            self._set_slider(self.drag[1], pos[0])

    def release(self, pid="mouse"):
        self.pressed = None
        if self.drag and self.drag[0] == pid:
            name = self.drag[1]
            self.drag = None
            self.game.save()
            if name == "sfx":
                self.audio.play("coin")          # пример громкости эффектов

    def _set_slider(self, name, x):
        v = max(0.0, min(1.0, (x - SLIDER_X0) / (SLIDER_X1 - SLIDER_X0)))
        v = round(v * 20) / 20                   # шаг 5 %
        g = self.game
        if name == "music":
            g.music_level = v
        else:
            g.sfx_level = v
        self.audio.set_levels(g.music_level, g.sfx_level)

    def _activate(self, name, pos, pid):
        g, a = self.game, self.audio
        if name in ("diff_normal", "diff_hard"):
            g.set_difficulty("normal" if name == "diff_normal" else "hard")
            g.save()
            a.play("click")
        elif name == "play":
            self.screen = "main"
            g.start_game()
        elif name in ("settings", "howto"):
            self.screen = name
            a.play("click")
        elif name == "back":
            self.screen = "main"
            a.play("click")
        elif name == "mute":
            self.toggle_sound()
        elif name in ("music", "sfx"):
            self.drag = (pid, name)
            self._set_slider(name, pos[0])
        elif name == "again":
            g.start_game()
        elif name == "menu":
            g.to_menu()
            self.screen = "main"
            a.play("click")


async def main():
    pygame.mixer.pre_init(22050, -16, 1, 512)   # до pygame.init(): задаём формат звука
    pygame.init()
    screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    pygame.display.set_caption("Wall Climbers")
    clock = pygame.time.Clock()
    renderer = Renderer()
    pointers = {}       # пальцы и мышь -> позиция (нужны, чтобы понимать, какая кнопка зажата)
    game = Game()
    game.record = True  # игра сообщает о событиях (прыжок, монетка, ...) для эффектов и звука
    audio = Audio(game.muted, game.music_level, game.sfx_level)

    def toggle_sound():
        game.muted = not game.muted
        audio.set_muted(game.muted)
        game.save()

    ui = UI(game, audio, toggle_sound)

    def press(pos, pid):
        pointers[pid] = pos
        if in_speaker(pos):
            toggle_sound()
        elif ui.press(pos, pid):
            pass
        elif game.state == "play" and on_buttons(pos):
            pass                                  # кнопки «вперёд/назад» обрабатываются ниже
        elif game.state != "menu":
            game.tap()                            # прыжок (или «ещё раз» на экране смерти)

    running = True
    while running:
        dt = min(clock.tick(60) / 1000, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            # --- касания (мультитач: одним пальцем держим кнопку, другим прыгаем) ---
            elif event.type == pygame.FINGERDOWN:
                press(finger_pos(event), ("f", getattr(event, "finger_id", 0)))
            elif event.type == pygame.FINGERMOTION:
                key = ("f", getattr(event, "finger_id", 0))
                if key in pointers:
                    pointers[key] = finger_pos(event)
                    ui.move(pointers[key], key)
            elif event.type == pygame.FINGERUP:
                key = ("f", getattr(event, "finger_id", 0))
                pointers.pop(key, None)
                ui.release(key)
            # --- мышь (касания, продублированные как мышь, пропускаем) ---
            elif event.type == pygame.MOUSEBUTTONDOWN and not getattr(event, "touch", False):
                press(event.pos, "mouse")
            elif event.type == pygame.MOUSEMOTION and not getattr(event, "touch", False):
                if "mouse" in pointers:
                    pointers["mouse"] = event.pos
                    ui.move(event.pos, "mouse")
            elif event.type == pygame.MOUSEBUTTONUP and not getattr(event, "touch", False):
                pointers.pop("mouse", None)
                ui.release("mouse")
            # --- клавиатура ---
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if game.state == "menu":
                        if ui.screen == "main":
                            game.start_game()
                        else:
                            ui.screen = "main"
                    else:
                        game.tap()
                elif event.key in (pygame.K_LEFT, pygame.K_RIGHT) and game.state == "menu" and ui.screen == "main":
                    game.set_difficulty("hard" if game.difficulty == "normal" else "normal")
                    game.save()
                    audio.play("click")
                elif event.key == pygame.K_m:
                    toggle_sound()
                elif event.key == pygame.K_ESCAPE:
                    if game.state == "menu":
                        if ui.screen != "main":
                            ui.screen = "main"
                        else:
                            running = False
                    else:
                        game.to_menu()
                        ui.screen = "main"

        keys = pygame.key.get_pressed()
        up = keys[pygame.K_w] or keys[pygame.K_UP]
        down = keys[pygame.K_s] or keys[pygame.K_DOWN]
        for pos in pointers.values():
            up = up or in_button(pos, BTN_UP)
            down = down or in_button(pos, BTN_DOWN)
        game.move_dir = (1 if up else 0) - (1 if down else 0)

        game.update(dt)
        audio.update(game, list(game.events), dt)      # звук читает события раньше, чем их заберёт рендерер
        renderer.update(game, dt)
        renderer.draw(game, up, down, ui)
        renderer.present(screen)
        pygame.display.flip()
        await asyncio.sleep(0)   # нужно для запуска в браузере (pygbag)

    game.save()
    pygame.quit()


asyncio.run(main())