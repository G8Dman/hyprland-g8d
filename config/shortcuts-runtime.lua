-- Native actions stay Lua closures, including workspace and switcher state.
g8d_shortcut_overrides = {}
g8d_standard_defaults = {}
local root = (os.getenv("G8D_CONFIG_DIR") or (os.getenv("HOME") .. "/.config/hyprland-g8d")) .. "/"
local file = io.open(root .. "shortcuts.lua", "r")
if file then file:close(); dofile(root .. "shortcuts.lua") end
function g8d_standard_combo(id)
    local override = g8d_shortcut_overrides[id]
    return (override and override.combo) or g8d_standard_defaults[id]
end
function g8d_standard_active(id)
    local override = g8d_shortcut_overrides[id]
    return not (override and override.command)
end
function g8d_bind(id, name, combo, action, options)
    g8d_standard_defaults[id] = combo
    options = options or {}
    local override = g8d_shortcut_overrides[id]
    if override and override.command then
        action = hl.dsp.exec_cmd(override.command)
        -- User applications/commands run once, with the desktop unlocked.
        options = {}
        if g8d_standard_combo(id):find("mouse:", 1, true) then options.mouse = true end
    end
    options.description = "g8d-standard:" .. id
    return hl.bind(g8d_standard_combo(id), action, options)
end
