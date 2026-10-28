#!/usr/bin/env python3
"""Живые обои Salad Night для GNOME (Wayland) + значок в трее с настройками.

Сцена запекается один раз (paint.py → scene.png), а дождь, водопад, туман,
дым, светлячков и свет в окнах каждый кадр считает шейдер (scene.frag) на
видеокарте. Настройки из окна в трее подаются в шейдер на лету.

Окно обоев — XWayland с типом _NET_WM_WINDOW_TYPE_DESKTOP: Mutter держит его
в самом нижнем слое, его нет в Alt-Tab, доке и обзоре, клики проходят сквозь.

  salad-live.py            запустить (повторный запуск перезапускает)
  salad-live.py --stop     остановить
  salad-live.py --settings открыть окно настроек (запустит обои, если не запущены)
  salad-live.py --version  версия

Экономия: обои ставятся на паузу, когда рабочий стол закрыт окнами или открыт обзор
(об этом сообщает расширение GNOME Shell из комплекта), когда экран заблокирован
или погашен; от батареи частота кадров снижается до battery_fps.
"""
__version__ = '1.0.0'
import json
import os
import signal
import sys

os.environ['GDK_BACKEND'] = 'x11'
os.environ['GST_GL_WINDOW'] = 'x11'  # иначе GstGL берёт Wayland и падает на X11-окне
os.environ.setdefault('GST_GL_PLATFORM', 'egl')

import gi  # noqa: E402
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import Gdk, GdkX11, Gio, GLib, Gst, GstVideo, Gtk  # noqa: E402,F401
import cairo  # noqa: E402

try:  # GLib >= 2.80; на старых системах — прежний API
    gi.require_version('GLibUnix', '2.0')
    from gi.repository import GLibUnix
    unix_signal_add = GLibUnix.signal_add
except (ValueError, ImportError):
    unix_signal_add = GLib.unix_signal_add

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = GLib.get_user_runtime_dir()
PIDFILE = os.path.join(RUNTIME, 'salad-live.pid')
CONFIG = os.path.join(GLib.get_user_config_dir(), 'salad-live', 'settings.json')
LOOP = 3600  # период анимации в шейдере, секунды (см. LOOP в scene.frag)
DEBUG = bool(os.environ.get('SALAD_LIVE_DEBUG'))

# D-Bus: через него расширение GNOME Shell сообщает, виден ли рабочий стол
BUS_NAME = 'io.github.vyugov76.SaladLive'
BUS_PATH = '/io/github/vyugov76/SaladLive'
BUS_XML = f"""<node><interface name="{BUS_NAME}">
  <method name="SetDesktopVisible"><arg type="b" direction="in" name="visible"/></method>
  <method name="ShowSettings"/>
</interface></node>"""


def log(*a):
    if DEBUG:
        print('[salad-live]', *a, file=sys.stderr, flush=True)

# ключ, подпись, мин, макс, шаг, по умолчанию
SLIDERS = [
    ('Дождь', None),
    ('u_rain_speed', 'Скорость', 0.2, 2.5, 0.05, 1.0),
    ('u_rain_density', 'Плотность', 0.0, 1.6, 0.05, 1.0),
    ('Светлячки', None),
    ('u_fireflies', 'Количество', 0, 40, 1, 18),
    ('u_firefly_glow', 'Яркость', 0.0, 2.0, 0.05, 1.0),
    ('Домик', None),
    ('u_windows', 'Свет в окнах', 0.0, 1.6, 0.05, 1.0),
    ('u_flicker', 'Мерцание', 0.0, 3.0, 0.05, 1.0),
    ('u_smoke', 'Дым из трубы', 0.0, 2.0, 0.05, 1.0),
    ('Природа', None),
    ('u_waves', 'Волны света', 0.0, 3.0, 0.05, 1.0),
    ('u_fog', 'Туман', 0.0, 2.5, 0.05, 1.0),
    ('u_water', 'Течение воды', 0.0, 2.5, 0.05, 1.0),
    ('u_sway', 'Ветер в траве', 0.0, 3.0, 0.05, 1.0),
]
DEFAULTS = {s[0]: s[5] for s in SLIDERS if s[1] is not None}
# battery_saver / battery_fps — без ползунков, правятся в settings.json
DEFAULTS.update(fps=24, paused=False, battery_saver=True, battery_fps=12)
FPS_CHOICES = (15, 20, 24, 30)

