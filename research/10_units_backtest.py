"""Units replay for the model: how many units following its picks would have won or lost, 2020-2025, graded at real prices.
Every game is predicted only from earlier seasons (walk-forward predictions saved by 07_spread_experiments.py).
  spread - picks where the model and the closing line disagree by 2.5+ points, at -110
  ml     - the model's winner in every game, at the closing moneyline
  value  - moneyline bets where the model's win chance beats the no-vig market by 5+ points, at the closing moneyline
Writes repo/pipeline/static/units_research.json. Needs work/model_wf.pkl (from 07)."""
import json, math
import numpy as np, pandas as pd

SPREAD_WIN = 100 / 110


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
    return {'bets': int(len(b)), 'w': w, 'l': l, 'p': p, 'units': round(float(b.profit.sum()), 2),
            'roi': round(float(b.profit.sum() / len(b)), 4) if len(b) else None}


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
model = block(pd.DataFrame(rows), ['spread', 'ml', 'value'], '2020–2025')
json.dump({'model': model}, open('repo/pipeline/static/units_research.json', 'w'), separators=(',', ':'))
print('MODEL', model['span'], len(model['timeline']), 'weeks')
for k, v in model['summary'].items():
    print(f"  {k:8s} {v['bets']:5d} bets  {v['w']}-{v['l']}-{v['p']}  units {v['units']:+8.2f}  ROI {v['roi']:+.3f}")
