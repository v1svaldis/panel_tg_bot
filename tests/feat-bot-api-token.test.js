// Bot API bearer: whitelist for key management, 401 everywhere else.
// No full server boot — the decision function is executed from source in a vm.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const vm = require('vm');

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  \u2713 ' + m); } else { fail++; console.log('  \u2717 ' + m); } };

const ROOT = path.join(__dirname, '..');
const serverSrc = fs.readFileSync(path.join(ROOT, 'panel', 'server', 'index.js'), 'utf8');
const htmlSrc = fs.readFileSync(path.join(ROOT, 'panel', 'public', 'index.html'), 'utf8');
const appSrc = fs.readFileSync(path.join(ROOT, 'panel', 'public', 'app.js'), 'utf8');
const ru = JSON.parse(fs.readFileSync(path.join(ROOT, 'panel', 'public', 'locales', 'ru.json'), 'utf8'));
const en = JSON.parse(fs.readFileSync(path.join(ROOT, 'panel', 'public', 'locales', 'en.json'), 'utf8'));

function sliceFn(src, name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) return null;
  const brace = src.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  return null;
}

console.log('\n[1] config + generate + mask');
ok(/botApiToken:\s*''/.test(serverSrc), 'botApiToken defaults to empty');
ok(/app\.get\('\/api\/bot\/token\/generate', requireAuth,/.test(serverSrc),
   'generate endpoint is behind requireAuth');
ok(/botApiToken:\s*crypto\.randomBytes\(32\)\.toString\('hex'\)/.test(serverSrc),
   'generates a 64-hex token and does not write it itself');
ok(/'federationToken','federationNodes','botApiToken'/.test(serverSrc),
   'botApiToken is accepted by POST /api/config');
ok(/delete safe\.botApiToken/.test(serverSrc), 'raw botApiToken is stripped from GET /api/config');
ok(/safe\.botApiTokenSet = !!botApiToken/.test(serverSrc), 'GET /api/config exposes only botApiTokenSet');
ok(/botBearerDecision\(req\.method, req\.path/.test(serverSrc),
   'requireAuth consults botBearerDecision');

console.log('\n[2] UI');
ok(/id="s-bot-api-token"/.test(htmlSrc), 'token input is in the panel UI');
ok(/data-action="gen-bot-api-token"/.test(htmlSrc), 'generate button is in the panel UI');
ok(/data-action="save-bot-api-token"/.test(htmlSrc), 'save button is in the panel UI');
ok(/genBotApiToken/.test(appSrc) && /\/api\/bot\/token\/generate/.test(appSrc),
   'UI generates via GET /api/bot/token/generate');
ok(/botApiToken:\s*raw/.test(appSrc), 'UI persists the token via POST /api/config');
ok(ru.botApi && ru.botApi.title && en.botApi && en.botApi.title, 'ru and en locales have botApi.title');

console.log('\n[3] LIVE botBearerDecision');
const routesStart = serverSrc.indexOf('const BOT_API_ROUTES');
const routesEnd = serverSrc.indexOf('function botApiRouteAllowed');
const routes = serverSrc.slice(routesStart, routesEnd);
const allowedFn = sliceFn(serverSrc, 'botApiRouteAllowed');
const decisionFn = sliceFn(serverSrc, 'botBearerDecision');
const equalFn = sliceFn(serverSrc, 'safeTokenEqual');
ok(!!routes && !!allowedFn && !!decisionFn && !!equalFn, 'auth functions extracted from source');

const TOKEN = crypto.randomBytes(32).toString('hex');
const sandbox = { crypto };
vm.createContext(sandbox);
vm.runInContext(`${equalFn}\n${routes}\n${allowedFn}\n${decisionFn}\nthis.botBearerDecision = botBearerDecision;`, sandbox);
const decide = (method, path, authorization, token) =>
  sandbox.botBearerDecision(method, path, authorization, token == null ? TOKEN : token);
const bearer = 'Bearer ' + TOKEN;

const allowed = [
  ['GET', '/api/config'],
  ['GET', '/api/users'],
  ['POST', '/api/users'],
  ['PUT', '/api/users/abc-123'],
  ['DELETE', '/api/users/abc-123'],
  ['GET', '/api/users/abc-123/config/naive'],
  ['GET', '/api/users/abc-123/config/mieru'],
  ['GET', '/api/users/abc-123/config/hy2'],
  ['GET', '/api/users/abc-123/config/universal'],
  ['GET', '/api/users/abc-123/sub-link'],
  ['GET', '/api/apply-status'],
  ['GET', '/api/users/abc-123/config/naive?x=1'],
];
for (const [method, path] of allowed) {
  ok(decide(method, path, bearer) === 200, `valid token ${method} ${path} → 200`);
}

const denied = [
  ['POST', '/api/config/password'],
  ['POST', '/api/config'],
  ['GET', '/api/backup/export'],
  ['POST', '/api/backup/import'],
  ['POST', '/api/settings/warp'],
  ['POST', '/api/settings/cascade'],
  ['POST', '/api/federation/fetch'],
  ['POST', '/api/federation/provision'],
  ['GET', '/api/bot/token/generate'],
  ['POST', '/api/users/abc-123/federation/deploy'],
  ['GET', '/api/users/abc-123/config/socks'],
  ['GET', '/api/status'],
];
for (const [method, path] of denied) {
  ok(decide(method, path, bearer) === 401, `valid token ${method} ${path} → 401`);
}

ok(decide('GET', '/api/users', 'Bearer wrong-token') === 401, 'wrong token on whitelist → 401');
ok(decide('GET', '/api/config', 'Bearer wrong-token') === 401, 'wrong token on /api/config → 401');
ok(decide('POST', '/api/config/password', 'Bearer wrong-token') === 401, 'wrong token on password → 401');
ok(decide('GET', '/api/users', '') === 401, 'missing header → 401');
ok(decide('GET', '/api/users', 'Basic ' + TOKEN) === 401, 'non-bearer scheme → 401');
ok(sandbox.botBearerDecision('GET', '/api/users', bearer, '') === 401, 'empty configured token → 401');
ok(sandbox.botBearerDecision('POST', '/api/users', bearer, '   ') === 401, 'blank configured token → 401');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