CSS = b"""
.salad-panel { background: #0f110f; color: #d9dfd4; }
.salad-panel .head { font-weight: 700; font-size: 15px; color: #a6d86b; }
.salad-panel .group { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: #858d80; margin-top: 10px; }
.salad-panel .val { color: #a6d86b; font-feature-settings: "tnum"; min-width: 40px; }
.salad-panel scale trough { background: #262b25; min-height: 4px; border-radius: 4px; }
.salad-panel scale highlight { background: #a6d86b; border-radius: 4px; }
.salad-panel scale slider { background: #d9dfd4; min-width: 14px; min-height: 14px; border-radius: 50%; border: none; box-shadow: 0 0 0 3px rgba(166,216,107,.18); }
.salad-panel button { background: #1d211d; color: #d9dfd4; border: 1px solid #262b25; border-radius: 8px; box-shadow: none; }
.salad-panel button:hover { border-color: #a6d86b; }
.salad-panel button.accent { background: #a6d86b; color: #0f110f; border-color: #a6d86b; }
.salad-panel radiobutton { color: #d9dfd4; }
"""


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


def read_pid():
    try:
        return int(open(PIDFILE).read())
    except (OSError, ValueError):
        return None


class Wallpaper:
    """Окно-«рабочий стол» на одном мониторе и GL-конвейер, рисующий в него."""

    def __init__(self, monitor, settings):
        geo = monitor.get_geometry()
        self.win = Gtk.Window(title='salad-live')
        self.win.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.win.set_decorated(False)
        self.win.set_skip_taskbar_hint(True)
        self.win.set_skip_pager_hint(True)
        self.win.set_accept_focus(False)
        self.win.set_keep_below(True)
        self.win.stick()
        self.win.move(geo.x, geo.y)
        self.win.set_default_size(geo.width, geo.height)
        self.win.set_size_request(geo.width, geo.height)
        self.area = Gtk.DrawingArea()
        # пока видеокарта не отдала первый кадр — тёмный фон, а не мусор
        self.area.connect('draw', lambda w, cr: (cr.set_source_rgb(15 / 255, 17 / 255, 15 / 255), cr.paint()))
        self.win.add(self.area)
        self.win.connect('realize', lambda w: w.get_window().input_shape_combine_region(cairo.Region(), 0, 0))
        self.win.show_all()

        frag = open(os.path.join(HERE, 'scene.frag')).read()
        self.frag = frag.replace('//@CONSTS@', open(os.path.join(HERE, 'consts.glsl')).read())
        self.pipe = None
        self.fps = None
        self.paused = None
        self.settings = settings

    def build(self, fps):
        pos = 0
        if self.pipe:
            ok, pos = self.pipe.query_position(Gst.Format.TIME)
            pos = pos if ok else 0
            self.pipe.set_state(Gst.State.NULL)
        self.pipe = Gst.parse_launch(
            f'filesrc location="{os.path.join(HERE, "scene.png")}" ! pngdec ! glupload ! imagefreeze ! '
            f'video/x-raw(memory:GLMemory),framerate={int(fps)}/1 ! glshader name=shader ! '
            'video/x-raw(memory:GLMemory),width=1920,height=1200 ! '
            'glimagesink name=sink force-aspect-ratio=false handle-events=false')
        self.shader = self.pipe.get_by_name('shader')
        self.shader.set_property('fragment', self.frag)
        self.apply(self.settings)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error', self.on_error)
        self.pipe.get_by_name('sink').set_window_handle(self.area.get_window().get_xid())
        self.pipe.set_state(Gst.State.PAUSED)
        self.pipe.get_state(3 * Gst.SECOND)
        if pos:  # продолжаем анимацию с того же места, без рывка
            self.pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, pos)
        self.fps = fps
        self.paused = True

    def set_mode(self, fps, paused):
        """Частота кадров и пауза. На паузе видеокарта и процессор не работают."""
        if fps != self.fps:
            self.build(fps)
        if paused != self.paused:
            self.pipe.set_state(Gst.State.PAUSED if paused else Gst.State.PLAYING)
            self.paused = paused

    def apply(self, settings):
        u = ','.join(f'{k}=(float){float(settings[k]):.4f}' for k in DEFAULTS if k.startswith('u_'))
        self.shader.set_property('uniforms', Gst.Structure.new_from_string('uniforms,' + u))

    def rewind(self):
        # перемотка на (позиция mod LOOP): для шейдера время не меняется — без рывка
        ok, pos = self.pipe.query_position(Gst.Format.TIME)
        if ok and pos > LOOP * Gst.SECOND:
            self.pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, pos % (LOOP * Gst.SECOND))
        return True

    def on_error(self, bus, msg):
        err, dbg = msg.parse_error()
        print('ошибка GStreamer:', err.message, dbg, file=sys.stderr)

    def stop(self):
        self.pipe.set_state(Gst.State.NULL)


