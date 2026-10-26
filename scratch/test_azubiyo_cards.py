import requests
import bs4
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

r = requests.get('https://www.azubiyo.de/ausbildung/berlin/', headers=headers, timeout=10)
soup = bs4.BeautifulSoup(r.text, 'html.parser')

# Check JSON-LD
for s in soup.find_all('script', type='application/ld+json'):
    try:
        data = json.loads(s.string)
        if isinstance(data, dict) and data.get('@type') == 'ItemList':
            print('Found ItemList JSON-LD with items:', len(data.get('itemListElement', [])))
            for item in data.get('itemListElement', [])[:3]:
                print(' Item:', item)
    except Exception as e:
        pass

# Check HTML cards
cards = soup.find_all('div', class_=lambda c: c and 'job-offer-teaser' in c)
print('Total HTML cards on page:', len(cards))
for c in cards[:3]:
    title_el = c.find('span', class_=lambda cl: cl and 'h3' in cl)
    title = title_el.get_text(strip=True) if title_el else 'N/A'
    comp_el = c.find('span', class_=lambda cl: cl and 'text-secondary' in cl)
    company = comp_el.get_text(strip=True) if comp_el else 'N/A'
    link_el = c.find('a', href=True)
    href = link_el['href'] if link_el else 'N/A'
    ul = c.find('ul')
    lis = [li.get_text(' ', strip=True) for li in ul.find_all('li')] if ul else []
    print(f'Card: {title} | Company: {company} | Details: {lis} | URL: {href}')
