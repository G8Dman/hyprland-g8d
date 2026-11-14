-- g8d / graphite. Independent Hyprland 0.56 session.
local root = (os.getenv("G8D_CONFIG_DIR") or (os.getenv("HOME") .. "/.config/hyprland-g8d")) .. "/"
local function cmd(action) return hl.dsp.exec_cmd(root .. "actions " .. action) end

-- Portable default; user display settings are loaded separately.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
do
    local monitors_file = io.open(root .. "monitors.lua", "r")
    if monitors_file then monitors_file:close(); dofile(root .. "monitors.lua") end
end
-- Qt applications must read the complete KDE palette, including alternate rows.
-- Qt integration is selected by the session launcher.
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
        kb_layout = "us,ru", kb_options = "grp:win_space_toggle",
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
hl.bind("SUPER + CTRL + S", cmd("settings"))
hl.bind("SUPER + T", cmd("terminal"))
hl.bind("SUPER + Return", cmd("terminal"))
dofile(root .. "window-switcher.lua")
hl.bind("SUPER + E", cmd("files"))
hl.bind("SUPER + B", cmd("browser"))
hl.bind("SUPER + R", cmd("launcher"))
hl.bind("SUPER + W", function() hl.exec_cmd(root .. "actions appearance") end)
hl.bind("SUPER + D", cmd("launcher"))
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("CTRL + ALT + Escape", hl.dsp.exec_cmd("hyprctl kill"))
hl.bind("SUPER + V", hl.dsp.window.float({action = "toggle"}))
hl.bind("SUPER + F", hl.dsp.window.fullscreen())
hl.bind("SUPER + J", hl.dsp.layout("togglesplit"))
hl.bind("SUPER + L", cmd("lock"))
hl.bind("SUPER + Escape", cmd("power"))
hl.bind("SUPER + SHIFT + M", cmd("power"))
hl.bind("SUPER + F1", cmd("help"))
hl.bind("Print", cmd("screenshot"))
hl.bind("SUPER + SHIFT + S", cmd("screenshot"))
hl.bind("SUPER + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind("SUPER + SHIFT + V", hl.dsp.window.move({workspace = "special:scratch"}))
for _, direction in ipairs({"left", "right", "up", "down"}) do
    hl.bind("SUPER + " .. direction, hl.dsp.focus({direction = direction}))
    hl.bind("SUPER + SHIFT + " .. direction, hl.dsp.window.move({direction = direction}))
end
for i = 1, 10 do
    hl.bind("SUPER + " .. i % 10, hl.dsp.focus({workspace = i}))
    hl.bind("SUPER + SHIFT + " .. i % 10, hl.dsp.window.move({workspace = i}))
end
-- Step through workspace numbers, creating empty workspaces on demand.
local function step_workspace(direction)
    local current = hl.get_active_workspace()
    local target = math.max(1, (current and math.max(1, current.id) or 1) + direction)
    hl.dispatch(hl.dsp.focus({workspace = target}))
end
hl.bind("SUPER + mouse_down", function() step_workspace(1) end)
hl.bind("SUPER + mouse_up", function() step_workspace(-1) end)
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), {mouse = true})
hl.bind("SUPER + mouse:273", hl.dsp.window.resize(), {mouse = true})
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), {locked = true, repeating = true})
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), {locked = true, repeating = true})
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), {locked = true})
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), {locked = true})
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl set 5%+"), {locked = true, repeating = true})
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 5%-"), {locked = true, repeating = true})
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), {locked = true})
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), {locked = true})
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), {locked = true})
hl.window_rule({name = "g8d-no-maximize", match = {class = ".*"}, suppress_event = "maximize"})
dofile(root .. "file-dialogs.lua")
dofile(root .. "accent.lua")
hl.on("hyprland.start", function() hl.exec_cmd(root .. "autostart") end)
