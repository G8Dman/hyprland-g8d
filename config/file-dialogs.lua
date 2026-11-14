-- File choosers and modal dialogs must float above their fullscreen parent.
hl.window_rule({
    name = "g8d-modal-dialogs", match = { modal = true },
    float = true, center = true, tag = "+g8d-dialog",
})
hl.window_rule({
    name = "g8d-portal-dialogs",
    match = { class = "^(org[.]freedesktop[.]impl[.]portal[.]desktop[.]kde|xdg-desktop-portal-(kde|gtk)|org[.]kde[.]kdialog|kdialog)$" },
    float = true, center = true, size = { "900", "600" }, tag = "+g8d-dialog",
})
hl.window_rule({
    name = "g8d-file-dialog-titles",
    match = { title = "^(Open( File| Files| Folder)?|Save( File| As)?|Select (File|Files|Folder)|File (Upload|Chooser)|Открыть( файл| файлы| папку)?|Сохранить( файл| как)?|Выбор (файла|файлов|папки)|Загрузка файла)([ —–-].*)?$" },
    float = true, center = true, size = { "900", "600" }, tag = "+g8d-dialog",
})
local origins = {}
local focus_timers = {}
local managers = { ["org.kde.dolphin"] = true, thunar = true,
    ["org.gnome.Nautilus"] = true, nemo = true }
hl.on("window.open_early", function(w)
    local active = hl.get_active_window()
    if w and active and active.fullscreen ~= 0 and active.workspace then
        origins[w.address] = active.workspace.id
    end
end)
hl.on("window.open", function(w)
    if not w then return end
    local origin = origins[w.address]
    origins[w.address] = nil
    local dialog = false
    for _, candidate in ipairs(hl.get_windows({ tag = "g8d-dialog" })) do
        if candidate.address == w.address then dialog = true; break end
    end
    if not dialog and not (origin and managers[w.class]) then return end
    local address = w.address
    local selector = "address:" .. address
    hl.dispatch(hl.dsp.window.float({ window = selector, action = "set" }))
    if origin then
        hl.dispatch(hl.dsp.window.move({ window = selector, workspace = origin, follow = false }))
    end
    if origin and managers[w.class] then
        hl.dispatch(hl.dsp.window.resize({ window = selector, x = 900, y = 600 }))
    end
    hl.dispatch(hl.dsp.window.center({ window = selector }))
    -- A new file-manager starts tiled; finish raising after its map transaction.
    focus_timers[address] = hl.timer(function()
        local target = hl.get_window(selector)
        if target and target.mapped then
            hl.dispatch(hl.dsp.focus({ window = selector }))
            hl.dispatch(hl.dsp.window.bring_to_top())
        end
        focus_timers[address] = nil
    end, { timeout = 60, type = "oneshot" })
end)
