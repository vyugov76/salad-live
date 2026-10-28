#version 100
#ifdef GL_ES
precision highp float;
#endif
// Salad Night — анимация поверх запечённой сцены (paint.py).
// tex 1920x2400: верх — цвет, низ — маски (R листва, G вода, B глубина, A качание).
// Координаты окон/фонаря/трубы приходят из consts.glsl (подставляется рендерером).

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float time;

// настройки из трея (0 — выключено, 1 — по умолчанию)
uniform float u_rain_speed;
uniform float u_rain_density;
uniform float u_fireflies;      // количество, 0..40
uniform float u_firefly_glow;
uniform float u_flicker;        // мерцание света в окнах
uniform float u_windows;        // яркость окон
uniform float u_waves;          // волны света по листве
uniform float u_fog;
uniform float u_smoke;
uniform float u_water;          // скорость воды
uniform float u_sway;           // качание травы

//@CONSTS@

const vec2 RES = vec2(1920.0, 1200.0);
const vec3 SALAD = vec3(166.0, 216.0, 107.0) / 255.0;
const vec3 NEON = vec3(196.0, 240.0, 140.0) / 255.0;
const vec3 MINT = vec3(150.0, 230.0, 190.0) / 255.0;
const vec3 WARM = vec3(232.0, 238.0, 160.0) / 255.0;
const vec3 RAIN = vec3(175.0, 200.0, 170.0) / 255.0;
const vec3 FOGC = vec3(40.0, 58.0, 44.0) / 255.0;
const vec3 SMOKE = vec3(70.0, 84.0, 72.0) / 255.0;
const float SLANT = 0.14;
const float TAU = 6.2831853;
// Всё периодическое повторяется за LOOP секунд; рендерер раз в LOOP «перематывает»
// время назад, чтобы float32 не терял точность.
const float LOOP = 3600.0;
float T;

