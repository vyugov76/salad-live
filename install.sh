#!/usr/bin/env bash
# Установщик живых обоев Salad Live.
#
#   sudo ./install.sh          в систему (/usr/local), автозапуск для всех пользователей
#   ./install.sh --user        только для себя (~/.local), без sudo
#
# Ключи:
#   --yes            не задавать вопросов (зависимости ставить, статичный кадр в обои ставить)
#   --no-deps        не проверять и не ставить пакеты
#   --no-start       не запускать обои после установки
#   --no-wallpaper   не ставить статичный кадр в обои / экран блокировки
#
# Переменная DESTDIR=/путь — «сухая» установка в каталог (для сборки пакетов и проверки).
set -euo pipefail

APP=salad-live
UUID=salad-live@vyugov76.github.io
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTDIR="${DESTDIR:-}"

MODE=system YES=0 DEPS=1 START=1 WALL=ask
for a in "$@"; do
    case "$a" in
        --user) MODE=user ;;
        --yes|-y) YES=1 ;;
        --no-deps) DEPS=0 ;;
        --no-start) START=0 ;;
        --no-wallpaper) WALL=no ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный ключ: $a (см. --help)"; exit 2 ;;
    esac
done
[ "$YES" = 1 ] && [ "$WALL" = ask ] && WALL=yes

