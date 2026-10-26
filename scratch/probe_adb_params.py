import requests
import bs4
import json
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
}

r = requests.get('https://www.ausbildung.de/suche/?search=Fachinformatiker', headers=headers, timeout=10)
soup = bs4.BeautifulSoup(r.text, 'html.parser')

scripts = soup.find_all('script')
for s in scripts:
    text = s.string or s.text or ''
    if 'search' in text and ('url' in text or 'param' in text or 'query' in text or 'router' in text):
        print('Found script with search:', text[:250])
        break
