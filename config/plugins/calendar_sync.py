"""Private Google iCalendar subscription, cached offline; no account credentials."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from icalendar import Calendar
import recurring_ical_events

ROOT = Path.home() / '.config/hyprland-g8d'
CONFIG = ROOT / 'calendar.json'
CACHE = Path.home() / '.local/state/hyprland-g8d/calendar.ics'


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
    temporary.replace(path)


class CalendarSync:
    def __init__(self):
        self.lock = threading.Lock()
        self.calendar = None
        self.url = ''
        self.attempt = 0
        self.updated = 0
        self.error = False
        self.busy = False
        try:
            self.url = json.loads(CONFIG.read_text()).get('url', '')
            if self.url and CACHE.exists():
                self.calendar = Calendar.from_ical(CACHE.read_bytes())
                self.updated = CACHE.stat().st_mtime
        except (OSError, ValueError):
            pass

    def configure(self, url):
        url = url.strip()
        parsed = urlsplit(url)
        if url and not (parsed.scheme == 'https' and parsed.hostname == 'calendar.google.com'
                        and parsed.path.startswith('/calendar/ical/') and parsed.path.endswith('.ics')
                        and not parsed.username and not parsed.password):
            raise ValueError('Нужен адрес iCal из настроек Google Календаря.')
        with self.lock:
            private_write(CONFIG, json.dumps({'url': url}).encode())
            CACHE.unlink(missing_ok=True)
            self.url, self.calendar = url, None
            self.attempt = self.updated = 0
            self.error = False

    def refresh(self, force=False):
        with self.lock:
            if self.busy or not self.url or (not force and time.time() - self.attempt < 300):
                return
            self.busy = True
            self.attempt = time.time()
            url = self.url
        def fetch():
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'hyprland-g8d-calendar/1'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError('Calendar too large')
                calendar = Calendar.from_ical(raw)
                if calendar.name != 'VCALENDAR':
                    raise ValueError('Invalid calendar')
                with self.lock:
                    if self.url == url:
                        private_write(CACHE, raw)
                        self.calendar, self.updated, self.error = calendar, time.time(), False
            except Exception:
                # Do not leak the private subscription URL through exception messages.
                with self.lock:
                    if self.url == url: self.error = True
            finally:
                with self.lock: self.busy = False
        threading.Thread(target=fetch, name='g8d-calendar-sync', daemon=True).start()

    def month(self, year, month):
        with self.lock:
            calendar = self.calendar
        if calendar is None: return []
        start = dt.datetime(year, month, 1).astimezone()
        end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        result = []
        for event in recurring_ical_events.of(calendar).between(start, end):
            if str(event.get('STATUS', '')).upper() == 'CANCELLED': continue
            begin = event.decoded('DTSTART')
            finish = event.decoded('DTEND', begin)
            all_day = not isinstance(begin, dt.datetime)
            if not all_day:
                begin = begin.astimezone() if begin.tzinfo else begin.replace(tzinfo=start.tzinfo)
                finish = finish.astimezone() if finish.tzinfo else finish.replace(tzinfo=start.tzinfo)
            result.append({'start': begin, 'end': finish, 'all_day': all_day,
                           'title': str(event.get('SUMMARY', 'Без названия')),
                           'location': str(event.get('LOCATION', ''))})
        return sorted(result, key=lambda e: (e['start'].isoformat()[:10], not e['all_day'], e['start'].isoformat()))

    def status(self):
        with self.lock:
            if not self.url: return 'Google Календарь не подключён'
            if self.busy: return 'Обновление событий…'
            if self.error: return 'Нет связи · сохранённые события' if self.calendar else 'Не удалось загрузить календарь'
            if self.updated: return 'Обновлено в ' + dt.datetime.fromtimestamp(self.updated).strftime('%H:%M')
            return 'Ожидание обновления'