G=$'\e[38;2;166;216;107m' D=$'\e[38;2;133;141;128m' R=$'\e[31m' N=$'\e[0m'
say()  { printf '%s▸%s %s\n' "$G" "$N" "$*"; }
note() { printf '  %s%s%s\n' "$D" "$*" "$N"; }
die()  { printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
ask()  { [ "$YES" = 1 ] && return 0; read -r -p "  $1 [Д/н] " r </dev/tty || true; [[ ! "$r" =~ ^[НнNn] ]]; }

# ---------------------------------------------------------------- кто и куда
if [ "$MODE" = system ]; then
    if [ -z "$DESTDIR" ] && [ "$(id -u)" != 0 ]; then
        say "Для установки в систему нужны права администратора."
        # передаём окружение графического сеанса, чтобы потом запустить обои у пользователя
        exec sudo --preserve-env=DISPLAY,WAYLAND_DISPLAY,XAUTHORITY,XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS \
            "$0" "$@"
    fi
    PREFIX=/usr/local
    AUTOSTART_DIR=/etc/xdg/autostart
    EXT_DIR=/usr/local/share/gnome-shell/extensions
    TARGET_USER="${SUDO_USER:-}"
    [ "$TARGET_USER" = root ] && TARGET_USER=""
else
    [ "$(id -u)" = 0 ] && die "--user запускают без sudo"
    PREFIX="$HOME/.local"
    AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    EXT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions"
    TARGET_USER="$(id -un)"
fi
SHARE="$PREFIX/share/$APP"
BIN="$PREFIX/bin/$APP"

# команды от имени пользователя, в его графическом сеансе
as_user() {
    [ -n "$TARGET_USER" ] || return 1
    local uid; uid="$(id -u "$TARGET_USER")"
    local env=(XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus")
    [ -n "${DISPLAY:-}" ] && env+=(DISPLAY="$DISPLAY")
    [ -n "${WAYLAND_DISPLAY:-}" ] && env+=(WAYLAND_DISPLAY="$WAYLAND_DISPLAY")
    [ -n "${XAUTHORITY:-}" ] && env+=(XAUTHORITY="$XAUTHORITY")
    if [ "$(id -un)" = "$TARGET_USER" ]; then
        env "${env[@]}" "$@"
    else
        sudo -u "$TARGET_USER" env "${env[@]}" "$@"
    fi
}

echo
printf '%s  Salad Live%s — живые обои: лес, водопад и домик под дождём\n' "$G" "$N"
note "режим: $([ "$MODE" = system ] && echo 'в систему' || echo 'для пользователя') → $SHARE"
echo

# ---------------------------------------------------------------- зависимости
PKGS=(python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-gl gir1.2-ayatanaappindicator3-0.1)
if [ "$DEPS" = 1 ] && [ -z "$DESTDIR" ]; then
    say "Проверяю зависимости"
    command -v dpkg-query >/dev/null || die "Нужен Debian/Ubuntu (dpkg). Поставь вручную: ${PKGS[*]}"
    missing=()
    for p in "${PKGS[@]}"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || missing+=("$p")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        note "не хватает: ${missing[*]}"
        if [ "$(id -u)" = 0 ]; then
            ask "Установить через apt?" || die "Без них обои не запустятся"
            apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
        else
            ask "Установить через sudo apt?" || die "Без них обои не запустятся"
            sudo apt-get update -qq && sudo apt-get install -y -qq "${missing[@]}"
        fi
    else
        note "всё на месте"
    fi
fi

# ---------------------------------------------------------------- файлы
say "Копирую файлы"
inst() { install -D -m "$1" "$2" "$DESTDIR$3"; }
inst 755 "$HERE/src/salad-live.py" "$SHARE/salad-live.py"
for f in scene.frag consts.glsl scene.png still.png paint.py; do
    inst 644 "$HERE/src/$f" "$SHARE/$f"
done
inst 644 "$HERE/src/icons/salad-live.svg" "$SHARE/icons/salad-live.svg"
inst 644 "$HERE/src/icons/salad-live.svg" "$PREFIX/share/icons/hicolor/scalable/apps/salad-live.svg"

mkdir -p "$DESTDIR$PREFIX/bin"
cat > "$DESTDIR$BIN" <<EOF
#!/bin/sh
exec python3 "$SHARE/salad-live.py" "\$@"
EOF
chmod 755 "$DESTDIR$BIN"
note "$BIN"

# ярлык в меню приложений: открывает настройки (и запускает обои, если выключены)
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
sed "s|@BIN@|$BIN|g" "$HERE/data/salad-live.desktop" > "$tmp"
inst 644 "$tmp" "$PREFIX/share/applications/salad-live.desktop"
# автозапуск при входе в систему
sed "s|@BIN@|$BIN|g" "$HERE/data/salad-live-autostart.desktop" > "$tmp"
inst 644 "$tmp" "$AUTOSTART_DIR/salad-live.desktop"
note "автозапуск: $AUTOSTART_DIR/salad-live.desktop"

# расширение GNOME Shell для экономии (пауза, когда рабочий стол не виден)
for f in metadata.json extension.js; do
    inst 644 "$HERE/extension/$f" "$EXT_DIR/$UUID/$f"
done
note "расширение: $EXT_DIR/$UUID"

[ -n "$DESTDIR" ] && { say "Готово (DESTDIR=$DESTDIR, без запуска)"; exit 0; }

if [ "$MODE" = system ]; then
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/local/share/icons/hicolor 2>/dev/null || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/local/share/applications 2>/dev/null || true
fi

# ---------------------------------------------------------------- настройка пользователя
if [ -n "$TARGET_USER" ]; then
    uhome="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    # старая ручная установка дублировала бы автозапуск
    old="$uhome/.config/autostart/salad-live.desktop"
    if [ "$MODE" = system ] && [ -f "$old" ]; then
        rm -f "$old"
        note "убрал дублирующий пользовательский автозапуск ($old)"
    fi

    say "Включаю расширение экономии"
    if as_user gsettings get org.gnome.shell enabled-extensions >/dev/null 2>&1; then
        cur="$(as_user gsettings get org.gnome.shell enabled-extensions)"
        if ! grep -q "$UUID" <<<"$cur"; then
            new="$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ','')); l.append(sys.argv[2]); print(l)" "$cur" "$UUID")"
            as_user gsettings set org.gnome.shell enabled-extensions "$new"
        fi
        note "заработает после следующего входа в систему (GNOME подхватывает новые расширения при входе)"
    else
        note "не GNOME или нет сеанса — пропускаю"
    fi

    if [ "$WALL" = ask ]; then
        echo
        ask "Поставить кадр этой сцены как статичные обои (их видно в обзоре и на экране блокировки)?" && WALL=yes || WALL=no
    fi
    if [ "$WALL" = yes ]; then
        uri="file://$SHARE/still.png"
        as_user gsettings set org.gnome.desktop.background picture-uri "$uri" 2>/dev/null &&
        as_user gsettings set org.gnome.desktop.background picture-uri-dark "$uri" 2>/dev/null &&
        as_user gsettings set org.gnome.desktop.screensaver picture-uri "$uri" 2>/dev/null &&
        note "обои и экран блокировки обновлены" || note "не получилось — можно поставить вручную: $SHARE/still.png"
    fi

    if [ "$START" = 1 ]; then
        say "Запускаю"
        if as_user sh -c "setsid '$BIN' >/dev/null 2>&1 </dev/null &"; then
            note "в верхней панели появится значок-ёлочка"
        else
            note "запусти сам: $APP   (или просто перезайди в систему)"
        fi
    fi
fi

echo
say "Установлено ✓"
note "$APP --settings   настройки       $APP --stop   выключить"
note "удаление: $( [ "$MODE" = system ] && echo 'sudo ' )$(basename "$HERE")/uninstall.sh$( [ "$MODE" = user ] && echo ' --user')"
echo
