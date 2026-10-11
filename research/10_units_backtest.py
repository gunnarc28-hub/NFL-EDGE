"""Units replay: how many units each pick list would have won or lost, graded at real prices wherever they exist.

Model (2020-2025, every game predicted only from earlier seasons):
  spread   - picks where the model and the closing line disagree by 2.5+ points, at -110
  ml       - the model's winner in every game, at the closing moneyline
  value    - moneyline bets where the model's win chance beats the no-vig market by 5+ points, at the closing moneyline
High-chance (2024-2025, the seasons the milestone chances were tested on):
  player   - the 12 likeliest milestones a week (3 a game at most), at the card's fair price (no sportsbook prices exist for these)
  teaser   - +1.5 to +2.5 underdogs teased six points, each leg at -282: two legs at that price make a 2-team teaser at -120
  ml       - favorites that both the model and the market give 75%+, at the closing moneyline
Long shots (2021-2025): every pick at the card's fair price, by market.

Fair-price lines get a 'cushion': how much less than the fair payout a book could pay before the picks stop breaking even.
Writes repo/pipeline/static/units_research.json. Needs work/model_wf.pkl (07), work/hc_replay.pkl (08), work/longshot_replay.pkl (09)."""
import json, math
import numpy as np, pandas as pd

SPREAD_WIN = 100 / 110
TEASE_LEG = math.sqrt(1 + 100 / 120) - 1          # 0.354 a leg; (1.354)^2 = 1.833 = a 2-team teaser at -120


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def am_prob(o):
    if o is None or pd.isna(o):
        return None
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def payout(o):
    o = float(o)
    return o / 100 if o > 0 else 100 / abs(o)


def grade(res, win_profit):
    """res > 0 win, < 0 loss, == 0 push"""
    return win_profit if res > 0 else (-1.0 if res < 0 else 0.0)


def summarize(b):
    w, l, p = int((b.profit > 0).sum()), int((b.profit < 0).sum()), int((b.profit == 0).sum())
    out = {'bets': int(len(b)), 'w': w, 'l': l, 'p': p, 'units': round(float(b.profit.sum()), 2),
           'roi': round(float(b.profit.sum() / len(b)), 4) if len(b) else None}
    if 'fair' in b.columns and b.fair.all():
        won = b[b.profit > 0].profit.sum()
        out['cushion'] = round(float(1 - l / won), 4) if won > 0 else None
        out['hit'] = round(w / len(b), 4) if len(b) else None
        out['rated'] = round(float(b.p.mean()), 4) if len(b) else None
    return out


def block(bets, keys, span):
    """Cumulative units by week for each strategy, on one shared season-week timeline."""
    tl = sorted({(int(s), int(w)) for s, w in zip(bets.season, bets.week)})
    idx = {k: i for i, k in enumerate(tl)}
    series, summary, by_season = {}, {}, {}
    for k in keys:
        b = bets[bets.strat == k]
        per = np.zeros(len(tl))
        for s, w, pr in zip(b.season, b.week, b.profit):
            per[idx[(int(s), int(w))]] += pr
        series[k] = [round(float(v), 2) for v in np.cumsum(per)]
        summary[k] = summarize(b)
        by_season[k] = [{'season': int(s), **summarize(x)} for s, x in b.groupby('season')]
    return {'span': span, 'timeline': [list(t) for t in tl], 'series': series, 'summary': summary, 'by_season': by_season}


# ---------------------------------------------------------------- model
wf = pd.read_pickle('work/model_wf.pkl')
wf = wf[(wf.season >= 2020) & wf.pred.notna() & (wf.week <= 18)].copy()
rows = []
for r in wf.itertuples():
    edge = r.pred - r.spread
    if abs(edge) >= 2.5:
        res = (r.margin - r.spread) * (1 if edge > 0 else -1)
        rows.append({'season': r.season, 'week': r.week, 'strat': 'spread', 'profit': grade(res, SPREAD_WIN)})
    if r.pred != 0:
        home = r.pred > 0
        o = r.home_moneyline if home else r.away_moneyline
        if pd.notna(o):
            rows.append({'season': r.season, 'week': r.week, 'strat': 'ml', 'profit': grade(r.margin * (1 if home else -1), payout(o))})
    ih, ia = am_prob(r.home_moneyline), am_prob(r.away_moneyline)
    if ih and ia:
        wp_h, nv_h = ncdf(r.pred / r.resid_sd), ih / (ih + ia)
        for home, gap, o in ((True, wp_h - nv_h, r.home_moneyline), (False, nv_h - wp_h, r.away_moneyline)):
            if gap >= 0.05:
                rows.append({'season': r.season, 'week': r.week, 'strat': 'value', 'profit': grade(r.margin * (1 if home else -1), payout(o))})
