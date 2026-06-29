import os

with open('requirements.txt', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

excludes = {'reportlab', 'xhtml2pdf', 'pyHanko', 'pyhanko-certvalidator', 'drf-spectacular'}
in_lines = set()

for line in lines:
    pkg = line.split('==')[0].strip()
    if pkg and pkg not in excludes:
        in_lines.add(pkg)

in_lines.add('drf-spectacular')

with open('requirements.in', 'w', encoding='utf-8') as f:
    for pkg in sorted(in_lines):
        f.write(f"{pkg}\n")
