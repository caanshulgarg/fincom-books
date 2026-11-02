"""Build the static website: the landing page plus the browser edition of the app.

    python web/build_site.py <pyodide-package-dir> <output-dir>

<pyodide-package-dir> is the unpacked npm package (e.g. `npm pack pyodide@314.0.7`, then extract).
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = ['fidelity.css', 'theme.css', 'workflows.js', 'fincom_screens.js', 'voucher_logic.js', 'lookup_context.js', 'print_view.js',
             'date_picker.js', 'logo.png', 'favicon.ico', 'version.json',
             'app_server.py', 'books.py', 'billing_rules.py', 'interchange.py', 'bank_import.py', 'inbox.py']
PYODIDE_FILES = ['pyodide.js', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']


def build(pyodide_dir: Path, out: Path):
    if out.exists():
        shutil.rmtree(out)
    app = out / 'app'
    (app / 'pyodide').mkdir(parents=True)
    for name in APP_FILES:
        shutil.copy2(ROOT / name, app / name)
    for name in ('web_boot.js', 'web_bridge.py'):
        shutil.copy2(ROOT / 'web' / name, app / name)
    for name in PYODIDE_FILES:
        shutil.copy2(pyodide_dir / name, app / 'pyodide' / name)

    # The site is served from a sub-path (GitHub Pages), so root-relative asset links become relative.
    page = (ROOT / 'index.html').read_text(encoding='utf-8')
    page = re.sub(r'(src|href)="/(?!/)', r'\1="./', page)
    first_script = page.index('<script src=')
    page = page[:first_script] + '<script src="./pyodide/pyodide.js"></script><script src="./web_boot.js"></script>' + page[first_script:]
    (app / 'index.html').write_text(page, encoding='utf-8')
    manifest = (ROOT / 'manifest.json').read_text(encoding='utf-8').replace('"/', '"./')
    (app / 'manifest.json').write_text(manifest, encoding='utf-8')

    shutil.copy2(ROOT / 'web' / 'index.html', out / 'index.html')
    shutil.copy2(ROOT / 'web' / 'voucher.jpg', out / 'voucher.jpg')
    shutil.copy2(ROOT / 'logo.png', out / 'logo.png')
    shutil.copy2(ROOT / 'favicon.ico', out / 'favicon.ico')
    shutil.copy2(ROOT / 'LICENSE', out / 'LICENSE.txt')
    (out / '.nojekyll').write_text('')
    return out


if __name__ == '__main__':
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
