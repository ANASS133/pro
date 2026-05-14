import os

base = r'C:\Users\provincesettat\Desktop\pro-main'

replacements = {}

# app.py - additional patterns
replacements['app.py'] = [
    ('Datensaetze', 'Datensätze'),
    ('enthaelt', 'enthält'),
]

# pdf_generator/frontend/script.js - missed 'gueltig'
replacements['pdf_generator/frontend/script.js'] = [
    ('gueltig', 'gültig'),
]

# static/dashboard_firebase.js - missed 'loeschen' and 'geloescht'
replacements['static/dashboard_firebase.js'] = [
    ('loeschen', 'löschen'),
    ('geloescht', 'gelöscht'),
]

# static/spa/sections/dashboard.js - missed 'loeschen' and 'geloescht'
replacements['static/spa/sections/dashboard.js'] = [
    ('loeschen', 'löschen'),
    ('geloescht', 'gelöscht'),
]

# static/spa/sections/firebase.js - missed 'loeschen' and 'geloescht'
replacements['static/spa/sections/firebase.js'] = [
    ('loeschen', 'löschen'),
    ('geloescht', 'gelöscht'),
]

# static/spa/sections/send-emails.js - missed 'geloescht'
replacements['static/spa/sections/send-emails.js'] = [
    ('geloescht', 'gelöscht'),
]

# static/spa/sections/supabase.js - missed 'geloescht'
replacements['static/spa/sections/supabase.js'] = [
    ('geloescht', 'gelöscht'),
]

files_changed = 0

for rel_path, subs in replacements.items():
    filepath = os.path.join(base, rel_path)
    if not os.path.exists(filepath):
        print(f'MISSING: {rel_path}')
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    changed = content
    for old, new in subs:
        if old in changed:
            changed = changed.replace(old, new)

    if changed != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(changed)
        count = sum(1 for old, _ in subs if old in content)
        files_changed += 1
        print(f'OK: {rel_path} ({count} patterns)')
    else:
        print(f'SKIP: {rel_path} (no changes)')

print(f'\nTotal files modified: {files_changed}')
