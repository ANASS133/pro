import os

base = r'C:\Users\provincesettat\Desktop\pro-main'

replacements = {}

# templates/dashboard.html - missed lowercase and more patterns
replacements['templates/dashboard.html'] = [
    ('loeschen', 'löschen'),
    ('rueckgaengig', 'rückgängig'),
    ('oeffnen', 'öffnen'),
    ('geloescht', 'gelöscht'),
    ('pruefen', 'prüfen'),
]

# templates/app_shell.html - missed patterns
replacements['templates/app_shell.html'] = [
    ('uebergeben', 'übergeben'),
    ('pruefen', 'prüfen'),
]

# templates/firebase.html - completely missed
replacements['templates/firebase.html'] = [
    ('Loeschen', 'Löschen'),
    ('loeschen', 'löschen'),
    ('geloescht', 'gelöscht'),
    ('rueckgaengig', 'rückgängig'),
]

# templates/send_emails.html - missed 'geloescht'
replacements['templates/send_emails.html'] = [
    ('geloescht', 'gelöscht'),
]

# static/spa/sections/supabase.js - missed 'loeschen'
replacements['static/spa/sections/supabase.js'] = [
    ('loeschen', 'löschen'),
]

# templates/auto_extraction_progress.html
replacements['templates/auto_extraction_progress.html'] = [
    ('oeffnen', 'öffnen'),
    ('loeschen', 'löschen'),
    ('geloescht', 'gelöscht'),
    ('rueckgaengig', 'rückgängig'),
    ('pruefen', 'prüfen'),
    ('uebergeben', 'übergeben'),
]

# templates/captcha_solve.html
replacements['templates/captcha_solve.html'] = [
    ('oeffnen', 'öffnen'),
    ('loeschen', 'löschen'),
]

# templates/create_anschreibens.html
replacements['templates/create_anschreibens.html'] = [
    ('fuer', 'für'),
    ('oeffnen', 'öffnen'),
    ('loeschen', 'löschen'),
    ('verfuegbar', 'verfügbar'),
]

# templates/error.html
replacements['templates/error.html'] = [
    ('zurueck', 'zurück'),
]

# json files
replacements['email_campaigns.json'] = [
    ('fuer', 'für'),
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