MB = pd.DataFrame(rows)
model = block(MB, ['spread', 'ml', 'value'], '2020–2025')

# ---------------------------------------------------------------- high-chance
pk = pd.read_pickle('work/hc_replay.pkl').sort_values('p', ascending=False)
pk = pk[pk.groupby(['season', 'week', 'game_id']).cumcount() < 3]
pk = pk[pk.groupby(['season', 'week']).cumcount() < 12]
rows = [{'season': r.season, 'week': r.week, 'strat': 'player', 'p': r.p, 'fair': True,
         'profit': (1 - r.p) / r.p if r.hit else -1.0} for r in pk.itertuples()]
sched = pd.read_csv('raw/games.csv', low_memory=False)
sc = sched[(sched.season.isin([2024, 2025])) & (sched.game_type == 'REG') & sched.result.notna() & sched.spread_line.notna()]
for r in sc.itertuples():
    for team_is_home, ln in ((True, -r.spread_line), (False, r.spread_line)):
        if 1.5 <= ln <= 2.5:
            mg = r.result if team_is_home else -r.result
            rows.append({'season': r.season, 'week': r.week, 'strat': 'teaser', 'profit': grade(mg + ln + 6, TEASE_LEG)})
for r in wf[wf.season.isin([2024, 2025])].itertuples():
    ih, ia = am_prob(r.home_moneyline), am_prob(r.away_moneyline)
    if not (ih and ia):
        continue
    wp_h, nv_h = ncdf(r.pred / r.resid_sd), ih / (ih + ia)
    for home, mp, kp, o in ((True, wp_h, nv_h, r.home_moneyline), (False, 1 - wp_h, 1 - nv_h, r.away_moneyline)):
        if mp >= 0.75 and kp >= 0.75:
            rows.append({'season': r.season, 'week': r.week, 'strat': 'ml', 'profit': grade(r.margin * (1 if home else -1), payout(o))})
HB = pd.DataFrame(rows)
HB['fair'] = HB.fair.fillna(False).astype(bool)
hc = block(HB, ['player', 'teaser', 'ml'], '2024–2025')

# ---------------------------------------------------------------- long shots
lr = pd.read_pickle('work/longshot_replay.pkl')
LB = pd.DataFrame({'season': lr.season, 'week': lr.week, 'strat': lr.market, 'p': lr.p, 'fair': True,
                   'profit': np.where(lr.hit == 1, (1 - lr.p) / lr.p, -1.0)})
LB = pd.concat([LB, LB.assign(strat='all')], ignore_index=True)
ls = block(LB, ['all', 'atd', 'ftd', 'td2', 'yds100', 'pass300'], '2021–2025')

out = {'model': model, 'hc': hc, 'ls': ls, 'tease_leg_price': round(-100 / TEASE_LEG)}
json.dump(out, open('repo/pipeline/static/units_research.json', 'w'), separators=(',', ':'))
for name, b in (('MODEL', model), ('HIGH-CHANCE', hc), ('LONG SHOTS', ls)):
    print(name, b['span'], len(b['timeline']), 'weeks')
    for k, v in b['summary'].items():
        print(f"  {k:8s} {v['bets']:5d} bets  {v['w']}-{v['l']}-{v['p']}  units {v['units']:+8.2f}  ROI {v['roi']:+.3f}"
              + (f"  hit {v['hit']:.3f} rated {v['rated']:.3f} cushion {v['cushion']:+.3f}" if 'cushion' in v else ''))
