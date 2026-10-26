import os

base = r'C:\Users\provincesettat\Desktop\pro-main'

replacements = {}

# app.py
replacements['app.py'] = [
    ('waehrend', 'während'),
    ('geloescht', 'gelöscht'),
    ('Empfaenger', 'Empfänger'),
    ('verfuegbar', 'verfügbar'),
    ('uebergeben', 'übergeben'),
    ('ungueltiger', 'ungültiger'),
    ('Ungueltige', 'Ungültige'),
    ('gueltigen', 'gültigen'),
    ('gueltiger', 'gültiger'),
    (' fuer ', ' für '),
    ('Fuer ', 'Für '),
]

# pdf_generator/frontend/script.js
replacements['pdf_generator/frontend/script.js'] = [
    ('uebersprungen', 'übersprungen'),
    (' fuer ', ' für '),
    ('Empfaenger', 'Empfänger'),
]

# templates/index.html
replacements['templates/index.html'] = [
    (' fuer ', ' für '),
]

# templates/extraction_progress.html
replacements['templates/extraction_progress.html'] = [
    ('oeffnen', 'öffnen'),
]

# templates/results.html
replacements['templates/results.html'] = [
    ('benoetigt', 'benötigt'),
]

# templates/dashboard.html
replacements['templates/dashboard.html'] = [
    ('abschliessen', 'abschließen'),
    ('Loeschen', 'Löschen'),
    ('waehrend', 'während'),
    (' fuer ', ' für '),
    ('verfuegbar', 'verfügbar'),
]

# templates/app_shell.html
replacements['templates/app_shell.html'] = [
    (' ueber ', ' über '),
    ('Verfuegbare', 'Verfügbare'),
    (' fuer ', ' für '),
    ('einfuegen', 'einfügen'),
    ('loeschen', 'löschen'),
]

# templates/send_emails.html
replacements['templates/send_emails.html'] = [
    ('abschliessen', 'abschließen'),
    ('loeschen', 'löschen'),
    ('Loeschen', 'Löschen'),
    ('waehrend', 'während'),
    ('rueckgaengig', 'rückgängig'),
]

# static/dashboard_firebase.js
replacements['static/dashboard_firebase.js'] = [
    ('Loeschen', 'Löschen'),
    ('rueckgaengig', 'rückgängig'),
]

# static/spa/sections/create-anschreibens.js
replacements['static/spa/sections/create-anschreibens.js'] = [
    ('gueltig', 'gültig'),
    ('uebersprungen', 'übersprungen'),
    (' fuer ', ' für '),
    ('Empfaenger', 'Empfänger'),
    ('verfuegbar', 'verfügbar'),
]

# static/spa/sections/dashboard.js
replacements['static/spa/sections/dashboard.js'] = [
    ('oeffnen', 'öffnen'),
    ('Loesche...', 'Lösche...'),
    ('Loeschen', 'Löschen'),
    ('rueckgaengig', 'rückgängig'),
]

# static/spa/sections/firebase.js
replacements['static/spa/sections/firebase.js'] = [
    ('Loesche...', 'Lösche...'),
    ('Loeschen', 'Löschen'),
    ('rueckgaengig', 'rückgängig'),
]

# static/spa/sections/search.js
replacements['static/spa/sections/search.js'] = [
    (' fuer ', ' für '),
]

# static/spa/sections/send-emails.js
replacements['static/spa/sections/send-emails.js'] = [
    ('abschliessen', 'abschließen'),
    ('loeschen', 'löschen'),
    ('rueckgaengig', 'rückgängig'),
]

# static/spa/sections/supabase.js
replacements['static/spa/sections/supabase.js'] = [
    ('verfuegbar', 'verfügbar'),
    ('Loesche...', 'Lösche...'),
    ('Loeschen', 'Löschen'),
    ('rueckgaengig', 'rückgängig'),
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
