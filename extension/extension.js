// Salad Live helper — расширение GNOME Shell для экономии ресурсов живыми обоями.
//
// Обычное приложение на Wayland не знает, закрыт ли рабочий стол чужими окнами:
// это знает только оболочка. Расширение следит за окнами текущего рабочего
// пространства и по D-Bus сообщает обоям (io.github.vyugov76.SaladLive),
// виден ли рабочий стол. Обои на паузе не рисуют ни одного кадра.
//
// Рабочий стол считается закрытым, если открыт обзор или на каждом мониторе
// обычные окна закрывают не меньше COVER_LIMIT рабочей области.
//
// Ещё расширение переносит картинку обоев в слой фона GNOME (под всеми окнами,
// включая значки рабочего стола DING): само окно обоев делается прозрачным,
// а в фон кладётся его живая копия (Clutter.Clone). Так значки и файлы на рабочем
// столе всегда видны поверх обоев, как бы ни менялся порядок окон.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.vyugov76.SaladLive';
const BUS_PATH = '/io/github/vyugov76/SaladLive';
const COVER_LIMIT = 0.92;
const GRID = 24; // сетка для оценки закрытой площади (GRID x GRID ячеек на монитор)

export default class SaladLiveHelper extends Extension {
    enable() {
        this._signals = [];
        this._windows = new Map();
        this._visible = null;
        this._timeoutId = 0;
        this._clones = new Map(); // MetaWindowActor обоев → {clone, opacityId}

        const q = () => this._queue();
        this._connect(global.display, 'restacked', q);
        this._connect(global.display, 'window-created', (_d, w) => {
            this._track(w);
            q();
        });
        // актор окна появляется к моменту map — тогда и переносим обои в фон
        this._connect(global.window_manager, 'map', (_wm, actor) => this._adopt(actor));
        this._connect(global.workspace_manager, 'active-workspace-changed', q);
        this._connect(Main.overview, 'showing', q);
        this._connect(Main.overview, 'hidden', q);
        this._connect(Main.layoutManager, 'monitors-changed', q);
        for (const actor of global.get_window_actors()) {
            this._track(actor.meta_window);
            this._adopt(actor);
        }

        // обои (пере)запустились — отправляем им текущее состояние заново
        this._watchId = Gio.bus_watch_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => {
                this._visible = null;
                q();
            }, null);
        q();
    }

    disable() {
        if (this._timeoutId)
            GLib.source_remove(this._timeoutId);
        this._timeoutId = 0;
        Gio.bus_unwatch_name(this._watchId);
        for (const [obj, id] of this._signals)
            obj.disconnect(id);
        this._signals = [];
        for (const w of [...this._windows.keys()])
            this._untrack(w);
        for (const actor of [...this._clones.keys()])
            this._release(actor);
        // без расширения обои должны просто работать
        this._send(true);
        this._visible = null;
    }

    _isWallpaper(win) {
        return !!win && win.get_window_type() === Meta.WindowType.DESKTOP &&
            (win.get_wm_class_instance() === 'salad-live' || win.get_title() === 'salad-live');
    }

    // окно обоев → прозрачное, а его живая копия — в слой фона, под всеми окнами
    _adopt(actor) {
        if (!actor || this._clones.has(actor) || !this._isWallpaper(actor.meta_window))
            return;
        const clone = new Clutter.Clone({source: actor, reactive: false});
        clone.add_constraint(new Clutter.BindConstraint({source: actor, coordinate: Clutter.BindCoordinate.ALL}));
        const bg = Main.layoutManager._backgroundGroup;
        bg.add_child(clone);
        bg.set_child_above_sibling(clone, null); // над картинкой фона, но всё ещё под окнами
        actor.opacity = 0;
        // Clone рисует источник со своей прозрачностью, так что копия видна
        const opacityId = actor.connect('notify::opacity', () => {
            if (actor.opacity !== 0)
                actor.opacity = 0;
        });
        const destroyId = actor.connect('destroy', () => this._release(actor, true));
        this._clones.set(actor, {clone, opacityId, destroyId});
        console.log(`[salad-live] обои перенесены в слой фона (${actor.width}x${actor.height})`);
    }

    _release(actor, destroyed = false) {
        const c = this._clones.get(actor);
        if (!c)
            return;
        this._clones.delete(actor);
        if (!destroyed) {
            actor.disconnect(c.opacityId);
            actor.disconnect(c.destroyId);
            actor.opacity = 255;
        }
        c.clone.destroy();
    }

    _connect(obj, signal, cb) {
        this._signals.push([obj, obj.connect(signal, cb)]);
    }

    _track(win) {
        if (!win || this._windows.has(win))
            return;
        const q = () => this._queue();
        const ids = [
            win.connect('position-changed', q),
            win.connect('size-changed', q),
            win.connect('notify::minimized', q),
            win.connect('workspace-changed', q),
            win.connect('unmanaged', () => {
                this._untrack(win);
                q();
            }),
        ];
        this._windows.set(win, ids);
    }

    _untrack(win) {
        const ids = this._windows.get(win);
        if (!ids)
            return;
        for (const id of ids) {
            try {
                win.disconnect(id);
            } catch {
                // окно уже уничтожено
            }
        }
        this._windows.delete(win);
    }

    // события окон сыплются пачками (перетаскивание) — считаем не чаще 4 раз в секунду
    _queue() {
        if (this._timeoutId)
            return;
        this._timeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            this._timeoutId = 0;
            this._update();
            return GLib.SOURCE_REMOVE;
        });
    }

    _update() {
        const visible = this._desktopVisible();
        if (visible !== this._visible) {
            this._visible = visible;
            this._send(visible);
        }
    }

    _send(visible) {
        Gio.DBus.session.call(BUS_NAME, BUS_PATH, BUS_NAME, 'SetDesktopVisible',
            new GLib.Variant('(b)', [visible]), null, Gio.DBusCallFlags.NO_AUTO_START, 1000, null,
            (conn, res) => {
                try {
                    conn.call_finish(res);
                } catch {
                    // обои не запущены — ничего страшного
                }
            });
    }

    _desktopVisible() {
        if (Main.overview.visible)
            return false;
        const ws = global.workspace_manager.get_active_workspace();
        const wins = ws.list_windows().filter(w =>
            !w.minimized &&
            w.showing_on_its_workspace() &&
            !w.skip_taskbar &&
            !this._isWallpaper(w) &&
            w.get_window_type() === Meta.WindowType.NORMAL);
        const n = global.display.get_n_monitors();
        for (let m = 0; m < n; m++) {
            if (this._coverage(Main.layoutManager.getWorkAreaForMonitor(m), wins) < COVER_LIMIT)
                return true;
        }
        return false;
    }

    // доля рабочей области монитора, закрытая окнами (по сетке, с учётом перекрытий)
    _coverage(area, wins) {
        const rects = wins.map(w => w.get_frame_rect()).filter(r =>
            r.x < area.x + area.width && r.x + r.width > area.x &&
            r.y < area.y + area.height && r.y + r.height > area.y);
        if (rects.length === 0)
            return 0;
        let covered = 0;
        for (let i = 0; i < GRID; i++) {
            const px = area.x + (i + 0.5) * area.width / GRID;
            for (let j = 0; j < GRID; j++) {
                const py = area.y + (j + 0.5) * area.height / GRID;
                if (rects.some(r => px >= r.x && px < r.x + r.width && py >= r.y && py < r.y + r.height))
                    covered++;
            }
        }
        return covered / (GRID * GRID);
    }
}
