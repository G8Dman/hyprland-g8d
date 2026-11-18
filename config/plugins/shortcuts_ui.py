"""GTK editor for custom application and shell shortcuts."""
import uuid
from gi.repository import Gdk, Gio, Gtk, Pango
import shortcuts


def label(value):
    widget=Gtk.Label(label=value,xalign=0)
    widget.set_line_wrap(True)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_max_width_chars(45)
    return widget


class ShortcutPage:
    def __init__(self,settings,page):
        self.settings=settings
        page.pack_start(label('Запускай приложения или свои команды. Изменения применяются сразу и сохраняются после перезагрузки.'),False,False,0)
        add=Gtk.Button(label='Добавить сочетание')
        add.connect('clicked',lambda *_:self.edit())
        page.pack_start(add,False,False,0)
        self.search=Gtk.SearchEntry()
        self.search.set_placeholder_text('Найти действие или сочетание')
        self.search.connect('search-changed',lambda *_:self.refresh())
        page.pack_start(self.search,False,False,0)
        self.rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        self.rows.get_style_context().add_class('shortcut-list')
        page.pack_start(self.rows,False,False,0)
        self.refresh()

    def refresh(self):
        for child in self.rows.get_children(): child.destroy()
        try: items=shortcuts.effective()
        except Exception as exc:
            self.settings.message(str(exc),True);return
        query=self.search.get_text().casefold()
        items=[i for i in items if query in (i['name']+' '+i['combo']).casefold()]
        if not items: self.rows.pack_start(label('Сочетания не найдены.'),False,False,0)
        for item in items:
            box=Gtk.Box(spacing=10)
            box.get_style_context().add_class('setting-row')
            copy=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
            copy.pack_start(label(item['name']+' · '+item['combo']),False,False,0)
            if item['kind']=='standard':
                action='Стандартное действие · '+item['default_name']
            else:
                action=item.get('app_name',item.get('desktop_id','')) if item['kind']=='app' else item['command']
            if item.get('builtin'): action+=' · По умолчанию: '+item['default_combo']
            if item['kind']=='command': action+=' · '+('в терминале' if item['terminal'] else 'без окна терминала')
            detail=label(action);detail.set_max_width_chars(45)
            copy.pack_start(detail,False,False,0)
            box.pack_start(copy,True,True,0)
            second=('Сбросить',lambda _,i=item:self.reset(i)) if item.get('builtin') else ('Удалить',lambda _,i=item:self.delete(i))
            for title,callback in [('Изменить',lambda _,i=item:self.edit(i)),second]:
                button=Gtk.Button(label=title);button.set_valign(Gtk.Align.CENTER)
                if title=='Удалить':button.get_style_context().add_class('destructive-action')
                button.connect('clicked',callback)
                if title=='Сбросить':button.set_sensitive(item['combo']!=item['default_combo'] or item['name']!=item['default_name'] or item['kind']!='standard')
                box.pack_start(button,False,False,0)
            self.rows.pack_start(box,False,False,0)
        self.rows.show_all()

    def commit(self,items,done):
        self.settings.work(lambda:shortcuts.save(items),lambda *_:(self.refresh(),done()),'Сочетания сохранены и применены.')

    def reset(self,item):
        try:self.commit([i for i in shortcuts.load() if i['id']!=item['id']],lambda:None)
        except Exception as exc:self.settings.message(str(exc),True)

    def delete(self,item):
        dialog=Gtk.MessageDialog(transient_for=self.settings.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text='Удалить «'+item['name']+'»?')
        dialog.get_style_context().add_class('g8d-settings')
        def response(d,r):
            d.destroy()
            if r==Gtk.ResponseType.OK:
                try: self.commit([i for i in shortcuts.load() if i['id']!=item['id']],lambda:None)
                except Exception as exc: self.settings.message(str(exc),True)
        dialog.connect('response',response);dialog.show_all()

    def edit(self,item=None):
        original=item
        item=dict(item or {'id':uuid.uuid4().hex,'kind':'app','terminal':False})
        dialog=Gtk.Dialog(title='Изменить сочетание' if original else 'Новое сочетание',transient_for=self.settings.window,modal=True)
        dialog.set_default_size(650,520)
        dialog.get_style_context().add_class('g8d-settings')
        dialog.add_buttons('Отмена',Gtk.ResponseType.CANCEL,'Сохранить',Gtk.ResponseType.OK)
        body=dialog.get_content_area();body.set_spacing(10);body.set_border_width(20)
        name=Gtk.Entry();name.set_text(item.get('name',''));name.set_placeholder_text('Название, например «Мой браузер»')
        body.pack_start(label('Название'),False,False,0);body.pack_start(name,False,False,0)
        combo=Gtk.Entry();combo.set_text(item.get('combo',''));combo.set_placeholder_text('SUPER + CTRL + K')
        body.pack_start(label('Сочетание клавиш'),False,False,0);body.pack_start(combo,False,False,0)
        capture=Gtk.ToggleButton(label='Записать нажатие клавиш')
        body.pack_start(capture,False,False,0)
        def keypress(_,event):
            if not capture.get_active():return False
            if event.keyval==Gdk.KEY_Escape:
                capture.set_active(False);capture.set_label('Записать нажатие клавиш');return True
            if event.is_modifier:return True
            result=Gdk.Keymap.get_for_display(dialog.get_display()).translate_keyboard_state(event.hardware_keycode,Gdk.ModifierType(0),0)
            key=Gdk.keyval_name(result[1] if result[0] else event.keyval)
            mods=[]
            for flag,title in [(Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK,'SUPER'),(Gdk.ModifierType.CONTROL_MASK,'CTRL'),(Gdk.ModifierType.MOD1_MASK,'ALT'),(Gdk.ModifierType.SHIFT_MASK,'SHIFT')]:
                if event.state & flag:mods.append(title)
            combo.set_text(' + '.join(mods+[key or '']))
            capture.set_active(False);capture.set_label('Записать нажатие клавиш');return True
        capture.connect('toggled',lambda b:b.set_label('Нажми сочетание · Esc — отмена' if b.get_active() else 'Записать нажатие клавиш'))
        dialog.connect('key-press-event',keypress)
        kind=Gtk.ComboBoxText();kind.append('app','Открыть приложение');kind.append('command','Выполнить команду')
        if item.get('builtin'):
            kind.append('standard','Исходное действие: '+item['default_name'])
            body.pack_start(label('Можно выбрать другое приложение, свою команду или исходное действие.\nИсходное сочетание: '+item['default_combo']),False,False,0)
        body.pack_start(label('Действие'),False,False,0);body.pack_start(kind,False,False,0)
        appbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        search=Gtk.SearchEntry();search.set_placeholder_text('Поиск приложений из Super + R')
        appbox.pack_start(search,False,False,0)
        apps=sorted([a for a in Gio.AppInfo.get_all() if a.get_id() and a.should_show()],key=lambda a:a.get_display_name().casefold())
        chooser=Gtk.ComboBoxText();appbox.pack_start(chooser,False,False,0)
        selected=[item.get('desktop_id')]
        def populate(*_):
            if chooser.get_active_id():selected[0]=chooser.get_active_id()
            query=search.get_text().casefold();chooser.remove_all()
            for app in apps:
                if query in (app.get_display_name()+' '+app.get_id()).casefold():chooser.append(app.get_id(),app.get_display_name())
            if selected[0]:chooser.set_active_id(selected[0])
            if chooser.get_active()<0:chooser.set_active(0)
        search.connect('search-changed',populate);populate()
        body.pack_start(appbox,False,False,0)
        cmdbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        command=Gtk.Entry();command.set_placeholder_text('Например: notify-send "Привет"');command.set_text(item.get('command',''))
        cmdbox.pack_start(command,False,False,0)
        terminal=Gtk.CheckButton(label='Открывать терминал и оставлять результат на экране');terminal.set_active(item.get('terminal',False))
        cmdbox.pack_start(terminal,False,False,0)
        cmdbox.pack_start(label('Без этой галочки команда выполняется в фоне, без окна терминала.'),False,False,0)
        body.pack_start(cmdbox,False,False,0)
        error=label('');error.get_style_context().add_class('error');body.pack_start(error,False,False,0)
        def visibility(*_):
            appbox.set_visible(kind.get_active_id()=='app');cmdbox.set_visible(kind.get_active_id()=='command')
        kind.connect('changed',visibility);kind.set_active_id(item.get('kind','app'))
        def response(_,response):
            if response!=Gtk.ResponseType.OK:dialog.destroy();return
            updated={'id':item['id'],'name':name.get_text().strip(),'combo':combo.get_text(),'kind':kind.get_active_id()}
            if item.get('builtin'):updated['builtin']=item['builtin']
            if updated['kind']=='standard':pass
            elif updated['kind']=='app':
                updated.update(desktop_id=chooser.get_active_id(),app_name=chooser.get_active_text())
            else:updated.update(command=command.get_text(),terminal=terminal.get_active())
            try:
                items=[i for i in shortcuts.load() if i['id']!=item['id']]+[updated]
                shortcuts.validate(items)
            except Exception as exc:error.set_text(str(exc));return
            dialog.set_response_sensitive(Gtk.ResponseType.OK,False)
            dialog.set_response_sensitive(Gtk.ResponseType.CANCEL,False)
            def operation():
                try:shortcuts.save(items)
                except Exception as exc:
                    from gi.repository import GLib
                    GLib.idle_add(failed,str(exc));return False
                return True
            def failed(message):
                error.set_text(message);dialog.set_response_sensitive(Gtk.ResponseType.OK,True);dialog.set_response_sensitive(Gtk.ResponseType.CANCEL,True)
            def done(ok):
                if ok:dialog.destroy();self.refresh();self.settings.message('Сочетания сохранены и применены.')
            self.settings.work(operation,done)
        dialog.connect('response',response)
        dialog.show_all();visibility();name.grab_focus()
        return dialog
