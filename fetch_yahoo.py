"""Refresh data.json from Yahoo's official Fantasy Sports API (runs in GitHub Actions).

Needs three environment variables (stored as GitHub repo secrets):
  YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_REFRESH_TOKEN

Writes data.json in the same format the site already reads. Uses only the Python
standard library. Exits with an error (and leaves data.json alone) if anything looks wrong.
"""
import base64, json, urllib.error, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LID = 68635
LEAGUE = f'nfl.l.{LID}'
API = 'https://fantasysports.yahooapis.com/fantasy/v2/'
TZ = ZoneInfo('America/Toronto')


def token():
    cid, sec, rt = (os.environ[k] for k in ('YAHOO_CLIENT_ID', 'YAHOO_CLIENT_SECRET', 'YAHOO_REFRESH_TOKEN'))
    err = None
    for redirect in ('https://jakeschles.github.io/WFFL-League-Hub/', 'https://localhost:8080', 'oob'):
        req = urllib.request.Request(
            'https://api.login.yahoo.com/oauth2/get_token',
            data=urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': rt,
                                         'redirect_uri': redirect}).encode(),
            headers={'Authorization': 'Basic ' + base64.b64encode(f'{cid}:{sec}'.encode()).decode(),
                     'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))['access_token']
        except urllib.error.HTTPError as e:
            err = f'HTTP {e.code} {e.read()[:300]!r}'
    raise RuntimeError('Yahoo sign-in failed (check the three secrets): ' + err)


TOKEN = None


def get(path):
    """GET an API path and return the XML root with namespaces stripped."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(API + path, headers={'Authorization': f'Bearer {TOKEN}'})
            raw = urllib.request.urlopen(req, timeout=30).read()
            root = ET.fromstring(raw)
            for el in root.iter():
                if '}' in el.tag:
                    el.tag = el.tag.split('}', 1)[1]
            return root
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise RuntimeError(f'{path}: HTTP {e.code} {e.read()[:300]!r}')


def txt(el, path, default=''):
    x = el.find(path)
    return x.text.strip() if x is not None and x.text else default


def num(el, path):
    try:
        return round(float(txt(el, path, '0')), 2)
    except ValueError:
        return 0.0


def team_id(key):
    return int(key.rsplit('.', 1)[1])


def player_name(p):
    """Match the Yahoo website's style: 'Ravens' for defenses, full name otherwise."""
    if txt(p, 'display_position') == 'DEF' or txt(p, 'position_type') == 'DT':
        full = txt(p, 'editorial_team_full_name') or txt(p, 'name/full')
        return full.split()[-1]
    return txt(p, 'name/full')


def player_label(p):
    return f"{player_name(p)} ({txt(p, 'editorial_team_abbr')} {txt(p, 'display_position')})"


def main():
    global TOKEN
    TOKEN = token()
    old = json.load(open('data.json'))

    lg = get(f'league/{LEAGUE}/settings').find('league')
    cur = int(txt(lg, 'current_week', '1'))
    league = dict(old.get('league', {}))
    league.update({'id': LID, 'url': f'https://football.fantasysports.yahoo.com/f1/{LID}'})
    st = lg.find('settings')
    if st is not None:
        if txt(st, 'num_playoff_teams'):
            league['playoffTeams'] = int(txt(st, 'num_playoff_teams'))
        if txt(st, 'playoff_start_week'):
            ps = int(txt(st, 'playoff_start_week'))
            league['regWeeks'] = ps - 1
            league['playoffWeeks'] = list(range(ps, int(txt(lg, 'end_week', '17')) + 1))
        ted = txt(st, 'trade_end_date')
        if ted:
            d = datetime.strptime(ted, '%Y-%m-%d')
            league['tradeDeadline'] = f"{d:%b} {d.day}, {d.year}"

    # teams (keep the hand-picked manager names already in data.json)
    teams = {}
    for t in get(f'league/{LEAGUE}/teams').iter('team'):
        tid = txt(t, 'team_id')
        nick = txt(t, 'managers/manager/nickname', 'Manager').split(' ')[0]
        teams[tid] = {
            'name': txt(t, 'name'),
            'mgr': old.get('teams', {}).get(tid, {}).get('mgr') or nick[:1].upper() + nick[1:],
            'faab': int(float(txt(t, 'faab_balance', '0'))),
            'moves': int(txt(t, 'number_of_moves', '0')),
        }

    # weekly scoreboards
    weeks = {}
    for w in range(1, int(txt(lg, 'end_week', '17')) + 1):
        games, final = [], True
        for m in get(f'league/{LEAGUE}/scoreboard;week={w}').iter('matchup'):
            ts = m.findall('teams/team')
            if len(ts) != 2:
                continue
            if txt(m, 'status') != 'postevent':
                final = False
            a, b = ts
            games.append([int(txt(a, 'team_id')), int(txt(b, 'team_id')),
                          num(a, 'team_points/total'), num(b, 'team_points/total'),
                          num(a, 'team_projected_points/total'), num(b, 'team_projected_points/total')])
        if games:
            weeks[str(w)] = {'final': final, 'games': games}

    # transactions (full season)
    txs, trades = [], []
    try:
        tx_root = get(f'league/{LEAGUE}/transactions;count=1000')
    except RuntimeError:
        tx_root = get(f'league/{LEAGUE}/transactions')
    for tx in tx_root.iter('transaction'):
        typ, status = txt(tx, 'type'), txt(tx, 'status')
        if status != 'successful' or typ not in ('add', 'drop', 'add/drop', 'trade'):
            continue
        when = datetime.fromtimestamp(int(txt(tx, 'timestamp', '0')), timezone.utc).astimezone(TZ)
        ts = f"{when:%b} {when.day}, {when.hour % 12 or 12}:{when:%M} {'am' if when.hour < 12 else 'pm'}"
        players = tx.findall('players/player')
        if typ == 'trade':
            legs = {}
            for p in players:
                to = team_id(txt(p, 'transaction_data/destination_team_key'))
                legs.setdefault(to, []).append(player_label(p))
            o = {'type': 'trade', 'ts': ts, 'legs': [{'to': k, 'players': v} for k, v in legs.items()]}
            txs.append(o); trades.append({'ts': ts, 'legs': o['legs']})
            continue
        o = {'type': typ, 'ts': ts}
        for p in players:
            td = p.find('transaction_data')
            if txt(td, 'type') == 'add':
                o['team'] = team_id(txt(td, 'destination_team_key'))
                o['add'] = player_label(p)
                src = txt(td, 'source_type')
                o['addHow'] = (f"${txt(tx, 'faab_bid', '0')} Waiver" if src == 'waivers' else 'Free Agent')
            else:
                o.setdefault('team', team_id(txt(td, 'source_team_key')))
                o['drop'] = player_label(p)
        txs.append(o)
    # keep any older moves the API didn't return
    if len(txs) < len(old.get('transactions', [])):
        seen = {json.dumps(x, sort_keys=True) for x in txs}
        txs += [x for x in old['transactions'] if json.dumps(x, sort_keys=True) not in seen
                and x['ts'] not in {y['ts'] for y in txs}]

    # rosters: [name, pos, slot, seasonPts, last4WeeksPts, injury, bye] with current lineup slots
    def roster(tid, stat):
        out = {}
        for p in get(f'team/{LEAGUE}.t.{tid}/roster/players/stats;type={stat}').iter('player'):
            bye = txt(p, 'bye_weeks/week', '0')
            out[player_name(p)] = [player_name(p), txt(p, 'display_position'),
                                   txt(p, 'selected_position/position'),
                                   num(p, 'player_points/total'), txt(p, 'status'),
                                   int(bye) if bye.isdigit() else 0]
        return out
    rosters = {}
    for tid in teams:
        s, l4 = roster(tid, 'season'), roster(tid, 'lastmonth')
        rosters[tid] = [[r[0], r[1], r[2], r[3], l4.get(n, [0] * 4)[3], r[4], r[5]] for n, r in s.items()]

    new = {'league': league, 'updated': datetime.now(TZ).isoformat(timespec='seconds'),
           'currentWeek': cur, 'teams': teams, 'weeks': weeks,
           'transactions': txs, 'rosters': rosters, 'trades': trades}

    # sanity checks before touching data.json
    assert len(teams) == 10, f'expected 10 teams, got {len(teams)}'
    for w in range(1, league.get('regWeeks', 14) + 1):
        assert str(w) in weeks, f'week {w} missing'
    for w in weeks.values():
        for g in w['games']:
            assert len(g) == 6 and all(isinstance(x, (int, float)) for x in g), g
    assert len(rosters) == 10 and all(len(r) >= 9 for r in rosters.values()), 'rosters look incomplete'
    assert len(txs) >= len(old.get('transactions', [])) * 0.9, 'lost transactions'

    strip = lambda d: {k: v for k, v in d.items() if k != 'updated'}
    if strip(new) == strip(old):
        print('No changes.'); return
    with open('data.json', 'w') as f:
        json.dump(new, f, ensure_ascii=False, separators=(',', ':'))
    print(f'Updated: week {cur}, {sum(w["final"] for w in weeks.values())} final weeks, {len(txs)} transactions')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        # Yahoo hasn't approved this app for the Fantasy API yet: skip quietly instead of
        # failing every hour. It starts working by itself once access is granted.
        if 'not authorized to perform this action' in str(e):
            print('Yahoo Fantasy API access not approved yet; skipping this run.'); sys.exit(0)
        raise
