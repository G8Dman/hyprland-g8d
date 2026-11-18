-- g8d / graphite. Independent Hyprland 0.56 session.
local root = (os.getenv("G8D_CONFIG_DIR") or (os.getenv("HOME") .. "/.config/hyprland-g8d")) .. "/"
dofile(root .. "shortcuts-runtime.lua")
local function cmd(action) return hl.dsp.exec_cmd(root .. "actions " .. action) end

-- Portable defaults; saved monitor settings are loaded below.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
do
    local monitors_file = io.open(root .. "monitors.lua", "r")
    if monitors_file then monitors_file:close(); dofile(root .. "monitors.lua") end
end
-- Qt applications must read the complete KDE palette, including alternate rows.
-- Qt integration is selected by the portable session launcher.
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.config({
    general = {
        gaps_in = 4, gaps_out = 12, border_size = 1,
        col = { active_border = "rgba(8bbfbaff)", inactive_border = "rgba(30373fff)" },
        layout = "dwindle", resize_on_border = true, allow_tearing = false,
    },
    decoration = {
        rounding = 8, active_opacity = 1, inactive_opacity = 1,
        shadow = { enabled = true, range = 12, render_power = 3, color = "rgba(00000035)" },
        blur = { enabled = false },
    },
    animations = { enabled = true },
    input = {
        kb_layout = "us,ru", kb_options = "",
        follow_mouse = 1, sensitivity = 0,
        touchpad = { natural_scroll = false },
    },
    dwindle = { preserve_split = true },
    misc = { disable_hyprland_logo = true, force_default_wallpaper = 0 },
})
hl.curve("g8d", { type = "bezier", points = { {0.2, 0.8}, {0.2, 1} } })
for _, leaf in ipairs({"windows", "fade", "workspaces", "layers", "border"}) do
    hl.animation({ leaf = leaf, enabled = true, speed = 3, bezier = "g8d" })
end
hl.window_rule({name = "g8d-settings", match = {class = "^g8d-settings$"}, float = true, center = true, size = {"1060", "760"}})
g8d_bind("settings", "Настройки", "SUPER + CTRL + S", cmd("settings"))
g8d_bind("terminal", "Терминал", "SUPER + T", cmd("terminal"))
g8d_bind("terminal-return", "Терминал · Enter", "SUPER + Return", cmd("terminal"))
dofile(root .. "window-switcher.lua")
g8d_bind("files", "Файловый менеджер", "SUPER + E", cmd("files"))
g8d_bind("browser", "Браузер", "SUPER + B", cmd("browser"))
g8d_bind("launcher", "Поиск приложений", "SUPER + R", cmd("launcher"))
g8d_bind("appearance", "Обои и оформление", "SUPER + W", function() hl.exec_cmd(root .. "actions appearance") end)
g8d_bind("launcher-d", "Поиск приложений · D", "SUPER + D", cmd("launcher"))
g8d_bind("close-window", "Закрыть окно", "SUPER + Q", hl.dsp.window.close())
g8d_bind("xkill", "Завершить выбранное приложение", "CTRL + ALT + Escape", hl.dsp.exec_cmd("hyprctl kill"))
g8d_bind("floating", "Плавающее окно", "SUPER + V", hl.dsp.window.float({action = "toggle"}))
g8d_bind("fullscreen", "Полный экран", "SUPER + F", hl.dsp.window.fullscreen())
g8d_bind("split", "Направление разделения окон", "SUPER + J", hl.dsp.layout("togglesplit"))
g8d_bind("lock", "Блокировка", "SUPER + L", cmd("lock"))
g8d_bind("power", "Меню питания", "SUPER + Escape", cmd("power"))
g8d_bind("power-m", "Меню питания · M", "SUPER + SHIFT + M", cmd("power"))
g8d_bind("help", "Памятка сочетаний", "SUPER + F1", cmd("help"))
g8d_bind("screenshot", "Снимок экрана", "Print", cmd("screenshot"))
g8d_bind("screenshot-s", "Снимок экрана · S", "SUPER + SHIFT + S", cmd("screenshot"))
g8d_bind("scratch", "Скрытый рабочий стол", "SUPER + S", hl.dsp.workspace.toggle_special("scratch"))
g8d_bind("move-scratch", "Перенести окно на скрытый стол", "SUPER + SHIFT + V", hl.dsp.window.move({workspace = "special:scratch"}))
for _, direction in ipairs({"left", "right", "up", "down"}) do
    g8d_bind("focus-" .. direction, "Фокус окна · " .. direction, "SUPER + " .. direction, hl.dsp.focus({direction = direction}))
    g8d_bind("move-" .. direction, "Переместить окно · " .. direction, "SUPER + SHIFT + " .. direction, hl.dsp.window.move({direction = direction}))
end
for i = 1, 10 do
    g8d_bind("workspace-" .. i, "Рабочий стол " .. i, "SUPER + " .. i % 10, hl.dsp.focus({workspace = i}))
    g8d_bind("move-workspace-" .. i, "Перенести окно на стол " .. i, "SUPER + SHIFT + " .. i % 10, hl.dsp.window.move({workspace = i}))
end
-- Step through workspace numbers, creating empty workspaces on demand.
local function step_workspace(direction)
    local current = hl.get_active_workspace()
    local target = math.max(1, (current and math.max(1, current.id) or 1) + direction)
    hl.dispatch(hl.dsp.focus({workspace = target}))
end
g8d_bind("workspace-next", "Следующий рабочий стол", "SUPER + mouse_down", function() step_workspace(1) end)
g8d_bind("workspace-prev", "Предыдущий рабочий стол", "SUPER + mouse_up", function() step_workspace(-1) end)
g8d_bind("drag-window", "Перетаскивание окна мышью", "SUPER + mouse:272", hl.dsp.window.drag(), {mouse = true})
g8d_bind("resize-window", "Размер окна мышью", "SUPER + mouse:273", hl.dsp.window.resize(), {mouse = true})
g8d_bind("volume-up", "Увеличить громкость", "XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), {locked = true, repeating = true})
g8d_bind("volume-down", "Уменьшить громкость", "XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), {locked = true, repeating = true})
g8d_bind("volume-mute", "Выключить звук", "XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), {locked = true})
g8d_bind("mic-mute", "Выключить микрофон", "XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), {locked = true})
g8d_bind("brightness-up", "Увеличить яркость", "XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl set 5%+"), {locked = true, repeating = true})
g8d_bind("brightness-down", "Уменьшить яркость", "XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 5%-"), {locked = true, repeating = true})
g8d_bind("media-play", "Воспроизведение / пауза", "XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), {locked = true})
g8d_bind("media-next", "Следующий трек", "XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), {locked = true})
g8d_bind("media-prev", "Предыдущий трек", "XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), {locked = true})
hl.window_rule({name = "g8d-no-maximize", match = {class = ".*"}, suppress_event = "maximize"})
dofile(root .. "file-dialogs.lua")
dofile(root .. "accent.lua")
hl.on("hyprland.start", function() hl.exec_cmd(root .. "autostart") end)
g8d_bind("layout", "Переключить раскладку", "SUPER + space", hl.dsp.exec_cmd("hyprctl switchxkblayout all next"))
