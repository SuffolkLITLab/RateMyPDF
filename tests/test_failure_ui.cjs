// Exercise the actual page script: accessible warning, manual retry, no more polling.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../app/templates/ratemypdf_stats.html'), 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
function element() {
  return {
    children: [], attributes: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  };
}
async function verify(status) {
  const container = element();
  const download = element();
  let onLoad, requests = 0, timers = 0;
  vm.runInNewContext(script, {
    document: {
      getElementById: id => id === 'stats-container' ? container : download,
      createElement: element,
    },
    window: { addEventListener: (_event, callback) => { onLoad = callback; } },
    fetch: async () => { requests++; return { ok: true, json: async () => status }; },
    AbortSignal: { timeout: () => undefined },
    setTimeout: () => { timers++; },
  });
  await onLoad();
  const alert = container.children[0];
  assert.equal(alert.attributes.role, 'alert');
  assert.match(alert.children[0].textContent, /upload/i);
  assert.equal(alert.children[1].href, '/');
  assert.equal(alert.children[1].textContent, 'Try uploading again');
  assert.equal(download.hidden, true);
  assert.equal(requests, 1);
  assert.equal(timers, 0);
}
(async () => {
  await verify({status: 'failed', status_message: "We couldn't convert your Word document to PDF. Please try uploading it again, or save it as a PDF and upload the PDF instead."});
  await verify({status: 'failed'});
  console.log('Failure UI checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
