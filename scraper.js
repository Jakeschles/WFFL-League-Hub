// WFFL scraper — run in a tab on football.fantasysports.yahoo.com while signed in.
// Returns the complete data.json content as a compact JSON string.
(async () => {
  const LID = 68635;
  const P = new DOMParser();
  const get = async u => P.parseFromString(await (await fetch(u, {credentials: 'include'})).text(), 'text/html');
  const teamId = a => +((a && a.getAttribute('href') || '').match(new RegExp(LID + '/(\\d+)')) || [])[1];
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = {
    league: {id: LID, name: 'WFFL', playoffTeams: 6, byes: 2, regWeeks: 14, playoffWeeks: [15, 16, 17], tradeDeadline: 'Nov 28, 2026', url: 'https://football.fantasysports.yahoo.com/f1/' + LID},
    updated: new Date().toISOString(), teams: {}, weeks: {}, transactions: []
  };
  // teams: name, manager first name, FAAB, moves
  const td = await get(`/f1/${LID}/teams`);
  td.querySelectorAll('table tbody tr').forEach(r => {
    const id = teamId(r.querySelector(`a[href*="/f1/${LID}/"]`)); if (!id) return;
    const c = [...r.children].map(x => clean(x.innerText));
    out.teams[id] = {name: c[0], mgr: (m => m.charAt(0).toUpperCase() + m.slice(1))(c[1].replace(/Commissioner$/, '').split(' ')[0]), faab: +c[3].replace(/[^0-9.]/g, ''), moves: +c[5]};
  });
  const MGR_OVERRIDE = {3: 'Charlie S.', 9: 'Charlie K.'};
  for (const k in MGR_OVERRIDE) if (out.teams[k]) out.teams[k].mgr = MGR_OVERRIDE[k];
  // weekly scoreboards 1-17
  for (let w = 1; w <= 17; w++) {
    const d = await get(`/f1/${LID}?matchup_week=${w}&module=matchups&lhst=matchups`);
    const status = clean(d.querySelector('#matchupweek .Submod .Ta-end')?.innerText);
    const games = [];
    d.querySelectorAll('#matchupweek li.Linkable').forEach(li => {
      const u = new URLSearchParams((li.getAttribute('data-target') || '').split('?')[1]);
      const sides = [...li.querySelectorAll('.Grid-u-6-13')];
      const nums = sides.map(s => [...s.querySelectorAll('.Grid-u-1-4 div div')].map(x => parseFloat(x.innerText) || 0));
      const ids = sides.map(s => teamId(s.querySelector('a.F-link')) || 0);
      games.push([ids[0] || +u.get('mid1'), ids[1] || +u.get('mid2'), nums[0][0], nums[1][0], nums[0][1], nums[1][1]]);
    });
    if (games.length) out.weeks[w] = {final: /final/i.test(status), status, games};
  }
  // transactions (latest 20)
  const tx = await get(`/f1/${LID}/transactions`);
  let cur = null;
  const pl = el => { const a = el.querySelector('a'); const pos = clean(el.querySelector('.F-position')?.innerText).replace(' - ', ' '); return `${clean(a?.innerText)} (${pos})`; };
  for (const r of tx.querySelectorAll('table tbody tr')) {
    const ts = clean(r.querySelector('.F-timestamp')?.innerText);
    const tm = teamId(r.querySelector('td.Ta-end a[href*="/f1/"]'));
    if (r.querySelector('.F-trade') || /Traded to/.test(r.innerText)) {
      if (r.querySelector('.F-trade')) { cur = {type: 'trade', ts, legs: []}; out.transactions.push(cur); }
      if (cur) cur.legs.push({to: tm, players: [...r.querySelectorAll('td p')].map(pl)});
      continue;
    }
    const icons = [...r.querySelectorAll('td:first-child .F-icon')].map(s => s.title);
    const divs = [...r.querySelectorAll('td.Fill-x > div')];
    const o = {type: icons.length > 1 ? 'add/drop' : /Added/.test(icons[0]) ? 'add' : 'drop', ts, team: tm};
    divs.forEach(dv => { const how = clean(dv.querySelector('h6')?.innerText); if (/^To /.test(how)) o.drop = pl(dv); else { o.add = pl(dv); o.addHow = how.replace(/\s+/g, ' '); } });
    out.transactions.push(o);
  }
  out.transactions = out.transactions.filter(x => x.ts).slice(0, 20);
  // full trade history
  const td2 = await get(`/f1/${LID}/transactions?transactionsfilter=trade`);
  out.trades = []; let ct = null;
  for (const r of td2.querySelectorAll('table tbody tr')) {
    if (!/Traded to/.test(r.innerText)) continue;
    const ts = clean(r.querySelector('.F-timestamp')?.innerText);
    const tm = teamId(r.querySelector('td.Ta-end a[href*="/f1/"]'));
    if (r.querySelector('.F-trade')) { ct = {ts, legs: []}; out.trades.push(ct); }
    if (ct) ct.legs.push({to: tm, players: [...r.querySelectorAll('td p')].map(pl)});
  }
  // rosters: [name, pos, slot, seasonPts, last4WeeksPts, injury, bye]
  const roster = async (id, stat2) => {
    const d = await get(`/f1/${LID}/${id}?stat1=S&stat2=${stat2}`); const rows = [];
    ['statTable0', 'statTable1', 'statTable2'].forEach(tid => {
      const t = d.querySelector('#' + tid); if (!t) return;
      t.querySelectorAll('tbody tr').forEach(r => {
        const a = r.querySelector('td.player a.name, .ysf-player-name a'); if (!a) return;
        const m = clean(a.closest('td').innerText).match(/\b([A-Za-z]{2,3}) - ([A-Z,]+)/);
        const ptsC = r.querySelector('td.pts');
        rows.push([clean(a.innerText), m ? m[2] : '', clean(r.querySelector('td.pos')?.innerText), parseFloat(clean(ptsC?.innerText)) || 0, clean(r.querySelector('.F-injury')?.innerText), +clean(ptsC?.previousElementSibling?.innerText) || 0]);
      });
    });
    return rows;
  };
  out.rosters = {};
  for (const id of Object.keys(out.teams)) {
    const s = await roster(id, 'S_2026'), l = await roster(id, 'L4W');
    const lm = Object.fromEntries(l.map(x => [x[0], x[3]]));
    out.rosters[id] = s.map(x => [x[0], x[1], x[2], x[3], lm[x[0]] ?? 0, x[4], x[5]]);
  }
  return JSON.stringify(out);
})()
