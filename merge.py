"""Merge a freshly scraped data file into data.json, keeping the full transaction history.

Usage: python3 merge.py NEW.json
The scraper only sees Yahoo's most recent page of transactions, so this keeps every
older move already in data.json and adds any new ones on top (newest first).
"""
import json, sys

def key(x):
    if x.get('type') == 'trade':
        return json.dumps(['trade', x.get('ts'), x.get('legs')], sort_keys=True)
    return json.dumps([x.get('type'), x.get('ts'), x.get('team'), x.get('add', ''), x.get('drop', '')])

new = json.load(open(sys.argv[1]))
try:
    old = json.load(open('data.json'))
except FileNotFoundError:
    old = {}
hist = old.get('transactions', [])
seen = {key(x) for x in hist}
fresh = []
for x in new.get('transactions', []):
    k = key(x)
    if k not in seen:
        seen.add(k)
        fresh.append(x)
new['transactions'] = fresh + hist
with open('data.json', 'w') as f:
    json.dump(new, f, ensure_ascii=False, separators=(',', ':'))
print(f'{len(fresh)} new transaction(s); {len(new["transactions"])} total')
