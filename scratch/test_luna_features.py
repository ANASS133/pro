import requests
import json
from pdf_generator.services.ats_service import _get_api_key

api_key = _get_api_key()
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

# Test 2: Culture & Vibe Radar
p2 = {
    'model': 'gpt-5.6-luna',
    'reasoning': {'effort': 'none'},
    'input': [
        {'role': 'developer', 'content': 'Antworte nur mit validem JSON ohne Markdown-Fences.'},
        {'role': 'user', 'content': 'Analysiere Unternehmenskultur für: BMW Group (Fachinformatiker Anwendungsentwicklung). Gib JSON mit: formality ("Sie" oder "Du"), vibe ("Konzern / Traditionell" oder "Mittelstand / Solide" oder "Modern Tech / Agil" oder "Startup / Locker"), icon, tone_tip (1 kurzer deutscher Satz).'}
    ],
    'max_output_tokens': 90,
    'store': False
}
r2 = requests.post('https://api.openai.com/v1/responses', headers=headers, json=p2).json()
txt2 = r2['output'][0]['content'][0]['text']
print('--- VIBE RADAR ---')
print(txt2)

# Test 3: Visual ATS Heatmap
p3 = {
    'model': 'gpt-5.6-luna',
    'reasoning': {'effort': 'none'},
    'input': [
        {'role': 'developer', 'content': 'Antworte nur mit validem JSON ohne Markdown-Fences.'},
        {'role': 'user', 'content': 'Bewerber Anass Sibbi (Python, React, Spring Boot, REST APIs, relationale DB) bewirbt sich bei Zalando (Fachinformatiker, Python, Docker, Cloud, Microservices). Gib JSON mit: match_percent (Zahl), matched (Array von 3 Skills), transferable (Array von 2 Skills), gaps (Array von 1-2 Skills), bridge_tip (1 kurzer deutscher Satz).'}
    ],
    'max_output_tokens': 160,
    'store': False
}
r3 = requests.post('https://api.openai.com/v1/responses', headers=headers, json=p3).json()
txt3 = r3['output'][0]['content'][0]['text']
print('--- ATS HEATMAP ---')
print(txt3)
