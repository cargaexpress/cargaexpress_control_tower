path = 'backend/alembic/env.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

target = 'config.set_main_option("sqlalchemy.url", settings.database_url)'
replacement = '# Escape % for configparser interpolation\nconfig.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))'

if target in text:
    text = text.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print('Updated successfully')
else:
    print('Target not found')
