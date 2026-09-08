"""Recompute Jack Adams best_avail/best_avail_book/edge in coaches_2026-27.json
from the current odds.json — the true longest price across every book that
posts jack_adams (not just FanDuel), matching how the Comp Tool picks a best
price. Re-run whenever odds.json changes (wired into run_all.ps1), so a new
book posting the market (e.g. Kambi) is picked up automatically instead of
leaving stale best_avail values until someone remembers to re-run this by hand.
"""
import json

with open('data/odds.json', encoding='utf-8') as f:
    odds = json.load(f)

with open('coaches_2026-27.json', encoding='utf-8') as f:
    coaches = json.load(f)

ja = odds.get('awards', {}).get('jack_adams', {})

changed = 0
for coach in coaches:
    name = coach['coach']
    prices = ja.get(name, {}).get('prices', {})
    if not prices:
        continue

    best_book = max(prices, key=lambda b: prices[b])
    best_price = prices[best_book]

    implied_pct = 10000 / (best_price + 100)
    edge = round(coach['model_pct'] - implied_pct, 1)

    old_avail, old_book = coach.get('best_avail'), coach.get('best_avail_book')
    if old_avail != best_price or old_book != best_book:
        print(f"  {name}: {old_avail} ({old_book}) -> {best_price} ({best_book})")
        changed += 1

    coach['best_avail'] = best_price
    coach['best_avail_book'] = best_book
    coach['edge'] = edge

print(f"  {changed} coach(es) changed best-available book/price" if changed
      else "  no best-available changes")

with open('coaches_2026-27.json', 'w', encoding='utf-8') as f:
    json.dump(coaches, f)
