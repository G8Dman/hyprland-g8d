"""Persistent native media controls; artwork and metadata replace the decorative turntable."""
from pathlib import Path
from urllib.parse import unquote, urlparse
from gi.repository import GdkPixbuf, GLib, Gtk, Pango


def label(value='', style=''):
    widget=Gtk.Label(label=value,xalign=0)
    widget.set_ellipsize(Pango.EllipsizeMode.END)
    widget.set_max_width_chars(36)
    if style:widget.get_style_context().add_class(style)
    return widget


def icon_button(icon, name, callback, primary=False):
    widget=Gtk.Button()
    widget.add(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.LARGE_TOOLBAR))
    widget.set_size_request(60 if primary else 44,60 if primary else 44)
    widget.get_style_context().add_class('media-play' if primary else 'media-icon')
    widget.set_tooltip_text(name);widget.get_accessible().set_name(name)
    widget.connect('clicked',lambda *_:callback())
    return widget


def clock(value):
    seconds=max(0,int(value/1_000_000))
    return f'{seconds//60}:{seconds%60:02}'


class MusicView(Gtk.Box):
    def __init__(self,popup):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=20)
        self.popup=popup;self.player=None;self.updating=False;self.sources=None;self.cover_key=None;self.yandex=None
        self.get_style_context().add_class('music-view')
        header=Gtk.Box(spacing=12)
        self.source=label('Музыка','media-source');header.pack_start(self.source,True,True,0)
        self.selector=Gtk.ComboBoxText();self.selector.set_no_show_all(True)
        self.selector.get_accessible().set_name('Источник музыки')
        for renderer in self.selector.get_cells():
            renderer.set_property('ellipsize',Pango.EllipsizeMode.END)
            renderer.set_property('max-width-chars',18)
        self.selector.connect('changed',lambda widget:popup.select_player(widget) if not self.updating else None)
        header.pack_start(self.selector,False,False,0)
        self.launch=Gtk.Button(label='Запустить Яндекс Музыку');self.launch.get_style_context().add_class('media-launch')
        self.launch.connect('clicked',self.open_player);header.pack_end(self.launch,False,False,0)
        self.pack_start(header,False,False,0)
        track=Gtk.Box(spacing=20);track.get_style_context().add_class('media-track')
        self.art=Gtk.Image();self.art.set_size_request(112,112);self.art.set_no_show_all(True)
        self.art.get_style_context().add_class('media-art');track.pack_start(self.art,False,False,0)
        copy=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);copy.set_valign(Gtk.Align.CENTER)
        self.title=label('Ничего не играет','media-title');self.title.set_line_wrap(True);self.title.set_lines(2)
        self.artist=label('Запусти плеер или выбери подборку.','media-artist')
        self.status=label('','media-status');self.status.set_no_show_all(True)
        for child in (self.title,self.artist,self.status):copy.pack_start(child,False,False,0)
        track.pack_start(copy,True,True,0);self.pack_start(track,False,False,0)
        self.timeline=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);self.timeline.set_no_show_all(True)
        self.progress=Gtk.ProgressBar();self.progress.get_style_context().add_class('media-progress')
        self.progress.get_accessible().set_name('Прогресс воспроизведения')
        times=Gtk.Box();self.elapsed=label('0:00','media-time');self.duration=label('0:00','media-time')
        times.pack_start(self.elapsed,False,False,0);times.pack_end(self.duration,False,False,0)
        self.timeline.pack_start(self.progress,False,False,0);self.timeline.pack_start(times,False,False,0)
        self.pack_start(self.timeline,False,False,0)
        self.controls=Gtk.Box(spacing=12);self.controls.set_halign(Gtk.Align.CENTER);self.controls.set_no_show_all(True)
        self.previous=icon_button('media-skip-backward-symbolic','Предыдущий трек',lambda:self.send('Previous'))
        self.play=icon_button('media-playback-start-symbolic','Воспроизвести',lambda:self.send('PlayPause'),True)
        self.next=icon_button('media-skip-forward-symbolic','Следующий трек',lambda:self.send('Next'))
        self.back=Gtk.Button(label='−10');self.forward=Gtk.Button(label='+10')
        for button,name,method in [(self.back,'Назад на 10 секунд','SeekBack'),(self.forward,'Вперёд на 10 секунд','SeekForward')]:
            button.get_style_context().add_class('media-seek');button.set_tooltip_text(name);button.get_accessible().set_name(name)
            button.set_no_show_all(True);button.connect('clicked',lambda _,method=method:self.send(method))
        for child in (self.back,self.previous,self.play,self.next,self.forward):self.controls.pack_start(child,False,False,0)
        self.pack_start(self.controls,False,False,0)
        presets=Gtk.Box(spacing=12)
        self.presets=[]
        for title,action in [('Моя волна','wave'),('Любимые треки','favorites')]:
            button=Gtk.Button(label=title);button.get_style_context().add_class('media-preset')
            button.connect('clicked',lambda _,action=action:popup.play_yandex(action))
            presets.pack_start(button,True,True,0);self.presets.append(button)
        self.pack_start(presets,False,False,0)
        self.notice=label('','media-notice');self.notice.set_line_wrap(True);self.notice.set_no_show_all(True)
        self.pack_start(self.notice,False,False,0)

    def send(self,method):
        if self.player:self.popup.app.music(self.player['bus'],method)

    def open_player(self,*_):
        if self.yandex:self.popup.open_yandex_music()
        else:self.popup.play_yandex('background')

    def artwork(self,uri):
        try:
            parsed=urlparse(uri)
            if parsed.scheme!='file' or parsed.netloc not in ('','localhost'):raise ValueError('Not local artwork')
            path=Path(unquote(parsed.path));stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
            if key==self.cover_key:return
            if not path.is_file() or stat.st_size>6*1024*1024:raise ValueError('Artwork too large')
            cover=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),112,112,True)
            self.art.set_from_pixbuf(cover);self.cover_key=key
        except (OSError,ValueError,TypeError,GLib.Error):
            if self.cover_key!='empty':self.art.set_from_icon_name('audio-x-generic-symbolic',Gtk.IconSize.DIALOG)
            self.cover_key='empty'

    def update(self,data):
        players=data.get('media',[]);self.yandex=next((p for p in players if p.get('yandex')),None)
        self.player=next((p for p in players if p['bus']==self.popup.preferred_player),self.yandex or (players[0] if players else None))
        self.popup.player=self.player['bus'] if self.player else None
        busy=self.popup.app.music_pending
        self.launch.set_label('Открыть Яндекс Музыку' if self.yandex else 'Запустить Яндекс Музыку');self.launch.set_sensitive(not busy)
        self.launch.set_tooltip_text('Официальное приложение: его очередь работает отдельно от фонового плеера.' if self.yandex else 'Запустить фоновый плеер Яндекс Музыки')
        sources=tuple((p['bus'],p['player']) for p in players)
        self.updating=True
        if sources!=self.sources:
            self.selector.remove_all();self.selector.append('auto','Авто')
            for bus,name in sources:self.selector.append(bus,name)
            self.sources=sources
        self.selector.set_active_id(self.popup.preferred_player if self.popup.preferred_player in dict(sources) else 'auto')
        self.updating=False
        self.selector.set_visible(len(players)>1)
        selected=self.player
        source=selected['player'] if selected else 'Музыка'
        self.source.set_text(source.upper() if self.get_style_context().lookup_color('nd_bg')[0] else source)
        self.art.set_visible(bool(selected));self.controls.set_visible(bool(selected));self.status.set_visible(bool(selected))
        self.timeline.set_visible(bool(selected and selected.get('length')))
        if selected:
            self.title.set_text(selected['title'] or 'Без названия');self.title.set_tooltip_text(selected['title'])
            artist=selected['artist'] or selected['album'] or selected['player']
            self.artist.set_text(artist);self.artist.set_tooltip_text(artist)
            playing=selected['status']=='Playing'
            self.status.set_text({'Playing':'Играет','Paused':'На паузе','Stopped':'Остановлено'}.get(selected['status'],selected['status']))
            self.artwork(selected.get('art',''))
            enabled=selected['control'] and not busy
            for widget,capability in [(self.previous,'previous'),(self.next,'next'),(self.play,'pause' if playing else 'play')]:widget.set_sensitive(enabled and selected[capability])
            self.play.get_child().set_from_icon_name('media-playback-pause-symbolic' if playing else 'media-playback-start-symbolic',Gtk.IconSize.LARGE_TOOLBAR)
            name='Пауза' if playing else 'Воспроизвести';self.play.set_tooltip_text(name);self.play.get_accessible().set_name(name)
            for widget in (self.back,self.forward):widget.set_visible(bool(selected.get('seek')));widget.set_sensitive(enabled and bool(selected.get('seek')))
            length=selected.get('length',0);position=selected.get('position',0)
            self.progress.set_fraction(max(0,min(1,position/length)) if length else 0)
            self.elapsed.set_text(clock(position));self.duration.set_text(clock(length))
        else:
            self.title.set_text('Ничего не играет');self.title.set_tooltip_text(None)
            self.artist.set_text('Запусти плеер или выбери подборку.');self.artist.set_tooltip_text(None)
        for button in self.presets:button.set_sensitive(not busy)
        message=self.popup.app.music_message if busy else self.popup.app.music_error
        if not message and selected and selected.get('yandex') and not selected['play'] and not selected['pause']:
            message='Выбери трек или включи «Мою волну».'
        self.notice.set_text(message);self.notice.set_visible(bool(message))
        self.notice.get_style_context().remove_class('error')
        if self.popup.app.music_error and not busy:self.notice.get_style_context().add_class('error')
        # Keep hidden states stable when the parent dashboard calls show_all().
        for container in (self.controls,self.timeline):
            for child in container.get_children():
                if child not in (self.back,self.forward):child.show_all()
