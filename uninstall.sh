#!/usr/bin/env bash
# Удаление живых обоев Salad Live.
#   sudo ./uninstall.sh        если ставили в систему
#   ./uninstall.sh --user      если ставили с --user
#   --purge                    удалить и настройки (~/.config/salad-live)
set -euo pipefail
APP=salad-live
UUID=salad-live@vyugov76.github.io
MODE=system PURGE=0
for a in "$@"; do
    case "$a" in
        --user) MODE=user ;;
        --purge) PURGE=1 ;;
        *) echo "Неизвестный ключ: $a"; exit 2 ;;
    esac
done
if [ "$MODE" = system ]; then
    [ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
    PREFIX=/usr/local AUTOSTART_DIR=/etc/xdg/autostart EXT_DIR=/usr/local/share/gnome-shell/extensions
    TARGET_USER="${SUDO_USER:-}"
else
    PREFIX="$HOME/.local" AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    EXT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions"
    TARGET_USER="$(id -un)"
fi

run_as_user() {
    [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != root ] || return 0
    local uid; uid="$(id -u "$TARGET_USER")"
    if [ "$(id -un)" = "$TARGET_USER" ]; then "$@"; else
        sudo -u "$TARGET_USER" env XDG_RUNTIME_DIR="/run/user/$uid" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$@"; fi
}

# остановить запущенные обои
run_as_user sh -c "kill \$(cat /run/user/\$(id -u)/salad-live.pid 2>/dev/null) 2>/dev/null" || true
# выключить расширение
cur="$(run_as_user gsettings get org.gnome.shell enabled-extensions 2>/dev/null || true)"
if grep -q "$UUID" <<<"$cur"; then
    new="$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ','')); print([x for x in l if x!=sys.argv[2]])" "$cur" "$UUID")"
    run_as_user gsettings set org.gnome.shell enabled-extensions "$new" || true
fi

rm -rf "$PREFIX/share/$APP" "$EXT_DIR/$UUID"
rm -f "$PREFIX/bin/$APP" "$PREFIX/share/applications/salad-live.desktop" \
      "$PREFIX/share/icons/hicolor/scalable/apps/salad-live.svg" "$AUTOSTART_DIR/salad-live.desktop"
if [ "$PURGE" = 1 ] && [ -n "$TARGET_USER" ]; then
    rm -rf "$(getent passwd "$TARGET_USER" | cut -d: -f6)/.config/salad-live"
fi
echo "Salad Live удалён. Статичные обои можно сменить в «Параметры → Внешний вид»."