class Panel(Gtk.Window):
    """Мини-окно с ползунками. Открывается из меню значка в трее."""

    def __init__(self, app):
        super().__init__(title='Salad Live')
        self.app = app
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_border_width(18)
        self.get_style_context().add_class('salad-panel')
        self.connect('delete-event', lambda *a: self.hide() or True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(box)
        head = Gtk.Label(label='Salad Live', xalign=0)
        head.get_style_context().add_class('head')
        box.pack_start(head, False, False, 0)

        self.scales = {}
        grid = None
        for spec in SLIDERS:
            if spec[1] is None:
                g = Gtk.Label(label=spec[0].upper(), xalign=0)
                g.get_style_context().add_class('group')
                box.pack_start(g, False, False, 0)
                grid = Gtk.Grid(column_spacing=12, row_spacing=2)
                box.pack_start(grid, False, False, 0)
                row = 0
                continue
            key, label, lo, hi, step, _ = spec
            lab = Gtk.Label(label=label, xalign=0)
            lab.set_size_request(120, -1)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            sc.set_draw_value(False)
            sc.set_size_request(200, -1)
            sc.set_value(app.settings[key])
            val = Gtk.Label(xalign=1)
            val.get_style_context().add_class('val')
            fmt = (lambda v: f'{int(round(v))}') if step >= 1 else (lambda v: f'{v:.2f}')
            val.set_text(fmt(app.settings[key]))
            sc.connect('value-changed', self.on_change, key, val, fmt)
            grid.attach(lab, 0, row, 1, 1)
            grid.attach(sc, 1, row, 1, 1)
            grid.attach(val, 2, row, 1, 1)
            self.scales[key] = sc
            row += 1

        g = Gtk.Label(label='КАДРОВ В СЕКУНДУ', xalign=0)
        g.get_style_context().add_class('group')
        box.pack_start(g, False, False, 0)
        fbox = Gtk.Box(spacing=12)
        group = None
        self.fps_buttons = {}
        for f in FPS_CHOICES:
            rb = Gtk.RadioButton.new_with_label_from_widget(group, str(f))
            group = group or rb
            rb.set_active(int(app.settings['fps']) == f)
            rb.connect('toggled', self.on_fps, f)
            fbox.pack_start(rb, False, False, 0)
            self.fps_buttons[f] = rb
        box.pack_start(fbox, False, False, 0)

        btns = Gtk.Box(spacing=8, margin_top=14)
        reset = Gtk.Button(label='Сбросить')
        reset.connect('clicked', self.on_reset)
        done = Gtk.Button(label='Готово')
        done.get_style_context().add_class('accent')
        done.connect('clicked', lambda *a: self.hide())
        btns.pack_start(reset, False, False, 0)
        btns.pack_end(done, False, False, 0)
        box.pack_start(btns, False, False, 0)

    def on_change(self, sc, key, val, fmt):
        v = sc.get_value()
        val.set_text(fmt(v))
        self.app.update(key, v)

    def on_fps(self, rb, f):
        if rb.get_active():
            self.app.update('fps', f)

    def on_reset(self, *_):
        for k, sc in self.scales.items():
            sc.set_value(DEFAULTS[k])
        self.fps_buttons[DEFAULTS['fps']].set_active(True)

    def present_near_tray(self):
        self.show_all()
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        geo = mon.get_workarea()
        w, _ = self.get_size()
        self.move(geo.x + geo.width - w - 16, geo.y + 12)
        self.present()


class App:
    def __init__(self):
        self.settings = load_settings()
        self._save_id = 0
        # внешние условия для экономии
        self.desktop_visible = True   # от расширения GNOME Shell; без него — всегда «виден»
        self.locked = False           # экран заблокирован или погашен
        self.on_battery = False
        disp = Gdk.Display.get_default()
        self.walls = [Wallpaper(disp.get_monitor(i), self.settings) for i in range(disp.get_n_monitors())]
        GLib.timeout_add_seconds(LOOP // 2, self.rewind)
        self.watch_session()
        self.refresh()

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.panel = Panel(self)

        self.ind = AppIndicator.Indicator.new('salad-live', 'salad-live',
                                              AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.ind.set_icon_theme_path(os.path.join(HERE, 'icons'))
        self.ind.set_icon_full('salad-live', 'Salad Live')
        self.ind.set_title('Salad Live — живые обои')
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        it = Gtk.MenuItem(label='Настройки…')
        it.connect('activate', lambda *a: self.panel.present_near_tray())
        menu.append(it)
        self.pause_item = Gtk.CheckMenuItem(label='Пауза')
        self.pause_item.set_active(self.settings['paused'])
        self.pause_item.connect('toggled', lambda i: self.update('paused', i.get_active()))
        menu.append(self.pause_item)
        menu.append(Gtk.SeparatorMenuItem())
        q = Gtk.MenuItem(label='Выключить живые обои')
        q.connect('activate', lambda *a: Gtk.main_quit())
        menu.append(q)
        menu.show_all()
        self.ind.set_menu(menu)
        self.ind.set_secondary_activate_target(it)  # средний клик по значку — настройки

        unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.on_usr1)

    def rewind(self):
        for w in self.walls:
            w.rewind()
        return True

    # ---- экономия: блокировка экрана, батарея, видимость рабочего стола

    def watch_session(self):
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        # D-Bus-сервис для расширения GNOME Shell (и для --settings)
        node = Gio.DBusNodeInfo.new_for_xml(BUS_XML)
        self.session.register_object(BUS_PATH, node.interfaces[0], self.on_dbus_call)
        Gio.bus_own_name_on_connection(self.session, BUS_NAME, Gio.BusNameOwnerFlags.REPLACE, None, None)
        # блокировка/гашение экрана
        self.session.signal_subscribe(None, 'org.gnome.ScreenSaver', 'ActiveChanged', '/org/gnome/ScreenSaver',
                                      None, Gio.DBusSignalFlags.NONE,
                                      lambda *a: self.set_state(locked=a[5].unpack()[0]))
        try:
            r = self.session.call_sync('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver',
                                       'GetActive', None, GLib.VariantType('(b)'), Gio.DBusCallFlags.NONE, 1000)
            self.locked = r.unpack()[0]
        except GLib.Error:
            pass
        # питание от батареи
        try:
            self.upower = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
                'org.freedesktop.UPower', '/org/freedesktop/UPower', 'org.freedesktop.UPower')
            self.upower.connect('g-properties-changed', lambda *a: self.read_battery())
            self.read_battery(refresh=False)
        except GLib.Error:
            self.upower = None

    def read_battery(self, refresh=True):
        v = self.upower.get_cached_property('OnBattery')
        self.on_battery = bool(v.unpack()) if v is not None else False
        if refresh:
            self.refresh()

    def on_dbus_call(self, conn, sender, path, iface, method, params, invocation):
        if method == 'SetDesktopVisible':
            self.set_state(desktop_visible=params.unpack()[0])
        elif method == 'ShowSettings':
            self.panel.present_near_tray()
        invocation.return_value(None)

    def set_state(self, **kw):
        for k, v in kw.items():
            setattr(self, k, bool(v))
        self.refresh()

    def refresh(self):
        s = self.settings
        paused = bool(s['paused']) or self.locked or not self.desktop_visible
        fps = int(s['battery_fps']) if (self.on_battery and s['battery_saver']) else int(s['fps'])
        log(f'paused={paused} (user={s["paused"]} locked={self.locked} visible={self.desktop_visible}) '
            f'fps={fps} battery={self.on_battery}')
        for w in self.walls:
            w.set_mode(fps, paused)

    def on_usr1(self):
        self.panel.present_near_tray()
        return True

    def update(self, key, value):
        self.settings[key] = value
        if key in ('fps', 'paused'):
            self.refresh()
        else:
            for w in self.walls:
                w.apply(self.settings)
        # сохраняем не на каждый шаг ползунка, а через полсекунды тишины
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(500, self._save)

    def _save(self):
        self._save_id = 0
        save_settings(self.settings)
        return False

    def quit(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save()
        for w in self.walls:
            w.stop()


def main():
    if '--version' in sys.argv:
        print('salad-live', __version__)
        return
    pid = read_pid()
    alive = False
    if pid and pid != os.getpid():
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            pass
    if '--stop' in sys.argv:
        if alive:
            os.kill(pid, signal.SIGTERM)
            print('остановлено')
        else:
            print('не запущено')
        return
    if '--settings' in sys.argv and alive:
        os.kill(pid, signal.SIGUSR1)
        return
    if alive:
        os.kill(pid, signal.SIGTERM)

    with open(PIDFILE, 'w') as f:
        f.write(str(os.getpid()))
    Gst.init(None)
    Gtk.init(None)
    app = App()
    if '--settings' in sys.argv:
        app.panel.present_near_tray()
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    Gtk.main()
    app.quit()
    if read_pid() == os.getpid():
        os.remove(PIDFILE)


if __name__ == '__main__':
    main()
