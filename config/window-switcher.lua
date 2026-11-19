-- Quick Alt+Tab commits the previous window; holding both keys shows a chooser.
local cycle, timer = nil, nil
local sequence = os.time() * 1000
local sender = (os.getenv("G8D_CONFIG_DIR") or (os.getenv("HOME") .. "/.config/hyprland-g8d")) .. "/plugins/switcher-ipc.py"
local function menu(show)
    sequence = sequence + 1
    local args = " " .. sequence .. " " .. (show and cycle.index or 0)
    if show then args = args .. " " .. table.concat(cycle.addresses, " ") end
    hl.exec_cmd("python3 " .. sender .. args)
end
local function stop_timer()
    if timer then timer:set_enabled(false); timer = nil end
end
function g8d_switch_commit(index)
    if not cycle then return end
    stop_timer()
    local address = cycle.addresses[index or cycle.index]
    menu(false)
    cycle = nil
    if address and hl.get_window("address:" .. address) then
        hl.dispatch(hl.dsp.focus({ window = "address:" .. address }))
        hl.dispatch(hl.dsp.window.bring_to_top())
    end
end
local function switch_window(reverse)
    if not cycle then
        local windows = {}
        for _, w in ipairs(hl.get_windows()) do
            local background_music = w.workspace and w.workspace.name == "special:g8d-music"
            if w.mapped and not w.hidden and w.accepts_input and not background_music then table.insert(windows, w) end
        end
        table.sort(windows, function(a, b) return a.focus_history_id < b.focus_history_id end)
        cycle = { addresses = {}, index = 1, shown = false }
        local active = hl.get_active_window()
        for i, w in ipairs(windows) do
            cycle.addresses[i] = w.address
            if active and active.address == w.address then cycle.index = i end
        end
    end
    local count = #cycle.addresses
    if count == 0 then cycle = nil; return end
    cycle.index = (cycle.index - 1 + (reverse and -1 or 1)) % count + 1
    if cycle.shown then menu(true)
    elseif not timer then
        timer = hl.timer(function()
            if cycle then cycle.shown = true; menu(true) end
            stop_timer()
        end, { timeout = 250, type = "oneshot" })
    end
end
g8d_bind("switch-next", "Следующее окно", "ALT + Tab", function() switch_window(false) end)
g8d_bind("switch-prev", "Предыдущее окно", "ALT + SHIFT + Tab", function() switch_window(true) end)
-- Keep release observers in sync when the chooser shortcuts are reassigned.
local observed_keys, observed_mods = {}, {}
local modifier_keys = { ALT = {"Alt_L", "Alt_R"}, CTRL = {"Control_L", "Control_R"}, SUPER = {"Super_L", "Super_R"} }
for _, id in ipairs({"switch-next", "switch-prev"}) do
    if g8d_standard_active(id) then
        local combo = g8d_standard_combo(id)
        for key in combo:gmatch("[^ +]+") do
            if not modifier_keys[key] and key ~= "SHIFT" and not observed_keys[key] then
                observed_keys[key] = true
                hl.bind(key, stop_timer, { release = true, ignore_mods = true, non_consuming = true })
            end
        end
        for mod, keys in pairs(modifier_keys) do
            if combo:find(mod .. " +", 1, true) and not observed_mods[mod] then
                observed_mods[mod] = true
                for _, release_key in ipairs(keys) do
                    hl.bind(mod .. " + " .. release_key, function() g8d_switch_commit() end,
                        { release = true, ignore_mods = true, transparent = true })
                end
            end
        end
    end
end
hl.bind("Escape", function()
    if cycle then stop_timer(); menu(false); cycle = nil end
end, { ignore_mods = true, non_consuming = true })
