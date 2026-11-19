"""Interface styling independent of the two Waybar styles. No runtime downloads."""
from pathlib import Path
import shutil
import re
import subprocess

STYLES = {'material': 'Material', 'nothing': 'Nothing'}
NOTHING_COLORS = {
    'dark': dict(zip(('background','surface','control','text','muted','border','selection'),
                     ('#000000','#111111','#1a1a1a','#e8e8e8','#999999','#333333','#262626'))),
    'light': dict(zip(('background','surface','control','text','muted','border','selection'),
                      ('#f5f5f5','#ffffff','#f0f0f0','#1a1a1a','#666666','#cccccc','#e8e8e8')))}


def ensure_fonts(root, target_home=None):
    source = Path(root) / 'themes/nothing/fonts'
    target = (Path.home() if target_home is None else Path(target_home)) / '.local/share/fonts/g8d-nothing'
    changed = False
    for font in source.rglob('*.ttf'):
        destination = target / font.name
        if not destination.exists() or destination.read_bytes() != font.read_bytes():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(font, destination)
            changed = True
    if changed: subprocess.run(['fc-cache', '-f', str(target)], check=True, timeout=15)


def tokens(palette, mode):
    values = {'bg':palette['background'], 'surface':palette['surface'], 'control':palette['control'],
              'text':palette['text'], 'muted':palette['muted'], 'border':palette['border'],
              'selection':palette['selection'], 'display':'#ffffff' if mode=='dark' else '#000000',
              'signal':'#d71921', 'on_primary':palette['background']}
    return '\n' + '\n'.join('@define-color nd_'+key+' '+color+';' for key,color in values.items())+'\n'


def render(rendered, palette, mode):
    for file in ['plugins/style.css','plugins/settings.css']: rendered[file] += tokens(palette, mode)
    rendered['rofi.rasi'] = '''configuration { display-drun: "ПРИЛОЖЕНИЯ"; }
* {
 font: "Space Grotesk 12";
 bg: %BG%; fg: %TEXT%; muted: %MUTED%; surface: %SURFACE%; edge: %BORDER%;
 selected: %TEXT%; on-selected: %BG%;
 background-color: transparent; text-color: @fg;
}
window { width: 600px; padding: 24px; border: 1px; border-color: @edge; border-radius: 16px; background-color: @bg; }
mainbox { children: [inputbar, listview]; spacing: 24px; }
inputbar { children: [prompt, entry]; spacing: 16px; padding: 12px 0px; border: 0px 0px 1px; border-color: @edge; }
prompt { font: "Space Mono 10"; text-color: @muted; }
entry { placeholder: "Название приложения…"; placeholder-color: @muted; }
listview { lines: 7; fixed-height: false; scrollbar: false; spacing: 4px; }
element { padding: 14px 16px; border-radius: 6px; spacing: 16px; }
element selected.normal { background-color: @selected; text-color: @on-selected; }
element-icon { size: 24px; }
element-text { vertical-align: 0.5; text-color: inherit; }
'''
    for key, role in {'BG':'background','TEXT':'text','MUTED':'muted','SURFACE':'surface','BORDER':'border'}.items():
        rendered['rofi.rasi'] = rendered['rofi.rasi'].replace('%'+key+'%',palette[role])
    # Keep app recognizability; icon colors remain the app's own, outside UI chrome.
    lock = rendered['hyprlock.conf'].replace('font_family = Roboto','font_family = Space Grotesk')
    lock = lock.replace('font_family = Space Grotesk','font_family = Doto',1)
    lock = lock.replace('rounding = 28','rounding = 16')
    lock = re.sub(r'(?m)^(\s*text\s*=\s*).*/ (graphite|clear)\s*$', r'\1g8d / nothing', lock)
    rendered['hyprlock.conf'] = lock
    rendered['kitty.conf'] = rendered['kitty.conf'].replace('font_family DejaVu Sans Mono', 'font_family Space Mono')
    rendered['mako.conf'] = rendered['mako.conf'].replace('font=DejaVu Sans 10','font=Space Grotesk 10')


def apply_typography(widget, style):
    """Only metadata is uppercased; saved data and accessible control names are intact."""
    from gi.repository import Gtk
    if isinstance(widget, Gtk.Label):
        context = widget.get_style_context()
        if any(context.has_class(c) for c in ('heading','section-heading')):
            if not hasattr(widget, '_g8d_original_text'): widget._g8d_original_text = widget.get_text()
            original = widget._g8d_original_text
            widget.set_text(original.upper() if style == 'nothing' else original)
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children(): apply_typography(child, style)
