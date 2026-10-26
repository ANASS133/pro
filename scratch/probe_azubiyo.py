import requests
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

r = requests.get('https://www.azubiyo.de/bundles5/bundlejs.js', headers=headers, timeout=10)
print('bundlejs length:', len(r.text))

# Search for angular or ajax search calls
matches = re.findall(r'(?:get|post)\([\'"`]([^\'"`]+)[\'"`]', r.text)
print('HTTP calls found:', len(matches))
for m in matches[:30]:
    if any(k in m for k in ['api', 'stelle', 'search', 'job', 'offer']):
        print(' Match:', m)

# Also search for 'JobOffer' or 'Stellenmarkt' or 'what' or 'where'
for line in r.text.split(';'):
    if 'joboffer' in line.lower() and ('http' in line.lower() or 'url' in line.lower() or 'api' in line.lower()):
        print('JobOffer line snippet:', line[:200])
        break
