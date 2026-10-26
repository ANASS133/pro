import requests
import bs4

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
}

queries = [
    'Ausbildung zum Fachinformatiker',
    'Fachinformatiker',
    'Fachinformatiker Anwendungsentwicklung',
    'Kaufmann im Einzelhandel',
]

for kw in queries:
    r = requests.get('https://www.ausbildung.de/suche/', params={'search': kw}, headers=headers, timeout=10)
    soup = bs4.BeautifulSoup(r.text, 'html.parser')
    cards = soup.find_all('article', attrs={'data-testid': 'jp-card'})
    print(f'=== search="{kw}" === (Found {len(cards)} cards)')
    for c in cards[:3]:
        t = c.find(attrs={'data-testid': 'jp-title'})
        title = t.get_text(strip=True) if t else 'N/A'
        co = c.find(attrs={'data-testid': 'jp-customer'})
        comp = co.get_text(strip=True) if co else 'N/A'
        print(' -', title, '|', comp)
