import requests
import bs4

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

slug_tests = [
    'https://www.azubiyo.de/ausbildung/koeln/fachinformatiker/',
    'https://www.azubiyo.de/ausbildung/koeln/fachinformatiker-anwendungsentwicklung/',
    'https://www.azubiyo.de/ausbildung/koeln/informatik/',
    'https://www.azubiyo.de/ausbildung/koeln/',
    'https://www.azubiyo.de/ausbildung/fachinformatiker/',
    'https://www.azubiyo.de/ausbildung/e-commerce/',
    'https://www.azubiyo.de/ausbildung/kaufmann-e-commerce/',
    'https://www.azubiyo.de/ausbildung/hamburg/kaufmann-e-commerce/'
]

for url in slug_tests:
    r = requests.get(url, headers=headers, timeout=10)
    print(f'{url} -> status={r.status_code}, final={r.url}')
    if r.status_code == 200:
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
        cards = soup.find_all('div', class_=lambda c: c and 'job-offer-teaser' in c)
        print(f'   Cards: {len(cards)}')
