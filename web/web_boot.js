// Web edition: load Python (Pyodide), keep the books in this browser's IndexedDB,
// and answer the app's /api calls locally. Must load before workflows.js.
(function () {
  const realFetch = window.fetch.bind(window);
  const sources = ['app_server.py', 'books.py', 'billing_rules.py', 'interchange.py', 'version.json', 'web_bridge.py'];
  const splash = document.createElement('div');
  splash.id = 'web-boot';
  splash.setAttribute('role', 'status');
  splash.textContent = 'Starting FinCom Books…';
  splash.style.cssText = 'position:fixed;inset:0;display:grid;place-items:center;background:#f4f8fc;color:#0e2a5c;font:600 16px system-ui,sans-serif;z-index:99999';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(splash));

  const sync = (py, load) => new Promise((resolve, reject) => py.FS.syncfs(load, (err) => (err ? reject(err) : resolve())));

  const ready = (async () => {
    const py = await loadPyodide({ indexURL: new URL('pyodide/', document.baseURI).href });
    py.FS.mkdirTree('/app');
    for (const name of sources) {
      const res = await realFetch(name, { cache: 'no-cache' });
      if (!res.ok) throw new Error('Missing ' + name);
      py.FS.writeFile('/app/' + name, new Uint8Array(await res.arrayBuffer()));
    }
    py.FS.mkdirTree('/data');
    py.FS.mount(py.FS.filesystems.IDBFS, {}, '/data');
    await sync(py, true);
    py.runPython("import sys; sys.path.insert(0, '/app')");
    const handle = py.pyimport('web_bridge').handle;
    splash.remove();
    return { py, handle };
  })();
  ready.catch((err) => {
    splash.textContent = 'FinCom Books could not start in this browser: ' + err.message + '. Use the latest Chrome, Edge or Safari, or download the desktop app.';
  });

  let saving = Promise.resolve();
  const persist = (py) => (saving = saving.then(() => sync(py, false)).catch((err) => console.error('Save to browser storage failed', err)));

  async function local(path, init = {}) {
    const { py, handle } = await ready;
    const method = (init.method || 'GET').toUpperCase();
    const result = handle(method, path, typeof init.body === 'string' ? init.body : '');
    const [status, headers, payload] = result.toJs({ dict_converter: Object.fromEntries });
    result.destroy();
    if (method === 'POST') await persist(py);
    return new Response(payload, { status, headers });
  }

  const isLocal = (url) => typeof url === 'string' && (url.startsWith('/api/') || url === '/version.json');

  window.fetch = (input, init) => (isLocal(input) ? local(input, init) : realFetch(input, init));

  async function saveFrom(path) {
    const res = await local(path);
    const name = (/filename="?([^";]+)/.exec(res.headers.get('Content-Disposition') || '') || [])[1] || path.split('/').pop().split('?')[0];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  // Links such as the CSV/XLSX templates point at /api/...; there is no server, so fetch them locally.
  document.addEventListener('click', (event) => {
    const link = event.target.closest && event.target.closest('a[href^="/api/"]');
    if (!link) return;
    event.preventDefault();
    saveFrom(link.getAttribute('href'));
  }, true);
  const realOpen = window.open.bind(window);
  window.open = (url, ...rest) => (isLocal(url) ? (saveFrom(url), null) : realOpen(url, ...rest));
  // Flush pending saves if the tab is closed mid-write.
  window.addEventListener('pagehide', () => ready.then(({ py }) => persist(py)));
})();
