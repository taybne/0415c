"""Finds coordinates for branch addresses listed in static/branches.json.

Uses the public OpenStreetMap Nominatim service (max 1 request/second).
Results are written back into branches.json, so every address is looked up once.

CLI:  python geocoder.py           # fill in missing coordinates
      python geocoder.py --retry   # also retry addresses that failed before
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'static', 'branches.json')
LOCK = os.path.join(BASE, 'branches.lock')

CITY_RU = {'spb': 'Санкт-Петербург', 'moscow': 'Москва', 'novosibirsk': 'Новосибирск'}
# left, top, right, bottom
VIEWBOX = {
    'spb': (29.55, 60.25, 30.85, 59.55),
    'moscow': (37.15, 56.05, 38.05, 55.45),
    'novosibirsk': (82.55, 55.30, 83.35, 54.70),
}
USER_AGENT = 'TAG-miniapp/1.0 (one-time branch geocoding)'


def _lookup(query, city):
    box = VIEWBOX[city]
    params = urllib.parse.urlencode({
        'q': f'{CITY_RU[city]}, {query}', 'format': 'json', 'limit': 1,
        'accept-language': 'ru', 'bounded': 1,
        'viewbox': ','.join(str(x) for x in box),
    })
    req = urllib.request.Request('https://nominatim.openstreetmap.org/search?' + params,
                                 headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf8'))
    time.sleep(1.1)  # Nominatim usage policy
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    return None


def _variants(q):
    yield q
    if ', ' in q:
        street, house = q.rsplit(', ', 1)
        m = re.match(r'\d+', house)
        if m and m.group(0) != house:
            yield f'{street}, {m.group(0)}'


def geocode(query, city):
    for v in _variants(query):
        try:
            found = _lookup(v, city)
        except Exception as exc:  # network problem: do not mark as failed
            raise ConnectionError(str(exc))
        if found:
            return found
    return None


def _touch_lock():
    try:
        os.utime(LOCK, None)
    except OSError:
        pass


def _save(groups):
    tmp = DATA + '.tmp'
    with open(tmp, 'w', encoding='utf8') as f:
        json.dump(groups, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)


def run(retry=False, log=print):
    # NOTE: lock file is refreshed on every request; a lock older than 90 s is considered stale
    with open(DATA, encoding='utf8') as f:
        groups = json.load(f)
    done = failed = 0
    todo = sum(1 for g in groups for b in g['branches']
               if b.get('lat') is None and (retry or not b.get('failed')))
    log(f'Geocoding {todo} addresses (about {int(todo * 1.5 / 60) + 1} min)...')
    for g in groups:
        for b in g['branches']:
            if b.get('lat') is not None:
                continue
            if b.get('failed') and not retry:
                continue
            _touch_lock()
            try:
                found = geocode(b['q'], g['city'])
            except ConnectionError as exc:
                log(f'Network error, stopping: {exc}')
                _save(groups)
                return done, failed
            if found:
                b['lat'], b['lon'] = round(found[0], 6), round(found[1], 6)
                b.pop('failed', None)
                done += 1
            else:
                b['failed'] = True
                failed += 1
                log(f"Not found: {g['city']} / {b['address']}")
            if (done + failed) % 5 == 0:
                _save(groups)
                log(f'[GEOCODER] {done + failed}/{todo}')
    _save(groups)
    log(f'Geocoding finished: found {done}, not found {failed}')
    return done, failed


def run_in_background():
    """Start run() once in a daemon thread (guarded by a lock file)."""
    import threading
    try:
        if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) > 90:
            os.remove(LOCK)
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return

    def worker():
        try:
            run()
        finally:
            try:
                os.remove(LOCK)
            except OSError:
                pass

    threading.Thread(target=worker, daemon=True).start()


if __name__ == '__main__':
    run(retry='--retry' in sys.argv)
