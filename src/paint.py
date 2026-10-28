#!/usr/bin/env python3
"""Salad Night — запекание сцены для живых обоев.

Стиль: ночная фэнтези-иллюстрация, неоновая контурная подсветка силуэтов,
слои дымки, светящийся водопад. Палитра: мягкий чёрный + салатовый.

Выход:
  scene.png   1920x2400 RGBA: верх — цвет (RGB), низ — маски:
              R листва (световые волны), G вода (1 водопад, 0.5 пруд),
              B глубина (0 близко … 1 небо, для тумана), A качание травы
  still.png   статичный кадр (для обзора и экрана блокировки)
  consts.glsl координаты окон, фонаря, трубы, воды — подставляются в шейдер

  python3 paint.py OUT_DIR [--seed N]
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1200
SS = 2

GLOW = (760.0, 430.0)  # главный источник света: сияние за горами
SALAD = np.array([166, 216, 107], np.float32)
NEON = np.array([196, 240, 140], np.float32)
MINT = np.array([150, 230, 190], np.float32)
WARM = np.array([232, 238, 160], np.float32)

YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)


def C(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


# ---------------------------------------------------------------- утилиты

def fbm(rng, octaves=5, base=4, h=H, w=W, persistence=.5):
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gh, gw = base * 2 ** o, int(base * 2 ** o * w / h) + 1
        g = rng.random((gh + 1, gw + 1)).astype(np.float32)
        im = Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        out += amp * np.asarray(im, np.float32) / 255
        tot += amp
        amp *= persistence
    return out / tot


def canvas():
    img = Image.new('L', (W * SS, H * SS), 0)
    return img, ImageDraw.Draw(img)


def down(img):
    return np.asarray(img.resize((W, H), Image.LANCZOS), np.float32) / 255


def blur(a, r):
    if r <= 0:
        return a
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255


def shift(a, dx, dy):
    """Сдвиг массива с нулями по краям (дробные сдвиги округляются)."""
    dx, dy = int(round(dx)), int(round(dy))
    out = np.zeros_like(a)
    h, w = a.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def light_dir():
    dx, dy = GLOW[0] - XX, GLOW[1] - YY
    n = np.sqrt(dx * dx + dy * dy) + 1e-3
    return dx / n, dy / n, n


LDX, LDY, LDIST = light_dir()


def rim(mask, width=3.0, soft=1.2, toward=None):
    """Контур силуэта, обращённый к свету: неоновая обводка как на иллюстрации."""
    acc = np.zeros_like(mask)
    norm = np.zeros_like(mask)
    ldx, ldy = (LDX, LDY) if toward is None else toward
    for k in range(8):
        a = k * math.pi / 4
        dx, dy = math.cos(a), math.sin(a)
        wgt = np.clip(dx * ldx + dy * ldy, 0, 1) ** 2
        # точки маски, у которых сосед в сторону света снаружи
        e = mask * (1 - shift(mask, -dx * width, -dy * width))
        acc += e * wgt
        norm += wgt
    r = acc / (norm + 1e-3)
    return np.clip(blur(r, soft) * 1.6, 0, 1)


def light_falloff(scale=900.0, floor=.25):
    return floor + (1 - floor) * np.exp(-(LDIST / scale) ** 2)


def over(img, mask, color):
    m = mask[..., None]
    return img * (1 - m) + color * m


# ---------------------------------------------------------------- формы

def pine(d, x, base, h, rng, detail=1.0):
    """Ель: свисающие лапы-клинья, снизу бахрома иголок (маска, координаты 1x)."""
    s = SS
    w = h * rng.uniform(.36, .46)
    tw = max(1.0, h * .018)
    d.polygon([((x - tw) * s, base * s), ((x + tw) * s, base * s), (x * s, (base - h) * s)], fill=255)
    n = int(7 + 14 * detail)
    lean = rng.uniform(-.04, .04)
    for i in range(n):
        f = (i + rng.uniform(-.3, .3)) / n  # 0 верх … 1 низ
        f = min(max(f, 0), 1)
        y = base - h + h * (.03 + .85 * f)
        cxp = x + lean * h * (1 - f)
        reach = w * .5 * (.12 + .88 * f ** .85) * rng.uniform(.8, 1.12)
        for side in (-1, 1):
            ln = reach * rng.uniform(.8, 1.05)
            droop = rng.uniform(.25, .5)
            th = max(2.0, h * .03 * (1 - f * .3))
            tip = (cxp + side * ln, y + ln * droop)
            up = (cxp + side * ln * .5, y + ln * droop * .15 - th * .3)
            lo = (cxp + side * ln * .6, y + ln * droop * .55 + th)
            pts = [(cxp, y - th * .6), up, tip, lo, (cxp, y + th * 1.4)]
            d.polygon([(a * s, b * s) for a, b in pts], fill=255)
            if detail > .25:  # бахрома иголок вдоль нижнего края лапы
                m = int(3 + 9 * detail * ln / (w * .5 + 1))
                for k in range(m):
                    t = (k + rng.random()) / m
                    px = cxp + side * ln * t
                    py = y + ln * droop * t * t * .9 + th * (1 - t)
                    nl = h * rng.uniform(.018, .04) * (1.2 - t * .5)
                    d.line([(px * s, py * s), ((px + side * nl * .35) * s, (py + nl) * s)],
                           fill=255, width=max(1, int(s * .9)))
    d.polygon([(x * s, (base - h * 1.04) * s), ((x - w * .04) * s, (base - h * .9) * s),
               ((x + w * .04) * s, (base - h * .9) * s)], fill=255)


def branch(d, leaves, x, y, ang, ln, wd, depth, rng, leaf_r):
    s = SS
    if ln > 40 and depth > 0:  # изгиб: длинную ветку рисуем двумя коленами
        a1 = ang + rng.uniform(-.25, .25)
        mx, my = x + math.cos(a1) * ln * .5, y - math.sin(a1) * ln * .5
        nx_, ny_ = math.sin(a1), math.cos(a1)
        w2 = wd * .84
        d.polygon([((x - nx_ * wd / 2) * s, (y - ny_ * wd / 2) * s), ((x + nx_ * wd / 2) * s, (y + ny_ * wd / 2) * s),
                   ((mx + nx_ * w2 / 2) * s, (my + ny_ * w2 / 2) * s), ((mx - nx_ * w2 / 2) * s, (my - ny_ * w2 / 2) * s)], fill=255)
        d.ellipse([(mx - w2 / 2) * s, (my - w2 / 2) * s, (mx + w2 / 2) * s, (my + w2 / 2) * s], fill=255)
        x, y, wd, ln = mx, my, w2, ln * .5
        ang = ang + rng.uniform(-.2, .2)
    x2 = x + math.cos(ang) * ln
    y2 = y - math.sin(ang) * ln
    # сужающийся сегмент
    nx, ny = math.sin(ang), math.cos(ang)
    w2 = wd * .68
    d.polygon([((x - nx * wd / 2) * s, (y - ny * wd / 2) * s), ((x + nx * wd / 2) * s, (y + ny * wd / 2) * s),
               ((x2 + nx * w2 / 2) * s, (y2 + ny * w2 / 2) * s), ((x2 - nx * w2 / 2) * s, (y2 - ny * w2 / 2) * s)],
              fill=255)
    d.ellipse([(x2 - w2 / 2) * s, (y2 - w2 / 2) * s, (x2 + w2 / 2) * s, (y2 + w2 / 2) * s], fill=255)
    if depth == 0 or ln < 10:
        leaves.append((x2, y2, leaf_r * rng.uniform(.7, 1.2)))
        return
    kids = 2 if rng.random() < .65 else 3
    for k in range(kids):
        da = rng.uniform(.25, .65) * (1 if k % 2 else -1) + rng.uniform(-.1, .1)
        branch(d, leaves, x2, y2, ang + da, ln * rng.uniform(.62, .8), w2, depth - 1, rng, leaf_r)


def foliage(d, leaves, rng, dabs=60):
    """Кроны — сотни мелких «мазков-листочков» вокруг концов веток."""
    s = SS
    for (cx, cy, r) in leaves:
        for i in range(dabs):
            a = rng.uniform(0, 2 * math.pi)
            rr = r * math.sqrt(rng.random())
            px, py = cx + math.cos(a) * rr * 1.3, cy + math.sin(a) * rr * .75 - r * .2
            lw, lh = rng.uniform(2.5, 6.5), rng.uniform(1.5, 3.5)
            rot = rng.uniform(0, math.pi)
            pts = [(px + math.cos(rot) * lw, py + math.sin(rot) * lw), (px + math.cos(rot + 1.57) * lh, py + math.sin(rot + 1.57) * lh),
                   (px - math.cos(rot) * lw, py - math.sin(rot) * lw), (px - math.cos(rot + 1.57) * lh, py - math.sin(rot + 1.57) * lh)]
            d.polygon([(a_ * s, b_ * s) for a_, b_ in pts], fill=255)


def fern(d, x, y, ln, ang, rng):
    s = SS
    pts = []
    for k in range(14):
        t = k / 13
        a = ang - t * .9 * (1 if ang < math.pi / 2 else -1)
        if k == 0:
            px, py = x, y
        else:
            px, py = pts[-1][0] / s + math.cos(a) * ln / 13, pts[-1][1] / s - math.sin(a) * ln / 13
        pts.append((px * s, py * s))
        if k > 0:
            fl = ln * .22 * (1 - t) ** .7 + 2
            for sd in (-1, 1):
                la = a + sd * 1.1
                d.line([(px * s, py * s), ((px + math.cos(la) * fl) * s, (py - math.sin(la) * fl) * s)], fill=255, width=max(1, int(1.4 * s)))
    d.line(pts, fill=255, width=max(1, int(1.6 * s)), joint='curve')


def grass(d, x, y, h, rng, lean=0.0):
    s = SS
    bend = rng.uniform(-.35, .35) + lean
    pts = []
    for k in range(6):
        t = k / 5
        pts.append(((x + bend * h * t * t) * s, (y - h * t) * s))
    d.line(pts, fill=255, width=max(1, int(rng.uniform(1.2, 2.4) * s)), joint='curve')


def rock(d, cx, cy, rx, ry, rng):
    s = SS
    pts = []
    n = 14
    for k in range(n):
        a = math.pi + k / (n - 1) * math.pi
        rr = rng.uniform(.82, 1.08)
        pts.append(((cx + math.cos(a) * rx * rr) * s, (cy + math.sin(a) * ry * rr) * s))
    pts.append(((cx + rx) * s, (cy + ry * .15) * s))
    pts.append(((cx - rx) * s, (cy + ry * .15) * s))
    d.polygon(pts, fill=255)


# ---------------------------------------------------------------- сцена

def paint(seed):
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    depth = np.ones((H, W), np.float32)
    leafm = np.zeros((H, W), np.float32)
    water = np.zeros((H, W), np.float32)
    sway = np.zeros((H, W), np.float32)

    def put(mask, color, dep, leaf=None, sw=None):
        nonlocal img, depth, leafm, water, sway
        img = over(img, mask, color)
        depth = depth * (1 - mask) + dep * mask
        leafm = leafm * (1 - mask) + (0 if leaf is None else leaf) * mask
        water = water * (1 - mask)
        sway = sway * (1 - mask) + (0 if sw is None else sw) * mask

    # --- небо
    t = np.clip(YY / 760, 0, 1)
    img[:] = C('#080a08') * (1 - t[..., None]) + C('#132017') * t[..., None]
    g = np.exp(-((XX - GLOW[0]) ** 2 / 520 ** 2 + (YY - GLOW[1]) ** 2 / 300 ** 2))
    img += (SALAD - img) * (g * .30)[..., None]
    img += (NEON - img) * (np.exp(-((XX - GLOW[0]) ** 2 + (YY - GLOW[1]) ** 2) / 120 ** 2) * .25)[..., None]
    # облака: волокна шума с подсветкой снизу
    cl = fbm(rng, 6, 3)
    cl = np.clip((cl - .5) * 3.2, 0, 1) * np.clip(1 - YY / 520, 0, 1)
    cl_edge = np.clip(cl - shift(cl, 0, 6), 0, 1) * (YY > 8)
    img = img * (1 - cl[..., None] * .55) + C('#0d140f') * (cl[..., None] * .55)
    img += (SALAD - img) * (cl_edge * light_falloff(700, .1) * 1.4)[..., None] * .5
    # звёзды
    for _ in range(140):
        sx, sy = rng.uniform(0, W), rng.uniform(0, 420)
        b = rng.uniform(.15, .6) * (1 - cl[int(sy), int(sx)])
        r2 = (XX[max(0, int(sy) - 3):int(sy) + 4, max(0, int(sx) - 3):int(sx) + 4] - sx) ** 2 + \
             (YY[max(0, int(sy) - 3):int(sy) + 4, max(0, int(sx) - 3):int(sx) + 4] - sy) ** 2
        img[max(0, int(sy) - 3):int(sy) + 4, max(0, int(sx) - 3):int(sx) + 4] += (np.exp(-r2 / .8) * b * 255)[..., None] * np.array([.8, 1, .75])

    # --- горы: два хребта
    xs = np.arange(W, dtype=np.float32)
    for k, (top, col, dep) in enumerate(((300, '#1a2a20', .92), (420, '#121d16', .85))):
        r1 = fbm(np.random.default_rng(seed + 10 + k), 6, 2, 64, W, .55)[32]
        # зубчатый хребет: крупные пики + мелкие скалы
        peaks = np.zeros(W, np.float32)
        for (pc, ph, pw) in (((540, 230, 210), (1180, 300, 260), (1560, 180, 200)) if k == 0 else
                             ((300, 160, 220), (980, 200, 240), (1720, 240, 230))):
            peaks = np.maximum(peaks, ph * np.clip(1 - np.abs(xs - pc) / pw, 0, 1) ** 1.25)
        line = top + 120 - peaks - (r1 - .5) * 90
        m = (YY >= line[None, :]).astype(np.float32)
        m = blur(m, .6)
        tex = fbm(rng, 5, 8)
        streak = fbm(np.random.default_rng(seed + 30 + k), 4, 3, 8, W)[4][None, :]
        facets = fbm(np.random.default_rng(seed + 40 + k), 5, 6, persistence=.6)
        base = C(col) * (.8 + .25 * tex[..., None] + .25 * (facets[..., None] - .5))
        haze = np.clip((YY - line[None, :]) / 300, 0, 1)
        base = base * (1 - haze[..., None] * .4) + C('#22342a') * (haze[..., None] * .4)
        put(m, base, dep)
        img += (NEON - img) * (rim(m, 3, 1.0) * light_falloff(800, .15) * .75)[..., None]

    # --- утёс с водопадом (по центру-слева)
    cv, cd = canvas()
    fall_x0, fall_x1, fall_top, fall_bot = 716, 746, 392, 868
    cliff = [(430, 1000), (455, 820), (490, 720), (470, 690), (520, 600), (548, 560), (585, 470), (612, 445),
             (650, 420), (690, 398), (fall_x0, fall_top), (fall_x1, fall_top - 3), (772, 380), (790, 352),
             (812, 370), (850, 402), (880, 455), (905, 470), (930, 540), (975, 610), (990, 660), (1030, 760),
             (1060, 860), (1080, 1000)]
    jag = []
    for (ax, ay), (bx, by) in zip(cliff, cliff[1:] + cliff[:1]):  # рваные грани между опорными точками
        for k in range(4):
            t = k / 4
            jag.append((ax + (bx - ax) * t + rng.uniform(-7, 7), ay + (by - ay) * t + rng.uniform(-7, 7)))
    cd.polygon([(x * SS, y * SS) for x, y in jag], fill=255)
    cm = down(cv)
    tex = fbm(rng, 6, 10)
    strata = (np.sin(YY * .07 + XX * .02 + tex * 12) * .5 + .5) ** 3 * .45
    put(cm, C('#0c130f') * (.8 + .4 * tex[..., None] + strata[..., None]), .7)
    img += (NEON - img) * (rim(cm, 4, 1.2) * light_falloff(600, .2))[..., None] * .9
    # трещины, подсвеченные водой
    for _ in range(26):
        x0 = rng.uniform(500, 1000)
        y0 = rng.uniform(500, 900)
        pts = [(x0, y0)]
        for k in range(8):
            x0 += rng.uniform(-14, 14)
            y0 += rng.uniform(4, 16)
            pts.append((x0, y0))
        cv2, cd2 = canvas()
        cd2.line([(a * SS, b * SS) for a, b in pts], fill=255, width=SS)
        cr = down(cv2) * cm
        img += (SALAD - img) * (cr * .35 * light_falloff(500, .1))[..., None]

    # водопад: базовый цвет (анимация — в шейдере)
    fx = (XX - (fall_x0 + fall_x1) / 2) / ((fall_x1 - fall_x0) / 2)
    edge_noise = (fbm(rng, 3, 30) - .5) * .5
    fall = np.clip(1 - np.abs(fx + edge_noise) ** 2.5, 0, 1) * ((YY > fall_top) & (YY < fall_bot)).astype(np.float32)
    widen = np.clip((YY - fall_top) / (fall_bot - fall_top), 0, 1)
    fx2 = (XX - (fall_x0 + fall_x1) / 2) / ((fall_x1 - fall_x0) / 2 * (1 + widen * .5))
    fall = np.clip(1 - np.abs(fx2 + edge_noise) ** 2.5, 0, 1) * ((YY > fall_top) & (YY < fall_bot))
    fall = blur(fall.astype(np.float32), .8)
    fcol = MINT * .55 + SALAD * .45
    img = over(img, fall * .85, fcol * (.6 + .5 * fbm(rng, 4, 40)[..., None]))
    water = np.maximum(water, (fall > .05) * 1.0)
    depth = depth * (1 - fall) + .68 * fall
    # свечение вокруг водопада
    gl = blur(fall, 18)
    img += (SALAD - img) * (gl * .45)[..., None]

    # --- лес: три слоя елей, дальние в дымке
    for k, (by, hmin, hmax, step, col, dep, det) in enumerate((
            (770, 90, 200, 30, '#172519', .62, .2),
            (830, 120, 280, 42, '#111b14', .52, .5),
            (885, 160, 340, 60, '#0b130e', .42, .85))):
        cv, cd = canvas()
        grp = fbm(np.random.default_rng(seed + 50 + k), 4, 3, 16, W)[8]  # рощи и прогалины
        x = -30.0
        while x < W + 30:
            g_ = grp[int(min(max(x, 0), W - 1))]
            clear_fall = fall_x0 - 70 < x < fall_x1 + 70
            if g_ > .38 and not clear_fall:
                h = rng.uniform(hmin, hmax) * (.6 + .7 * g_)
                if 440 < x < 1080:
                    h *= .55 if k < 2 else .7
                pine(cd, x, by + rng.uniform(-10, 10), h, rng, det)
            x += step * rng.uniform(.45, 1.2)
        # подложка слоя: мягкий холм без жёсткого края (на неё не ставим контур)
        und, ud = canvas()
        wav = fbm(np.random.default_rng(seed + 60 + k), 4, 3, 16, W)[8]
        ud.polygon([(0, H * SS)] + [(x_ * SS, (by - 10 + (wav[x_] - .5) * 40) * SS) for x_ in range(0, W, 16)] +
                   [(W * SS, H * SS)], fill=255)
        um = blur(down(und), 3)
        trees_m = down(cv)
        m = np.maximum(trees_m, um)
        tex = fbm(rng, 4, 20)
        put(m, C(col) * (.85 + .3 * tex[..., None]), dep, leaf=.5 + .2 * k)
        img += (NEON - img) * (rim(trees_m, 2.5, .8) * (1 - um) * light_falloff(700, .12) * (.75 - k * .15))[..., None]
        # туман между слоями
        fogb = np.exp(-((YY - by + 10) / 45) ** 2) * .22 * (1 - k * .25)
        img += (C('#2a3c2c') - img) * fogb[..., None]

    # --- пруд и отражения
    pond_y = 900.0
    cv, cd = canvas()
    shore = [(330, 1010), (360, 935), (430, 905), (560, 896), (700, 890), (900, 893), (1080, 900), (1230, 912),
             (1300, 960), (1270, 1010)]
    cd.polygon([((x + rng.uniform(-5, 5)) * SS, (y + rng.uniform(-3, 3)) * SS) for x, y in shore], fill=255)
    pm = down(cv)
    pm = pm * (YY >= pond_y - 14)
    refl_y = np.clip(2 * pond_y - YY, 0, H - 1).astype(int)
    refl = img[refl_y, XX.astype(int)]
    ref_col = refl * .55 + C('#06120c') * .45
    ref_col += (SALAD - ref_col) * (blur(fall, 22)[refl_y, XX.astype(int)] * .5)[..., None]
    put(pm, ref_col, .45)
    water = np.maximum(water * (1 - pm), pm * .5)
    # светящаяся пена у подножия водопада
    foam = np.exp(-(((XX - 730) / 70) ** 2 + ((YY - 900) / 10) ** 2))
    img += (NEON - img) * (foam * .7)[..., None]

    # --- пригорок с домиком (справа)
    cv, cd = canvas()
    hill = [(1100, 1200), (1120, 960), (1200, 925), (1300, 908), (1450, 900), (1650, 905), (1800, 930), (1920, 960), (1920, 1200)]
    cd.polygon([(x * SS, y * SS) for x, y in hill], fill=255)
    hm = down(cv)
    put(hm, C('#0b110c') * (.8 + .4 * fbm(rng, 5, 30)[..., None]), .3)
    img += (SALAD - img) * (rim(hm, 3, 1) * .5 * light_falloff(900, .3))[..., None]

    cabin = paint_cabin(rng)
    ca = cabin['rgba']
    a = ca[..., 3]
    put(a, ca[..., :3], .3)
    img += (NEON - img) * (rim(a, 2.5, .8) * .55 * light_falloff(1100, .35))[..., None]

    # тёплый свет от окон: на землю, крыльцо и траву
    wl = np.zeros((H, W), np.float32)
    for (x0, y0, x1, y1) in cabin['windows']:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dd = np.sqrt((XX - cx) ** 2 + ((YY - cy) / 1.2) ** 2)
        wl += np.exp(-(dd / 110) ** 2) * .6 + np.exp(-(dd / 320) ** 2) * .25
        dd2 = np.sqrt(((XX - cx) / 2.0) ** 2 + ((YY - cabin['ground'] - 26) / .6) ** 2)
        wl += np.exp(-(dd2 / 50) ** 2) * .45
    lx, ly = cabin['lantern']
    dl = np.sqrt((XX - lx) ** 2 + (YY - ly) ** 2)
    wl += np.exp(-(dl / 60) ** 2) * .5 + np.exp(-(dl / 200) ** 2) * .2
    img += WARM * (wl * .10)[..., None]
    for (x0, y0, x1, y1) in cabin['windows']:
        m = ((XX >= x0) & (XX <= x1) & (YY >= y0) & (YY <= y1)).astype(np.float32)
        cross = ((np.abs(XX - (x0 + x1) / 2) < 2) | (np.abs(YY - (y0 + y1) / 2) < 2))
        m *= ~cross
        grad = 1 - (YY - y0) / (y1 - y0) * .25
        img = over(img, m, WARM * grad[..., None])
    ldot = np.exp(-dl ** 2 / 16)
    img += (WARM - img) * np.clip(ldot * 1.5, 0, 1)[..., None]

    # --- обрамление: лиственные деревья по краям, кроны аркой над кадром
    keep_clear = [(1240, 600, 1760, 960), (640, 330, 840, 900)]  # домик и водопад не закрываем

    def clear(x, y):
        return not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in keep_clear)

    for side in ('right', 'left'):
        cv, cd = canvas()
        lv_, lvd = canvas()
        leaves = []
        if side == 'right':
            trunk = [(1905, 1210), (1885, 1000), (1862, 820), (1850, 640), (1832, 470)]
            crowns = [((1832, 470), 118, 170, 34), ((1850, 640), 150, 150, 26), ((1862, 820), 160, 120, 22),
                      ((1832, 470), 80, 130, 24)]
        else:
            trunk = [(30, 1210), (52, 1000), (80, 820), (100, 640), (122, 480)]
            crowns = [((122, 480), 62, 170, 32), ((100, 640), 30, 150, 24), ((80, 820), 25, 120, 20),
                      ((122, 480), 100, 130, 24)]
        for k in range(len(trunk) - 1):
            (ax, ay), (bx, by) = trunk[k], trunk[k + 1]
            wa, wb = 54 - k * 9, 54 - (k + 1) * 9
            cd.polygon([((ax - wa / 2) * SS, ay * SS), ((ax + wa / 2) * SS, ay * SS),
                        ((bx + wb / 2) * SS, by * SS), ((bx - wb / 2) * SS, by * SS)], fill=255)
            cd.ellipse([(bx - wb / 2) * SS, (by - wb / 2) * SS, (bx + wb / 2) * SS, (by + wb / 2) * SS], fill=255)
        for (ox, oy), ang, ln, wd in crowns:
            branch(cd, leaves, ox, oy, math.radians(ang), ln, wd, 5, rng, 26)
        leaves = [l for l in leaves if clear(l[0], l[1])]
        foliage(lvd, leaves, rng, 80)
        bm = down(cv)
        fm = down(lv_)
        trunk_col = C('#0a0c09') * (.8 + .4 * fbm(rng, 4, 40)[..., None])
        put(bm, trunk_col, .12)
        img += (SALAD - img) * (rim(bm, 2.5, .8) * .55 * light_falloff(1300, .3))[..., None]
        ftex = fbm(rng, 5, 30)
        fcol = C('#0c180f') * (.6 + .7 * ftex[..., None])
        put(fm, fcol, .1, leaf=1.0, sw=.35)
        img += (NEON - img) * (rim(fm, 3, 1.0) * .85 * light_falloff(1300, .35))[..., None]
        glint = np.clip(rim(fm, 1.5, .5) * (ftex > .6), 0, 1)
        img += (NEON - img) * (glint * .5)[..., None]

    # --- передний план: берег, камни, папоротники, трава
    cv, cd = canvas()
    cd.polygon([(0, 1030 * SS), (300 * SS, 1015 * SS), (600 * SS, 1030 * SS), (900 * SS, 1022 * SS),
                (1200 * SS, 1035 * SS), (W * SS, 1010 * SS), (W * SS, H * SS), (0, H * SS)], fill=255)
    gm = down(cv)
    put(gm, C('#080b08') * (.8 + .4 * fbm(rng, 5, 40)[..., None]), .05)

    cv, cd = canvas()
    for (cx, cy, rx, ry) in ((420, 1060, 90, 50), (560, 1080, 60, 34), (980, 1055, 110, 55), (1120, 1090, 70, 40),
                             (310, 1000, 40, 22), (1180, 990, 46, 24), (820, 1120, 80, 40)):
        rock(cd, cx, cy, rx, ry, rng)
    rm = down(cv)
    put(rm, C('#0d120e') * (.7 + .6 * fbm(rng, 5, 25)[..., None]), .06)
    img += (NEON - img) * (rim(rm, 3, 1) * .8 * light_falloff(1000, .3))[..., None]

    cv, cd = canvas()
    for _ in range(26):
        x = rng.choice([rng.uniform(0, 520), rng.uniform(1050, 1500), rng.uniform(1650, W)])
        fern(cd, x, 1205, rng.uniform(70, 150), rng.choice([math.radians(55), math.radians(125)]) + rng.uniform(-.2, .2), rng)
    for _ in range(1100):
        x = rng.uniform(0, W)
        y = rng.uniform(1015, 1210)
        grass(cd, x, y, rng.uniform(10, 45) * (.6 + (y - 1000) / 300), rng)
    for _ in range(500):  # трава на берегу пруда и у домика
        x = rng.uniform(300, 1920)
        y = rng.uniform(895, 1015)
        if pm[int(min(y, H - 1)), int(min(x, W - 1))] > .5:
            continue
        grass(cd, x, y, rng.uniform(6, 20), rng)
    fm = down(cv)
    put(fm, C('#060906'), .04, leaf=.25, sw=1.0)
    img += (SALAD - img) * (rim(fm, 2, .6) * .32 * light_falloff(1300, .3))[..., None]
    img += WARM * (wl * fm * .15)[..., None]

    # общая виньетка
    vig = np.clip(1 - (((XX - W / 2) / (W * .75)) ** 2 + ((YY - H * .45) / (H * .8)) ** 2), 0, 1) ** .6
    img *= (.55 + .45 * vig)[..., None]

    return dict(img=img, depth=depth, leaf=leafm, water=water, sway=sway, cabin=cabin,
                fall=(fall_x0, fall_x1, fall_top, fall_bot), pond_y=pond_y)


def paint_cabin(rng):
    S = SS
    im = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, x1 = 1330, 1610
    ground = 905
    wall_top = 780
    peak = 672
    cx = (x0 + x1) / 2

    def P(*pts):
        return [(x * S, y * S) for x, y in pts]

    def col(h, f=1.0):
        c = C(h) * f
        return tuple(int(min(255, v)) for v in c) + (255,)

    # стены из брёвен
    d.rectangle(P((x0, wall_top), (x1, ground)), fill=col('#1a140e'))
    n = 10
    lh = (ground - wall_top) / n
    for i in range(n):
        y = wall_top + i * lh
        f = rng.uniform(.85, 1.1)
        d.rounded_rectangle(P((x0 - 10, y + 1), (x1 + 10, y + lh - 1)), radius=lh / 2 * S, fill=col('#3a2c1d', f))
        d.line(P((x0 - 6, y + lh * .3), (x1 + 6, y + lh * .3)), fill=col('#4a3925', f), width=S)  # блик на бревне
        d.line(P((x0 - 6, y + lh - 2), (x1 + 6, y + lh - 2)), fill=col('#140f0a'), width=S)
        for k in range(int((x1 - x0) / 40)):  # сучки и трещины
            kx = rng.uniform(x0, x1)
            d.line(P((kx, y + lh * .45), (kx + rng.uniform(6, 18), y + lh * .5)), fill=col('#24190f'), width=S)
        for ex in (x0 - 10, x1 + 10):  # торцы с кольцами
            r = lh * .48
            d.ellipse(P((ex - r, y + lh / 2 - r), (ex + r, y + lh / 2 + r)), fill=col('#5a4630', f))
            d.ellipse(P((ex - r * .6, y + lh / 2 - r * .6), (ex + r * .6, y + lh / 2 + r * .6)), outline=col('#3d2f20'), width=S)
            d.ellipse(P((ex - r * .25, y + lh / 2 - r * .25), (ex + r * .25, y + lh / 2 + r * .25)), outline=col('#3d2f20'), width=S)
    # фронтон
    d.polygon(P((x0 + 4, wall_top + 2), (cx, peak + 20), (x1 - 4, wall_top + 2)), fill=col('#24190f'))
    for i in range(9):
        y = peak + 26 + i * 10
        half = (y - peak - 20) / (wall_top - peak - 20) * ((x1 - x0) / 2 - 4)
        d.line(P((cx - half, y), (cx + half, y)), fill=col('#2f2216'), width=2 * S)
    # круглое окошко на фронтоне
    d.ellipse(P((cx - 13, peak + 52), (cx + 13, peak + 78)), fill=col('#120d08'))
    # крыша с черепицей-дранкой
    ov = 40
    roofL = [(x0 - ov, wall_top + 16), (cx, peak - 6)]
    roofR = [(cx, peak - 6), (x1 + ov, wall_top + 16)]
    d.polygon(P((x0 - ov, wall_top + 16), (cx, peak - 6), (x1 + ov, wall_top + 16), (x1 + ov, wall_top + 30),
                (cx, peak + 10), (x0 - ov, wall_top + 30)), fill=col('#14130f'))
    for row in range(7):  # ряды дранки вдоль скатов
        f = row / 7
        for (a, b) in (roofL, roofR):
            ax, ay = a[0] + (b[0] - a[0]) * 0, a[1]
            for k in range(26):
                t = k / 26
                px = a[0] + (b[0] - a[0]) * t
                py = a[1] + (b[1] - a[1]) * t + 14 * f + 2
                if (a is roofL and px > cx - 4) or (a is roofR and px < cx + 4):
                    continue
                d.line(P((px, py), (px, py + 11)), fill=col('#1d1c17', rng.uniform(.8, 1.2)), width=S)
    d.line(P((x0 - ov, wall_top + 30), (cx, peak + 10), (x1 + ov, wall_top + 30)), fill=col('#0b0b09'), width=3 * S)
    # мох на крыше
    for _ in range(140):
        t = rng.random()
        side = rng.choice([0, 1])
        a, b = (roofL if side == 0 else roofR)
        px = a[0] + (b[0] - a[0]) * t
        py = a[1] + (b[1] - a[1]) * t + rng.uniform(0, 12)
        r = rng.uniform(1.5, 4)
        d.ellipse(P((px - r, py - r), (px + r, py + r)), fill=col('#1f2d18', rng.uniform(.8, 1.3)))
    # каменная труба
    chx = cx + 70
    ch_top = peak + 4
    for row in range(8):
        for k in range(3):
            bx = chx - 18 + k * 12 + (6 if row % 2 else 0) - 6
            by = ch_top + row * 9
            d.rectangle(P((bx, by), (bx + 11, by + 8)), fill=col('#2a2b27', rng.uniform(.7, 1.2)))
    d.rectangle(P((chx - 24, ch_top - 6), (chx + 24, ch_top + 2)), fill=col('#33342f'))
    # окна с рамами и наличниками
    windows = []
    for fx in (.43, .70):
        wx0 = x0 + (x1 - x0) * fx
        wx1 = wx0 + 54
        wy0, wy1 = wall_top + 34, wall_top + 84
        d.rectangle(P((wx0 - 8, wy0 - 10), (wx1 + 8, wy1 + 6)), fill=col('#2a1f14'))
        d.polygon(P((wx0 - 12, wy0 - 10), ((wx0 + wx1) / 2, wy0 - 20), (wx1 + 12, wy0 - 10)), fill=col('#33271a'))
        d.rectangle(P((wx0 - 12, wy1 + 4), (wx1 + 12, wy1 + 10)), fill=col('#3a2c1d'))
        # горшок с цветком на подоконнике
        d.rectangle(P((wx1 - 14, wy1 - 2), (wx1 - 4, wy1 + 4)), fill=col('#3d2a1c'))
        windows.append((wx0, wy0, wx1, wy1))
    # дверь
    dx0, dx1 = x0 + 34, x0 + 84
    d.rectangle(P((dx0 - 6, wall_top + 20), (dx1 + 6, ground)), fill=col('#2a1f14'))
    d.rectangle(P((dx0, wall_top + 26), (dx1, ground)), fill=col('#1d150d'))
    for k in range(4):
        d.line(P((dx0 + 6 + k * 12, wall_top + 28), (dx0 + 6 + k * 12, ground - 2)), fill=col('#150f09'), width=S)
    d.ellipse(P((dx1 - 12, wall_top + 70), (dx1 - 6, wall_top + 76)), fill=col('#8a7a4a'))
    # крыльцо со ступеньками и столбиками
    d.rectangle(P((x0 - 40, ground - 6), (x0 + 130, ground + 4)), fill=col('#2c2116'))
    d.rectangle(P((x0 - 30, ground + 4), (x0 + 120, ground + 12)), fill=col('#231a11'))
    d.rectangle(P((x0 - 20, ground + 12), (x0 + 110, ground + 18)), fill=col('#1c150e'))
    for px in (x0 - 34, x0 + 124):
        d.rectangle(P((px - 3, wall_top + 18), (px + 3, ground - 6)), fill=col('#2f2418'))
    d.line(P((x0 - 40, wall_top + 18), (x0 + 130, wall_top + 18)), fill=col('#2f2418'), width=3 * S)
    # фонарь у двери
    lx, ly = dx1 + 22, wall_top + 44
    d.line(P((lx, ly - 18), (lx, ly - 10)), fill=col('#1a1a18'), width=2 * S)
    d.rectangle(P((lx - 6, ly - 10), (lx + 6, ly + 8)), fill=col('#1a1a18'))
    d.rectangle(P((lx - 4, ly - 7), (lx + 4, ly + 5)), fill=col('#e8eea0'))
    # поленница справа
    for row in range(4):
        for k in range(7 - row % 2):
            px = x1 + 26 + k * 12 + (6 if row % 2 else 0)
            py = ground - 8 - row * 11
            d.ellipse(P((px - 6, py - 6), (px + 6, py + 6)), fill=col('#5a4630', rng.uniform(.7, 1.1)))
            d.ellipse(P((px - 2.5, py - 2.5), (px + 2.5, py + 2.5)), fill=col('#3a2c1d'))
    d.polygon(P((x1 + 16, ground - 52), (x1 + 120, ground - 52), (x1 + 126, ground - 46), (x1 + 12, ground - 46)), fill=col('#14130f'))
    # бочка для дождевой воды
    d.rounded_rectangle(P((x0 - 74, ground - 44), (x0 - 44, ground + 2)), radius=6 * S, fill=col('#2c2116'))
    for yy in (ground - 36, ground - 8):
        d.line(P((x0 - 74, yy), (x0 - 44, yy)), fill=col('#151412'), width=2 * S)

    im = im.resize((W, H), Image.LANCZOS)
    rgba = np.asarray(im, np.float32)
    out = rgba.copy()
    a = rgba[..., 3:4] / 255
    out[..., :3] = np.where(a > 0, rgba[..., :3] / np.maximum(a, 1e-3), 0)
    out[..., 3] = a[..., 0]
    return dict(rgba=out, windows=windows, lantern=(lx, ly - 1), chimney=(chx, ch_top - 8),
                ground=ground, x0=x0, x1=x1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--seed', type=int, default=7)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    s = paint(a.seed)
    img = s['img'] + np.random.default_rng(1).normal(0, 1.1, (H, W, 1)).astype(np.float32)
    img = np.clip(img, 0, 255)
    Image.fromarray(img.astype(np.uint8)).save(os.path.join(a.out, 'still.png'))
    masks = np.dstack([s['leaf'], s['water'], s['depth'], s['sway']])
    top = np.dstack([img, np.full((H, W), 255, np.float32)])
    full = np.concatenate([top, np.clip(masks, 0, 1) * 255], axis=0).astype(np.uint8)
    Image.fromarray(full, 'RGBA').save(os.path.join(a.out, 'scene.png'))

    c = s['cabin']
    w0, w1 = c['windows']
    fx0, fx1, ftop, fbot = s['fall']
    with open(os.path.join(a.out, 'consts.glsl'), 'w') as f:
        f.write('// сгенерировано paint.py — координаты в пространстве 1920x1200\n')
        f.write(f'const vec4 WIN0 = vec4({w0[0]:.1f}, {w0[1]:.1f}, {w0[2]:.1f}, {w0[3]:.1f});\n')
        f.write(f'const vec4 WIN1 = vec4({w1[0]:.1f}, {w1[1]:.1f}, {w1[2]:.1f}, {w1[3]:.1f});\n')
        f.write(f'const vec2 LANTERN = vec2({c["lantern"][0]:.1f}, {c["lantern"][1]:.1f});\n')
        f.write(f'const vec2 CHIMNEY = vec2({c["chimney"][0]:.1f}, {c["chimney"][1]:.1f});\n')
        f.write(f'const vec4 FALL = vec4({fx0:.1f}, {fx1:.1f}, {ftop:.1f}, {fbot:.1f});\n')
        f.write(f'const float POND_Y = {s["pond_y"]:.1f};\n')
        f.write(f'const float CABIN_GROUND = {c["ground"]:.1f};\n')
    print('готово:', a.out)


if __name__ == '__main__':
    main()