float hash(float n) { return fract(sin(n * 127.1) * 43758.5453); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash2(i), b = hash2(i + vec2(1.0, 0.0));
    float c = hash2(i + vec2(0.0, 1.0)), d = hash2(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm3(vec2 p) {
    return vnoise(p) * 0.55 + vnoise(p * 2.03 + 7.1) * 0.3 + vnoise(p * 4.1 + 3.3) * 0.15;
}

vec3 colorAt(vec2 uv) {
    return texture2D(tex, vec2(uv.x, clamp(uv.y, 0.0, 0.9995) * 0.5)).rgb;
}
vec4 masksAt(vec2 uv) {
    return texture2D(tex, vec2(uv.x, 0.5 + clamp(uv.y, 0.0, 0.9995) * 0.5));
}

float inRect(vec2 p, vec4 r) {
    return step(r.x, p.x) * step(p.x, r.z) * step(r.y, p.y) * step(p.y, r.w);
}

float windowLight(vec2 p) {
    vec2 c0 = (WIN0.xy + WIN0.zw) * 0.5, c1 = (WIN1.xy + WIN1.zw) * 0.5;
    float d0 = length((p - c0) * vec2(1.0, 0.83)), d1 = length((p - c1) * vec2(1.0, 0.83));
    float dl = length(p - LANTERN);
    return exp(-pow(d0 / 110.0, 2.0)) * 0.6 + exp(-pow(d0 / 320.0, 2.0)) * 0.25
         + exp(-pow(d1 / 110.0, 2.0)) * 0.6 + exp(-pow(d1 / 320.0, 2.0)) * 0.25
         + exp(-pow(dl / 60.0, 2.0)) * 0.5 + exp(-pow(dl / 200.0, 2.0)) * 0.2;
}

float fallGlow(vec2 p) {
    float cx = (FALL.x + FALL.y) * 0.5;
    float dx = (p.x - cx) / 90.0;
    float inside = smoothstep(FALL.z - 40.0, FALL.z + 40.0, p.y) * (1.0 - smoothstep(FALL.w, FALL.w + 80.0, p.y));
    return exp(-dx * dx) * inside;
}

// Один слой дождя: колонки, в каждой капли падают сверху вниз наискосок.
float rainLayer(vec2 p, float cw, float len, float speed, float width, float density, float seed) {
    float xs = p.x - SLANT * p.y;
    float col = floor(xs / cw);
    float h1 = hash(col + seed), h2 = hash(col * 1.7 + seed + 3.1), h3 = hash(col * 2.3 + seed + 7.7);
    float period = len * (3.0 + 5.0 * h2);
    // целое число отрезков за LOOP — анимация без шва при перемотке
    float n = max(1.0, floor(speed * u_rain_speed * (0.85 + 0.3 * h3) * LOOP / period));
    float v = n * period / LOOP;
    float yy = p.y - T * v + h1 * period * 13.0;
    float cell = mod(floor(yy / period), n);
    if (hash2(vec2(col, cell) + seed) > density * u_rain_density) return 0.0;
    float ly = mod(yy, period);
    float off = (hash2(vec2(cell, col) + seed * 1.3) - 0.5) * (cw - width * 2.0);
    float lx = (xs - (col + 0.5) * cw) - off;
    float across = 1.0 - smoothstep(width * 0.5, width * 0.5 + 0.8, abs(lx));
    float along = step(ly, len);
    float head = ly / len;                       // низ капли (голова) ярче
    return across * along * (0.25 + 0.75 * head * head);
}

float ripples(vec2 p, float onWater) {
    if (p.y < POND_Y) return 0.0;
    vec2 cell = vec2(64.0, 22.0);
    vec2 id = floor(p / cell);
    float r = 0.0;
    for (int dx = -1; dx <= 1; dx++) {
        vec2 cid = id + vec2(float(dx), 0.0);
        float h = hash2(cid);
        if (h > 0.25 + 0.5 * u_rain_density) continue;
        float per = LOOP / floor(LOOP / (1.2 + 2.0 * hash2(cid + 9.1)));
        float age = mod(T + h * 17.0, per) / max(u_rain_speed, 0.2);
        if (age > 0.8) continue;
        vec2 c = (cid + vec2(0.2 + 0.6 * hash2(cid + 1.7), 0.5)) * cell;
        float rad = 2.0 + age * (18.0 + 14.0 * onWater);
        float d = length((p - c) * vec2(1.0, 1.0 / 0.3));
        r += (1.0 - smoothstep(0.0, 1.2, abs(d - rad))) * (1.0 - age / 0.8);
    }
    return r;
}

float fireflies(vec2 p) {
    if (u_fireflies < 0.5 || p.y < 480.0 || p.y > 1180.0) return 0.0;
    float g = 0.0;
    for (int i = 0; i < 40; i++) {
        float fi = float(i);
        if (fi >= u_fireflies) break;
        vec2 base = vec2(0.04 + 0.92 * hash(fi + 0.3), 0.5 + 0.42 * hash(fi + 5.1)) * RES;
        vec2 amp = vec2(25.0 + 70.0 * hash(fi + 2.2), 12.0 + 35.0 * hash(fi + 4.4));
        vec2 fr = floor(vec2(0.03 + 0.05 * hash(fi + 6.6), 0.04 + 0.07 * hash(fi + 8.8)) * LOOP) / LOOP;
        float ph = TAU * hash(fi + 9.9);
        vec2 pos = base + amp * vec2(sin(TAU * fr.x * T + ph), sin(TAU * fr.y * T + ph * 1.7));
        vec2 d = p - pos;
        float dd = dot(d, d);
        if (dd > 2500.0) continue;
        float pf = floor((0.1 + 0.15 * hash(fi + 3.3)) * LOOP) / LOOP;
        float pulse = pow(max(0.0, sin(TAU * pf * T + ph * 2.0)), 3.0);
        float r = 1.5 + 1.5 * hash(fi + 7.7);
        g += pulse * (exp(-dd / (r * r)) + 0.3 * exp(-dd / pow(r * 7.0, 2.0)));
    }
    return g * u_firefly_glow;
}

float smoke(vec2 p) {
    vec2 q = p - CHIMNEY;
    if (u_smoke <= 0.01 || q.y > 4.0 || q.y < -340.0 || abs(q.x - (-q.y) * 0.25) > 120.0) return 0.0;
    float h = -q.y;                              // высота над трубой
    float cx = h * 0.25 + sin(h * 0.018 - T * 0.6) * (6.0 + h * 0.08);
    float w = 8.0 + h * 0.22;
    float across = exp(-pow((q.x - cx) / w, 2.0));
    float n = fbm3(vec2(q.x * 0.025, (q.y + T * 22.0) * 0.02));
    float fade = smoothstep(0.0, 18.0, h) * (1.0 - smoothstep(120.0, 340.0, h));
    return clamp(across * smoothstep(0.35, 0.75, n) * fade, 0.0, 1.0) * u_smoke;
}

void main() {
    T = mod(time, LOOP);
    vec2 uv = v_texcoord;
    vec2 p = uv * RES;
    vec4 m = masksAt(uv);
    float leaf = m.r, water = m.g, depth = m.b, sway = m.a;

    // искажения: качание травы/листвы и рябь на пруду
    vec2 off = vec2(0.0);
    float gust = 0.6 + 0.4 * sin(T * 0.35 + p.x * 0.002);
    off.x += sway * u_sway * gust * (sin(T * 1.6 + p.x * 0.03 + p.y * 0.05) * 1.4 + sin(T * 2.7 + p.x * 0.07) * 0.6);
    float pond = smoothstep(0.3, 0.45, water) * (1.0 - smoothstep(0.6, 0.75, water));
    off += pond * vec2(sin(p.y * 0.45 + T * 1.7 * u_water) * 1.4, sin(p.x * 0.05 + p.y * 0.3 + T * 1.1 * u_water) * 1.8);
    vec3 col = colorAt(uv + off / RES);

    // волны света по листве
    float t = T / 12.0;
    float w1 = sin(p.x * 0.0042 + p.y * 0.0021 - TAU * t) * 0.5 + 0.5;
    float w2 = sin(-p.x * 0.0027 + p.y * 0.0049 - TAU * t * 2.0 + 1.3) * 0.5 + 0.5;
    float w3 = sin(p.x * 0.0011 - p.y * 0.0013 + TAU * t + 0.4) * 0.5 + 0.5;
    float wave = (pow(w1, 6.0) * 0.65 + pow(w2, 8.0) * 0.45) * (0.55 + 0.45 * w3);
    col += (NEON - col) * leaf * wave * 0.15 * u_waves;

    // водопад: бегущие вниз струи, пена и брызги у подножия
    float fall = smoothstep(0.8, 0.95, water);
    if (fall > 0.0) {
        float s1 = vnoise(vec2(p.x * 0.16, p.y * 0.012 - T * 2.6 * u_water));
        float s2 = vnoise(vec2(p.x * 0.33 + 5.0, p.y * 0.02 - T * 3.4 * u_water));
        float streak = smoothstep(0.45, 0.95, s1 * 0.6 + s2 * 0.5);
        col = mix(col, NEON, fall * streak * 0.65);
        col += MINT * fall * 0.08;
    }
    float fx = (p.x - (FALL.x + FALL.y) * 0.5) / 75.0;
    float fy = (p.y - FALL.w) / 26.0;
    float foamZone = exp(-fx * fx - fy * fy);
    if (foamZone > 0.01) {
        float fn = fbm3(vec2(p.x * 0.05, p.y * 0.08 - T * 1.5 * u_water));
        col += NEON * foamZone * smoothstep(0.4, 0.9, fn) * 0.6;
    }
    // общее мягкое «дыхание» света от водопада
    col += SALAD * fallGlow(p) * (0.04 + 0.02 * sin(T * 0.8)) ;

    // пруд: блики
    if (pond > 0.0) {
        float g = pow(vnoise(vec2(p.x * 0.04 + T * 0.3 * u_water, p.y * 0.35)), 16.0);
        col += NEON * g * pond * (0.25 + fallGlow(vec2(p.x, FALL.w)) * 1.2);
    }

    // свет в окнах и фонаре: яркость и мерцание
    float fl = u_flicker * (0.07 * sin(TAU * T * 0.58) + 0.05 * sin(TAU * T * 1.27 + 1.0)
              + 0.06 * (vnoise(vec2(T * 3.1, 0.5)) - 0.5) * 2.0);
    float flL = u_flicker * 0.14 * (vnoise(vec2(T * 5.3, 9.0)) - 0.5) * 2.0;   // фонарь мерцает живее
    float win = max(inRect(p, WIN0), inRect(p, WIN1));
    float lightK = (u_windows - 1.0) + fl;
    col = mix(col, col * clamp(u_windows + fl, 0.0, 2.0), win);
    float wl = windowLight(p);
    col += WARM * wl * 0.12 * lightK;
    float dl = length(p - LANTERN);
    col += WARM * (exp(-dl * dl / 30.0) * 0.6 + exp(-dl * dl / 3600.0) * 0.12) * (u_windows - 1.0 + flL + 0.2);

    // дым из трубы
    float sm = smoke(p);
    col = mix(col, SMOKE + WARM * 0.05, sm * 0.6);

    // туман: плывёт между слоями леса и у воды
    if (u_fog > 0.0) {
        float fn = fbm3(vec2(p.x * 0.0025 + T * 0.012, p.y * 0.006 - T * 0.004));
        float band = exp(-pow((depth - 0.5) / 0.16, 2.0)) * 0.5 + exp(-pow((p.y - 905.0) / 45.0, 2.0)) * 0.45;
        col = mix(col, FOGC + SALAD * 0.04, clamp(band * smoothstep(0.35, 0.8, fn) * 0.5 * u_fog, 0.0, 0.6));
    }

    // дождь
    float light = clamp(wl + fallGlow(p) * 0.8, 0.0, 1.3);
    float r = rainLayer(p, 9.0, 16.0, 260.0, 1.0, 0.55, 1.0) * 0.16
            + rainLayer(p, 17.0, 28.0, 420.0, 1.1, 0.5, 2.0) * 0.26
            + rainLayer(p, 41.0, 54.0, 680.0, 1.8, 0.38, 3.0) * 0.36;
    r += ripples(p, pond) * 0.35 * min(u_rain_density * 2.0, 1.0);
    col += (RAIN - col) * clamp(r * (0.55 + 1.6 * light), 0.0, 1.0) * 0.55;

    // светлячки
    col += (NEON - col) * clamp(fireflies(p), 0.0, 1.0);

    gl_FragColor = vec4(col, 1.0);
}
