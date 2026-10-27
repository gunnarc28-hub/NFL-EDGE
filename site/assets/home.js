/* Sports Edge home: a card per sport from each sport's summary.json, live scores while games are on, and the shared bets. */
(function(){
'use strict';
const {$, $$, esc, fmtOdds, pct, sign, unitsTxt, kick, ago, dayKey, toast, liveTxt, SPORTS} = SE;
const store = SE.mkStore('sportsedge.');
const ORDER = ['nfl', 'nba', 'nhl'];
const SUM = {};
/* ESPN uses a few different abbreviations from the builds */
const ALIAS = {nfl: {WSH: 'WAS', LAR: 'LA', JAC: 'JAX'}, nba: {GS: 'GSW', NY: 'NYK', SA: 'SAS', NO: 'NOP', UTAH: 'UTA', WSH: 'WAS', PHO: 'PHX'}, nhl: {NJ: 'NJD', SJ: 'SJS', TB: 'TBL', LA: 'LAK', UTAH: 'UTA', WSH: 'WSH'}};

function cardHtml(sp){
  const S = SUM[sp], C = SPORTS[sp];
  if (!S) return `<article class="sc sc-${sp}"><a class="sc-top" href="${C.path}"><div><div class="sc-k">${esc(C.name)}</div><div class="sc-n">${C.label}</div><div class="sc-s">Loading…</div></div><span class="sc-go">Open →</span></a><div class="sc-body"><div class="sc-empty">Getting the latest numbers.</div></div></article>`;
  if (S.error) return `<article class="sc sc-${sp}"><a class="sc-top" href="${C.path}"><div><div class="sc-k">${esc(C.name)}</div><div class="sc-n">${C.label}</div><div class="sc-s">Couldn't load the summary</div></div><span class="sc-go">Open →</span></a><div class="sc-body"><div class="sc-empty">Open the ${C.label} page for everything, or reload in a minute.</div></div></article>`;
  const gs = (S.games || []).slice().sort((a, b) => (a.st === 'in' ? -1 : 0) - (b.st === 'in' ? -1 : 0) || (a.st === 'post') - (b.st === 'post') || String(a.k).localeCompare(String(b.k)));
  const live = gs.filter(g => g.st === 'in').length, left = gs.filter(g => g.st === 'pre').length;
  const sub = gs.length ? `${esc(S.period)} · ${gs.length} game${gs.length === 1 ? '' : 's'}${live ? ` · <b style="color:#fff">${live} live</b>` : left ? ` · ${left} to go` : ' · all final'}` : S.next ? `Next game ${esc(kick(S.next.k, {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: undefined}))}` : esc(S.off || 'No games scheduled');
  const shown = gs.slice(0, 5);
  const gameRow = g => {
    const st = g.st === 'in' ? `<span class="lv">${esc(liveTxt(g.det))}</span> · <b>${g.as}–${g.hs}</b>` : g.st === 'post' ? `Final · <b>${g.as}–${g.hs}</b>` : `${esc(kick(g.k, {weekday: dayKey(g.k) === dayKey(new Date().toISOString()) ? undefined : 'short', hour: 'numeric', minute: '2-digit', timeZoneName: undefined}))}${g.line ? ` · <b>${esc(g.line)}</b>` : ''}`;
    return `<a class="sc-g" href="${C.path}#g-${encodeURIComponent(g.id)}" data-sg="${sp}|${esc(g.id)}"><span class="mu">${esc(g.a)} <span class="small">@</span> ${esc(g.h)}${g.pick ? ` <span class="pill stripe" title="Model's pick to win">${esc(g.pick)}</span>` : ''}</span><span class="st">${st}</span></a>`;
  };
  const picks = (S.picks || []).slice(0, 4).map(p => `<a class="sc-p" href="${C.path}#${esc(p.view || 'hc')}"><span class="tag ${esc(p.tag)}">${esc(({hc: 'High-chance', ls: 'Long shot', md: 'Model'})[p.tag] || p.tag)}</span>
      <span class="d">${esc(p.t)}<small>${esc(p.s || '')}</small></span><span class="v num">${esc(p.v || '')}</span></a>`).join('');
  const links = (S.links || [['week', 'Games'], ['props', 'Props'], ['hc', 'High-chance'], ['ls', 'Long shots'], ['trends', 'Trends']]).map(([v, l]) => `<a href="${C.path}#${v}">${esc(l)}</a>`).join('');
  return `<article class="sc sc-${sp}">
    <a class="sc-top" href="${C.path}"><div><div class="sc-k">${esc(C.name)}${S.season ? ' · ' + esc(S.season) : ''}</div><div class="sc-n">${C.label}</div><div class="sc-s">${sub}</div></div><span class="sc-go">Open →</span></a>
    <div class="sc-body">
      ${shown.length ? `<div class="sc-games">${shown.map(gameRow).join('')}</div>${gs.length > shown.length ? `<a class="small" href="${C.path}">+ ${gs.length - shown.length} more</a>` : ''}` : `<div class="sc-empty">${esc(S.note || 'No games on the slate right now.')}</div>`}
      ${picks ? `<div class="sc-h">Top picks</div><div class="sc-picks">${picks}</div>` : ''}
      ${S.record ? `<div class="small">${esc(S.record)}</div>` : ''}
    </div>
    <div class="sc-foot">${links}</div>
  </article>`;
}
function renderCards(){ $('#cards').innerHTML = ORDER.map(cardHtml).join(''); renderStamp(); }
function renderStamp(){
  const ts = ORDER.map(s => SUM[s] && SUM[s].asof).filter(Boolean).sort();
  const t = ts.length ? ts[ts.length - 1] : null;
  $('#m-asof').innerHTML = t ? `Updated <strong>${ago(t)}</strong>` : '';
  $('#m-asof2').innerHTML = t ? `Updated ${ago(t)}` : '';
}

/* ---------- your bets, in brief ---------- */
function homeBets(){
  const box = $('#home-bets'); if (!box) return;
  const s = SB.summary(), bets = SB.bets();
  if (!bets.length && !SB.slip().legs.length){ box.innerHTML = ''; return; }
  const open = bets.filter(b => !b._g.r).sort((a, b) => String(b.created).localeCompare(String(a.created))).slice(0, 6);
  const rows = open.map(b => {
    const sp = [...new Set(b.legs.map(l => l.sport))];
    const t = b.type === 'single' ? SB.legLabel(b.legs[0]) : `${b.legs.length}-leg ${b.type}`;
    const sub = b.type === 'single' ? (b.legs[0].sub || '') : b.legs.map(l => SB.legLabel(l)).join(' · ');
    const done = b._g.legs.filter(x => x.r === 'W').length;
    return `<div class="pk"><span>${sp.map(SB.sportTag).join('')}</span><div style="min-width:0"><div class="d">${esc(t)} <span class="small num">${fmtOdds(Number(b.odds))}</span></div><div class="m">${esc(sub)}${b.type !== 'single' && done ? ` · ${done} of ${b.legs.length} legs won` : ''}</div></div><div class="small num">${unitsTxt(Number(b.stake) || 1)} to win ${unitsTxt((Number(b.stake) || 1) * (SE.dec(b.odds) - 1))}</div></div>`;
  }).join('');
  box.innerHTML = `<div class="sec-head"><div><h2 class="h2">Your bets</h2><p class="lede">Every sport in one place. Each leg grades itself when its game ends.</p></div>
      <div class="filters"><button class="btn" data-hgo="picks">See all bets</button>${SB.slip().legs.length ? `<button class="btn stripe" data-slipopen="">Bet slip (${SB.slip().legs.length})</button>` : ''}</div></div>
    <div class="tiles">
      <div class="tile"><div class="label">Open</div><div class="v num">${s.open}</div><div class="small">${s.open ? unitsTxt(s.openRisk) + ' at risk' : 'No open bets'}</div></div>
      <div class="tile"><div class="label">Record</div><div class="v num">${s.W}-${s.L}${s.P ? '-' + s.P : ''}</div><div class="small">${s.pct == null ? 'Settled bets' : pct(s.pct, 1) + ' of settled bets'}</div></div>
      <div class="tile"><div class="label">Units</div><div class="v num ${s.units > 0 ? 'pos' : s.units < 0 ? 'neg' : ''}">${sign(s.units, 2)}</div><div class="small">ROI ${s.roi == null ? '–' : pct(s.roi, 1)}</div></div>
    </div>
    ${rows ? `<div class="trend-list">${rows}</div>` : ''}`;
}

/* ---------- tabs ---------- */
function show(view){
  $$('.tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === view)));
  $$('.view').forEach(v => v.hidden = v.id !== 'v-' + view);
  if (view === 'picks') SB.renderBets(); else homeBets();
  history.replaceState(null, '', view === 'home' ? location.pathname : '#' + view);
  window.scrollTo({top: 0});
}
document.addEventListener('click', e => {
  const t = e.target.closest('.tab, [data-hgo]'); if (!t) return;
  show(t.dataset.view || t.dataset.hgo);
});

/* ---------- live scores while games are on ---------- */
let liveTimer = null;
async function liveScores(){
  let anyLive = false, changed = false;
  await Promise.all(ORDER.map(async sp => {
    const S = SUM[sp]; if (!S || !S.espn || !(S.games || []).some(g => g.st !== 'post' && new Date(g.k).getTime() < Date.now() + 15 * 60000)) return;
    try {
      const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), 7000);
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${S.espn}/scoreboard`, {signal: ctl.signal, cache: 'no-store'});
      clearTimeout(tm); if (!r.ok) return;
      const j = await r.json(), al = ALIAS[sp] || {};
      (j.events || []).forEach(ev => {
        const comp = (ev.competitions || [])[0]; if (!comp) return;
        const cs = comp.competitors || [], h = cs.find(c => c.homeAway === 'home'), a = cs.find(c => c.homeAway === 'away'); if (!h || !a) return;
        const ab = c => { const x = (c.team || {}).abbreviation || ''; return al[x] || x; };
        const g = S.games.find(x => (x.eid && String(x.eid) === String(ev.id)) || (x.h === ab(h) && x.a === ab(a) && Math.abs(new Date(x.k) - new Date(ev.date)) < 18 * 3600e3));
        if (!g) return;
        const st = ((comp.status || ev.status || {}).type) || {}, hs = parseInt(h.score, 10), as = parseInt(a.score, 10);
        if (st.state === 'in'){ anyLive = true; if (g.st !== 'in' || g.hs !== hs || g.as !== as || g.det !== (st.shortDetail || '')){ Object.assign(g, {st: 'in', hs, as, det: st.shortDetail || 'Live'}); changed = true; } }
        else if (st.state === 'post' && g.st !== 'post' && !isNaN(hs)){ Object.assign(g, {st: 'post', hs, as, det: 'Final'}); changed = true; }
      });
    } catch(e){ /* the summary still shows */ }
  }));
  if (changed && !$('#v-home').hidden) renderCards();
  clearTimeout(liveTimer);
  if (anyLive) liveTimer = setTimeout(() => { if (!document.hidden) liveScores(); }, 60000);
}

async function loadSummaries(){
  await Promise.all(ORDER.map(async sp => {
    try {
      const r = await fetch(`${SPORTS[sp].path}data/summary.json?t=${Date.now()}`, {cache: 'no-store'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      SUM[sp] = await r.json();
    } catch(e){ SUM[sp] = {error: true}; }
    renderCards();
  }));
  liveScores();
}

SB.init({sport: null, root: '', betsEl: '#v-picks', countEl: '#pick-count', onChange: () => { if (!$('#v-home').hidden) homeBets(); }, onGrade: () => { if (!$('#v-home').hidden) homeBets(); }});
renderCards();
loadSummaries();
const h = location.hash.replace('#', '');
if (h === 'picks' || h === 'bets') show('picks'); else homeBets();
setInterval(renderStamp, 60000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) liveScores(); });
})();
