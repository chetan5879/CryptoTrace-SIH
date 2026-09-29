"""Fetch pinned public browser dependencies during installation, never during investigations.
Review supplier code/licenses and lock file hashes in your release approval process.
"""
import hashlib
import json
from pathlib import Path
import requests
assets=Path(__file__).with_name('assets');assets.mkdir(exist_ok=True)
urls={
 'fontawesome.min.css':'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css',
 'fa-solid-900.woff2':'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/webfonts/fa-solid-900.woff2',
 'fa-regular-400.woff2':'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/webfonts/fa-regular-400.woff2',
 'vis-network.min.js':'https://unpkg.com/vis-network@10.1.2/standalone/umd/vis-network.min.js',
 'jspdf.umd.min.js':'https://unpkg.com/jspdf@4.2.1/dist/jspdf.umd.min.js',
 'jspdf.plugin.autotable.min.js':'https://unpkg.com/jspdf-autotable@5.0.8/dist/jspdf.plugin.autotable.min.js',
}
manifest=json.loads((assets/'manifest.json').read_text()) if (assets/'manifest.json').exists() else {}
for name,url in urls.items():
 response=requests.get(url,timeout=30);response.raise_for_status()
 data=response.content
 if name.endswith('.css'): data=data.replace(b'../webfonts/', b'/assets/')
 (assets/name).write_bytes(data)
 manifest[name]={'source':url,'sha256':hashlib.sha256(data).hexdigest()}
(assets/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Local browser assets installed; hashes recorded in assets/manifest.json')

# Report fonts are bundled separately (DejaVu 2.37); this command preserves them.
for name in ('report-regular.ttf','report-bold.ttf'):
 if not (assets/name).is_file(): raise RuntimeError('Restore the bundled report fonts from the release ZIP')
