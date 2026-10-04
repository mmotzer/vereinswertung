'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roleName = role => ({admin:'Administrator',director:'Turnierleiter',member:'Vereinsmitglied'}[role] || role);
const catName = cat => cat === 'blitz' ? 'Blitz' : 'Schnellschach';
const formatDate = date => date ? new Date(date + 'T12:00:00Z').toLocaleDateString('de-DE') : '–';
const signed = n => n > 0 ? '+' + n : String(n);
const delta = n => `<span class="delta ${n > 0 ? 'positive' : n < 0 ? 'negative' : ''}">${signed(n)}</span>`;
const resultLabel = n => n === 1 ? '1 : 0' : n === 0 ? '0 : 1' : '½ : ½';
let user = null, csrf = null, needsSetup = false, category = 'blitz', ranks = [], tournaments = [];
let importData = null, previewToken = null, undoTarget = null, resetTarget = null, toastTimer, importGeneration = 0;

async function api(path, body) {
  const options = {headers: {}, credentials: 'same-origin'};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf || ''};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 401 && user) { location.reload(); throw new Error('Bitte erneut anmelden'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen');
  return data;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.toggle('error-toast', error);
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, error ? 12000 : 5000);
}
async function busy(button, fn) {
  if (button.disabled) return;
  button.disabled = true;
  const original = button.textContent;
  button.textContent = 'Bitte warten …';
  try { await fn(); } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = original; }
}
function empty(title, text, action = '') {
  return `<div class="empty"><div class="empty-icon" aria-hidden="true">♙</div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(text)}</p>${action}</div>`;
}
function refreshAuth() {
  $$('.auth-only').forEach(el => { el.hidden = !user; });
  $('.nav [data-page="submissions"]').textContent = ['director','admin'].includes(user?.role) ? 'Einreichungen' : 'Einreichen';
  $$('.director-only').forEach(el => { el.hidden = !['director', 'admin'].includes(user?.role); });
  $$('.admin-only').forEach(el => { el.hidden = user?.role !== 'admin'; });
  $('#login-button').textContent = user ? user.username : needsSetup ? 'App einrichten' : 'Anmelden';
}
function openAuth() {
  if (user) {
    $('#account-name').textContent = `${user.username} · ${roleName(user.role)}`;
    $('#account-dialog').showModal();
    return;
  }
  $('#auth-form').reset();
  $('#auth-error').hidden = true;
  $('#setup-token-label').hidden = !needsSetup;
  $('#setup-token').required = needsSetup;
  $('#auth-password').minLength = needsSetup ? 12 : 1;
  $('#auth-password').autocomplete = needsSetup ? 'new-password' : 'current-password';
  $('#auth-eyebrow').textContent = needsSetup ? 'ERSTE EINRICHTUNG' : 'TURNIERLEITER';
  $('#auth-title').textContent = needsSetup ? 'Dein Verein. Deine Wertung.' : 'Willkommen zurück.';
  $('#auth-description').textContent = needsSetup ? 'Lege den ersten Administrator an. Den Einrichtungsschlüssel findest du in deiner NAS-Konfiguration.' : 'Melde dich an, um ein Turnier zu importieren.';
  $('#auth-submit').textContent = needsSetup ? 'Administrator anlegen →' : 'Anmelden →';
  $('#auth-dialog').showModal();
}
$('#login-button').addEventListener('click', openAuth);
$$('[data-close]').forEach(el => el.addEventListener('click', () => document.getElementById(el.dataset.close).close()));
// Close details on a backdrop tap, without treating clicks inside the panel
// or drags starting inside it as a request to close.
const detailDialog = $('#detail-dialog');
const outsideDetails = event => {
  const rect = detailDialog.getBoundingClientRect();
  return event.clientX < rect.left || event.clientX > rect.right ||
    event.clientY < rect.top || event.clientY > rect.bottom;
};
let detailBackdropPress = false;
detailDialog.addEventListener('pointerdown', event => {
  detailBackdropPress = event.target === detailDialog && outsideDetails(event);
});
detailDialog.addEventListener('click', event => {
  if (detailBackdropPress && event.target === detailDialog && outsideDetails(event)) detailDialog.close();
  detailBackdropPress = false;
});
detailDialog.addEventListener('close', () => { detailBackdropPress = false; });
$('#auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('#auth-submit');
  if (button.disabled) return;
  button.disabled = true;
  $('#auth-error').hidden = true;
  try {
    const credentials = {username: $('#auth-username').value, password: $('#auth-password').value};
    if (needsSetup) {
      await api('/api/setup', {...credentials, token: $('#setup-token').value});
      needsSetup = false;
    }
    const login = await api('/api/login', credentials);
    user = login.user; csrf = login.csrf;
    refreshAuth();
    $('#auth-dialog').close();
    $('#auth-form').reset();
    toast('Angemeldet. Du kannst jetzt Turniere importieren.');
    location.hash = '#import';
    await navigate();
  } catch (error) {
    $('#auth-error').textContent = error.message;
    $('#auth-error').hidden = false;
  } finally { button.disabled = false; }
});
$('#logout-button').addEventListener('click', event => busy(event.currentTarget, async () => {
  await api('/api/logout', {});
  location.reload();
  user = null; csrf = null; previewToken = null; importData = null;
  $('#account-dialog').close();
  $('#import-form').hidden = true; $('#import-preview').hidden = true;
  refreshAuth(); location.hash = '#rankings'; await navigate();
}));
$('#password-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    await api('/api/password', Object.fromEntries(new FormData(event.target)));
    event.target.reset(); toast('Passwort geändert. Andere Sitzungen wurden abgemeldet.');
  });
});

async function loadRanks() {
  const requested = category;
  $('#ranking-list').innerHTML = '<p class="loading">Rangliste wird geladen …</p>';
  const data = await api('/api/rankings?category=' + requested);
  if (requested !== category) return;
  ranks = data.players.filter(p => p.games > 0);
  const played = ranks.filter(p => p.games > 0);
  $('#rank-stats').innerHTML = `<div class="stat"><strong>${played.length}</strong><span>Spieler mit ${catName(category)}partien</span></div><div class="stat"><strong>${ranks.reduce((n, p) => n + p.games, 0) / 2}</strong><span>Gewertete Partien</span></div><div class="stat"><strong>${ranks.filter(p => p.games && !p.provisional).length}</strong><span>Gefestigte Wertungen</span></div>`;
  renderRanks();
}
function renderRanks() {
  const search = $('#player-search').value.toLocaleLowerCase('de');
  const filtered = ranks.filter(p => p.name.toLocaleLowerCase('de').includes(search) && (!$('#established-only').checked || (p.games > 0 && !p.provisional)));
  if (!ranks.length) {
    $('#ranking-list').innerHTML = empty('Die erste Partie macht den Anfang.', 'Noch keine gewerteten Partien in dieser Kategorie. Nach dem ersten Turnierimport erscheint hier eure Vereinsrangliste.', user ? '<a class="button" href="#import">Erstes Turnier importieren →</a>' : '');
    return;
  }
  if (!filtered.length) {
    $('#ranking-list').innerHTML = empty('Keine passenden Spieler.', 'Passe die Suche oder den Filter an.'); return;
  }
  $('#ranking-list').innerHTML = `<table class="rank-table"><thead><tr><th>#</th><th>Spieler</th><th>Wertung</th><th class="games-col">Partien</th><th>Letzte Partie</th></tr></thead><tbody>${filtered.map(p => {
    const initials = p.name.split(/[ ,]+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('');
    return `<tr><td class="rank-num">${p.games ? ranks.filter(r => r.games && r.rating > p.rating).length + 1 : '–'}</td><td><button class="player-link" data-player="${p.id}"><span class="avatar" aria-hidden="true">${escapeHtml(initials)}</span><span>${escapeHtml(p.name)}</span></button></td><td><span class="rating-value">${p.display}</span>${p.provisional ? '<span class="question-mark" title="Vorläufige Wertung">?</span>' : ''}</td><td class="games-col">${p.games}</td><td>${p.games ? delta(p.diff) : '<span class="muted">–</span>'}</td></tr>`;
  }).join('')}</tbody></table>`;
}
$$('[data-category]').forEach(button => button.addEventListener('click', async () => {
  category = button.dataset.category;
  $$('[data-category]').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  $('#csv-link').href = '/api/export.csv?category=' + category;
  try { await loadRanks(); } catch (error) { toast(error.message, true); }
}));
$('#player-search').addEventListener('input', renderRanks);
$('#established-only').addEventListener('change', renderRanks);

async function loadTournaments() {
  const data = await api('/api/tournaments'); tournaments = data.tournaments;
  $('#tournament-list').innerHTML = tournaments.length ? tournaments.map(t => `<article class="card tournament-card"><div><span class="badge ${t.active ? '' : 'cancelled'}">${catName(t.category)}${t.active ? '' : ' · Zurückgenommen'}</span><h2>${escapeHtml(t.name)}</h2><p>${formatDate(t.date)}${t.end_date !== t.date ? ' – ' + formatDate(t.end_date) : ''} · ${t.rounds} Runden · ${t.games} Partien</p></div><button class="button secondary" data-tournament="${t.id}">Ansehen →</button></article>`).join('') : empty('Hier beginnt eure Turnierhistorie.', 'Bestätigte Importe erscheinen hier mit Ergebnissen und Wertungsänderungen.');
}
function changesTable(changes) {
  return `<div class="table-scroll"><table class="detail-table"><thead><tr><th>Spieler</th><th>Vorher</th><th>Nachher</th><th>Änderung</th></tr></thead><tbody>${changes.map(c => `<tr><td>${escapeHtml(c.name)}</td><td>${c.before}</td><td><strong>${c.after}</strong></td><td>${delta(c.diff)}</td></tr>`).join('')}</tbody></table></div>`;
}
function gameTable(games) {
  return `<div class="table-scroll"><table class="detail-table"><thead><tr><th>Runde</th><th>Weiß</th><th>Ergebnis</th><th>Schwarz</th></tr></thead><tbody>${games.map(g => `<tr><td>${g.round}</td><td>${escapeHtml(g.white_name)}${g.white_diff !== undefined ? '<br>' + delta(g.white_diff) : ''}</td><td>${resultLabel(g.score)}</td><td>${escapeHtml(g.black_name)}${g.black_diff !== undefined ? '<br>' + delta(g.black_diff) : ''}</td></tr>`).join('')}</tbody></table></div>`;
}
async function showTournament(id) {
  const t = await api('/api/tournaments/' + id);
  const canUndo = t.active && user && (user.role === 'admin' || t.owner === user.id);
  $('#detail-content').innerHTML = `<div class="eyebrow">${catName(t.category)} · ${formatDate(t.date)}</div><h2>${escapeHtml(t.name)}</h2>${!t.active ? '<p class="note">Dieser Import wurde zurückgenommen und wird nicht gewertet.</p>' : `<h3>Wertungsänderungen im Turnier</h3>${changesTable(t.changes)}`}<h3>Partien</h3>${gameTable(t.games)}${t.skipped.length ? `<p class="note">${t.skipped.length} Einträge ohne gespielte Partie wurden nicht gewertet.</p>` : ''}${!t.active && user?.role === 'admin' ? '<hr><p class="note">Spieler bleiben in der Datenbank erhalten.</p><button class="button secondary" id="hide-tournament">Aus Übersicht entfernen</button>' : ''}${canUndo ? `<hr><button class="button secondary" id="undo-open">Import zurücknehmen</button>` : ''}`;
  $('#detail-dialog').showModal();
  if (!t.active && user?.role === 'admin') $('#hide-tournament').addEventListener('click', event => busy(event.currentTarget, async () => {
    await api(`/api/tournaments/${t.id}/hide`, {});
    $('#detail-dialog').close();
    toast('Turnier ausgeblendet. Spieler bleiben erhalten.');
    await loadTournaments();
  }));
  if (canUndo) $('#undo-open').addEventListener('click', () => {
    undoTarget = t; $('#detail-dialog').close(); $('#undo-form').reset();
    $('#undo-name').placeholder = t.name; $('#undo-dialog').showModal();
  });
}
$('#undo-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    await api(`/api/tournaments/${undoTarget.id}/undo`, {confirm: $('#undo-name').value});
    $('#undo-dialog').close(); toast('Import zurückgenommen. Folgewertungen wurden neu berechnet.');
    await loadTournaments(); await loadRanks();
  });
});
async function showPlayer(id) {
  const data = await api('/api/players/' + id);
  const history = data.history.filter(h => h.category === category);
  const points = history.slice().reverse().map(h => h.after);
  let chart = '';
  if (points.length) {
    points.unshift(1500);
    const min = Math.min(...points) - 30, max = Math.max(...points) + 30;
    const coords = points.map((p, i) => `${15 + i / Math.max(1, points.length - 1) * 630},${140 - (p - min) / (max - min) * 115}`).join(' ');
    chart = `<svg class="chart" viewBox="0 0 660 160" role="img" aria-label="Wertungsverlauf ${catName(category)}, von 1500 auf ${points.at(-1)}"><polyline class="chart-line" points="${coords}"/></svg>`;
  }
  $('#detail-content').innerHTML = `<div class="eyebrow">SPIELERPROFIL</div><h2>${escapeHtml(data.player.name)}</h2><div class="profile-ratings">${['blitz','rapid'].map(cat => {
    const r = data.ratings[cat];
    return `<div class="card"><span class="muted">${catName(cat)}</span><strong>${r?.display ?? 1500}${r?.provisional !== false ? '?' : ''}</strong><span class="muted">${r?.games ?? 0} Partien · RD ${(r?.rd ?? 500).toFixed(1)}</span></div>`;
  }).join('')}</div><h3>${catName(category)} · Wertungsverlauf</h3>${chart}${history.length ? `<div class="table-scroll"><table class="detail-table"><thead><tr><th>Turnier / Runde</th><th>Gegner</th><th>Ergebnis</th><th>Wertung</th></tr></thead><tbody>${history.map(h => `<tr><td>${escapeHtml(h.name)}<br><span class="muted">${formatDate(h.date)} · R${h.round}</span></td><td>${escapeHtml(h.opponent)}<br><span class="muted">${h.color}</span></td><td>${h.result === .5 ? '½' : h.result}</td><td>${h.after}<br>${delta(h.diff)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">Noch keine gewerteten Partien in dieser Kategorie.</p>'}`;
  $('#detail-dialog').showModal();
}
document.addEventListener('click', event => {
  const player = event.target.closest('[data-player]'), tournament = event.target.closest('[data-tournament]');
  if (player) showPlayer(Number(player.dataset.player)).catch(e => toast(e.message, true));
  if (tournament) showTournament(Number(tournament.dataset.tournament)).catch(e => toast(e.message, true));
});

function invalidatePreview() { importGeneration++; previewToken = null; $('#import-preview').hidden = true; }
$('#import-form').addEventListener('input', invalidatePreview);
$('#import-form').addEventListener('change', invalidatePreview);
$('#trf-file').addEventListener('change', () => { importData = null; $('#import-form').hidden = true; invalidatePreview(); });
$('#upload-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const file = $('#trf-file').files[0];
    if (!file) throw new Error('Bitte eine TRF-Datei auswählen.');
    if (file.size > 1024 * 1024) throw new Error('Die TRF-Datei darf höchstens 1 MB groß sein.');
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
    const content = btoa(binary);
    const info = await api('/api/import/inspect', {content});
    if ($('#trf-file').files[0] !== file) throw new Error('Dateiauswahl geändert. Bitte die neue Datei prüfen.');
    importData = {...info, content, filename: file.name}; invalidatePreview();
    $('#import-name').value = info.parsed.name;
    $('#import-date').value = info.parsed.date;
    $('#round-dates').innerHTML = Array.from({length: info.parsed.rounds}, (_, i) => `<label>Runde ${i + 1}<input type="date" data-round-date="${i}" value="${escapeHtml(info.parsed.date)}" required></label>`).join('');
    $('#import-summary').textContent = `${info.parsed.players.length} Spieler · ${info.parsed.rounds} Runden · ${info.parsed.games.length} gewertete Partien · ${info.parsed.skipped.length} nicht gewertete Einträge`;
    $('#assignments').innerHTML = info.assignments.map(a => `<div class="assignment"><div><strong>${escapeHtml(a.name)}</strong><small>${a.player_id ? 'Bekannt · ' + escapeHtml(a.matched_name) : a.suggestions.length ? 'Ähnlicher Name vorhanden – bitte Zuordnung prüfen' : 'Neu · Start bei 1500'}</small></div><label class="assignment-control"><span class="muted">Zuordnung</span><select data-assignment="${a.number}" aria-label="Zuordnung für ${escapeHtml(a.name)}" ${a.player_id ? 'disabled' : ''}><option value="0">Neuen Spieler anlegen · 1500</option>${info.players.map(p => `<option value="${p.id}" ${p.id === a.player_id ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}</select></label></div>`).join('');
    const warnings = [...info.parsed.warnings];
    if (info.parsed.end_date && info.parsed.end_date !== info.parsed.date) warnings.push('Mehrtägiges Turnier erkannt: Bitte das Datum jeder Runde anpassen.');
    $('#import-warnings').innerHTML = warnings.map(w => `<p class="note">${escapeHtml(w)}</p>`).join('');
    $('#import-form').hidden = false;
    $('#import-form').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
});
$('#import-date').addEventListener('change', () => { $$('[data-round-date]').forEach(input => { input.value = $('#import-date').value; }); });
$('#import-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    if (!importData) throw new Error('Bitte zuerst die Datei prüfen.');
    const payload = {content: importData.content, filename: importData.filename, name: $('#import-name').value,
      category: $('#import-category').value, round_dates: $$('[data-round-date]').map(i => i.value),
      mapping: Object.fromEntries($$('[data-assignment]').map(i => [i.dataset.assignment, Number(i.value)]))};
    const generation = importGeneration;
    const data = await api('/api/import/preview', payload);
    if (generation !== importGeneration) throw new Error('Angaben wurden während der Berechnung geändert. Bitte die Vorschau erneut berechnen.');
    previewToken = data.token;
    const t = data.tournament;
    $('#import-preview').innerHTML = `<div class="eyebrow">NOCH NICHT GESPEICHERT</div><h2>Vorschau: ${escapeHtml(t.name)}</h2><p class="muted">${catName(t.category)} · ${formatDate(t.date)} · ${t.games.length} Partien</p><h3>Änderung während dieses Turniers</h3>${changesTable(t.changes)}<details><summary>Alle Partien prüfen</summary>${gameTable(t.games)}</details>${data.affected.length ? `<details><summary>Auswirkung auf die heutige Rangliste</summary>${changesTable(data.affected.map(c => ({...c, name: c.name + ' · ' + catName(c.category), diff: c.after - c.before})))}</details>` : ''}<p class="note">Neue Spieler werden erst beim Speichern angelegt. Ein älteres Turnier berechnet auch nachfolgende Wertungen neu.</p><label class="check-label"><input id="preview-confirm" type="checkbox"> Spieler, Kategorie, Rundendaten und Ergebnisse sind geprüft.</label><button id="commit-button" class="button" disabled>Import verbindlich speichern →</button>`;
    $('#import-preview').hidden = false;
    $('#preview-confirm').addEventListener('change', event => { $('#commit-button').disabled = !event.target.checked; });
    $('#commit-button').addEventListener('click', event => busy(event.currentTarget, async () => {
      if (!previewToken) throw new Error('Bitte Vorschau erneut berechnen.');
      const saved = await api('/api/import/commit', {token: previewToken});
      previewToken = null; importData = null;
      $('#import-preview').hidden = true; $('#import-form').hidden = true; $('#upload-form').reset();
      toast('Turnier gespeichert. Die Vereinswertungen sind aktualisiert.');
      await loadRanks(); location.hash = '#tournaments'; await navigate(); await showTournament(saved.tournament_id);
    }));
    $('#import-preview').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
});

async function loadAdmin() {
  const [accounts, audit, settings] = await Promise.all([api('/api/users'), api('/api/audit'), api('/api/settings')]);
  $('#request-email').value = settings.request_email;
  $('#user-list').innerHTML = '<h2>Bestehende Zugänge</h2>' + accounts.users.map(u => `<div class="user-row"><div><strong>${escapeHtml(u.username)}</strong><small>${roleName(u.role)} · ${u.active ? 'Aktiv' : 'Gesperrt'}</small></div><div class="user-actions"><button class="button secondary" data-reset-user="${u.id}" data-username="${escapeHtml(u.username)}">Passwort setzen</button>${u.id !== user.id ? `<button class="button secondary" data-toggle-user="${u.id}" data-active="${u.active}">${u.active ? 'Sperren' : 'Aktivieren'}</button>` : ''}</div></div>`).join('');
  $('#audit-list').innerHTML = audit.events.map(e => `<div class="audit-item">${escapeHtml(new Date(e.created * 1000).toLocaleString('de-DE'))} · ${escapeHtml(e.username)} · ${escapeHtml(e.detail)}</div>`).join('');
  $$('[data-toggle-user]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
    await api('/api/users/' + button.dataset.toggleUser, {active: button.dataset.active !== '1'}); await loadAdmin();
  })));
  $$('[data-reset-user]').forEach(button => button.addEventListener('click', () => {
    resetTarget = Number(button.dataset.resetUser); $('#reset-name').textContent = button.dataset.username;
    $('#reset-form').reset(); $('#reset-dialog').showModal();
  }));
}
$('#user-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => { await api('/api/users', Object.fromEntries(new FormData(event.target))); event.target.reset(); toast('Zugang angelegt.'); await loadAdmin(); });
});
$('#reset-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    await api('/api/users/' + resetTarget, Object.fromEntries(new FormData(event.target)));
    $('#reset-dialog').close(); toast('Passwort gesetzt. Bestehende Sitzungen wurden beendet.');
    const me = await api('/api/me'); user = me.user; csrf = me.csrf; refreshAuth(); await navigate();
  });
});
async function navigate() {
  let page = location.hash.slice(1) || 'rankings';
  if (!['rankings','tournaments','import','submissions','help','admin'].includes(page)) page = 'rankings';
  if ((page === 'import' && !['director', 'admin'].includes(user?.role)) || (page === 'admin' && user?.role !== 'admin')) { page = 'rankings'; location.hash = '#rankings'; }
  $$('.page').forEach(el => { el.hidden = el.id !== 'page-' + page; });
  $$('.nav a').forEach(el => { el.classList.toggle('active', el.dataset.page === page); if (el.dataset.page === page) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  try {
    if (page === 'rankings') await loadRanks();
    if (page === 'tournaments') await loadTournaments();
    if (page === 'admin') await loadAdmin();
    if (page === 'submissions') await loadSubmissions();
  } catch (error) { toast(error.message, true); }
}
window.addEventListener('hashchange', navigate);
(async () => {
  try {
    const me = await api('/api/me'); user = me.user; csrf = me.csrf; needsSetup = me.needs_setup;
    if (!user) { location.reload(); return; }
    refreshAuth(); await navigate();
  } catch (error) { toast('Verbindung zur App fehlgeschlagen: ' + error.message, true); }
})();

let lichessInfo = null, lichessGeneration = 0;
function invalidateLichess() { lichessGeneration++; $('#lichess-preview').hidden = true; }
$('#lichess-links').addEventListener('input', () => { invalidateLichess(); lichessInfo = null; $('#lichess-mapping-form').hidden = true; });
$('#lichess-mapping-form').addEventListener('input', invalidateLichess);
$('#lichess-mapping-form').addEventListener('change', invalidateLichess);
function displayLichess(info) {
  lichessInfo = info; $('#lichess-consent').checked = false;
  $('#lichess-games').innerHTML = info.games.map(g => `<label class="check-label"><input type="checkbox" data-lichess-game="${escapeHtml(g.external_id)}" checked> ${escapeHtml(g.name)} · ${catName(g.category)} · ${new Date(g.played*1000).toLocaleString('de-DE')} · ${escapeHtml(g.parsed.players[0].name)} – ${escapeHtml(g.parsed.players[1].name)} · ${resultLabel(g.parsed.games[0].score)}</label>`).join('');
  $('#lichess-assignments').innerHTML = info.assignments.map(a => `<label>${escapeHtml(a.name)}<select data-lichess-player="${escapeHtml(a.name)}" ${a.player_id ? 'disabled' : ''}><option value="">Vereinsspieler auswählen</option>${info.players.map(p => `<option value="${p.id}" ${p.id===a.player_id ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}</select></label>`).join('');
  $('#lichess-mapping-form').hidden = false;
  $('#lichess-mapping-form').scrollIntoView({behavior: 'smooth', block: 'start'});
}
for (const form of ['lichess-links-form','lichess-match-form']) {
  $('#'+form).addEventListener('input', () => { invalidateLichess(); lichessInfo = null; $('#lichess-mapping-form').hidden = true; });
  $('#'+form).addEventListener('submit', event => {
    event.preventDefault();
    busy(event.submitter, async () => {
      invalidateLichess(); const generation = lichessGeneration;
      const request = form === 'lichess-match-form' ? {mode:'match', first:$('#lichess-first').value.trim(), second:$('#lichess-second').value.trim(), day:$('#lichess-day').value} : {links:$('#lichess-links').value};
      const info = await api('/api/lichess/inspect', request);
      if (generation !== lichessGeneration) return;
      displayLichess(info);
    });
  });
}
$('#lichess-day').value = new Date().toLocaleDateString('sv-SE');
$('#lichess-mapping-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const generation = lichessGeneration;
    const mapping = Object.fromEntries($$('[data-lichess-player]').map(el => [el.dataset.lichessPlayer, Number(el.value)]));
    const preview = await api('/api/lichess/preview', {token: lichessInfo.token, mapping, selected: $$('[data-lichess-game]:checked').map(el => el.dataset.lichessGame), consent: $('#lichess-consent').checked});
    if (generation !== lichessGeneration) return;
    $('#lichess-preview').innerHTML = `<h2>${preview.count} Partien gemeinsam speichern</h2>${changesTable(preview.changes.map(c => ({...c,name:c.name+' · '+catName(c.category)})))}<p>Auch Änderungen an späteren Wertungen sind in dieser Vorschau enthalten.</p><button id="lichess-save" class="button">Import bestätigen →</button>`;
    $('#lichess-preview').hidden = false;
    $('#lichess-preview').scrollIntoView({behavior: 'smooth', block: 'start'});
    $('#lichess-save').addEventListener('click', event => busy(event.currentTarget, async () => {
      if (generation !== lichessGeneration) throw new Error('Angaben geändert. Bitte neue Vorschau erstellen.');
      await api('/api/import/commit', {token:preview.token});
      invalidateLichess(); lichessInfo = null; $('#lichess-mapping-form').hidden = true; $('#lichess-links-form').reset();
      toast('Lichess-Partien gespeichert.'); await loadRanks(); location.hash = '#tournaments'; await navigate();
    }));
  });
});

let submissionPlayers = [];
async function loadSubmissions() {
  const [people,data] = await Promise.all([api('/api/submission-players'),api('/api/submissions')]);
  submissionPlayers=people.players;
  const options='<option value="">Vereinsspieler auswählen</option>'+people.players.map(p => `<option value="${p.id}" ${p.available ? '' : 'disabled'}>${escapeHtml(p.name)}${p.available ? '' : ' · Lichess-Name fehlt'}</option>`).join('');
  for (const id of ['submission-first','submission-second']) { const value=$('#'+id).value; $('#'+id).innerHTML=options; $('#'+id).value=value; }
  $('#account-player').innerHTML='<option value="">Vereinsspieler auswählen</option>'+people.players.map(p => `<option value="${p.id}">${escapeHtml(p.name)}${p.username ? ' · '+escapeHtml(p.username) : ''}</option>`).join('');
  const names = Object.fromEntries(people.players.map(p => [p.id,p.name]));
  const review = ['admin','director'].includes(user?.role);
  $('#submission-list').innerHTML='<h2>'+ (review ? 'Einreichungen zur Prüfung' : 'Deine Einreichungen')+'</h2>'+ (data.submissions.length ? data.submissions.map(s => `<article class="card"><span class="badge">${({pending:'Wartet auf Prüfung',approved:'Genehmigt',rejected:'Abgelehnt'})[s.status]}</span><h3>${escapeHtml(names[s.payload.first_player] || 'Spieler')} – ${escapeHtml(names[s.payload.second_player] || 'Spieler')}</h3><p>${formatDate(s.payload.day)}${review ? ' · Eingereicht von '+escapeHtml(s.username) : ''}</p>${s.response ? '<p class="note">'+escapeHtml(s.response)+'</p>' : ''}${review && s.status==='pending' ? `<div class="user-actions"><button class="button" data-review-submission="${s.id}">Partien prüfen →</button><button class="button secondary" data-reject-submission="${s.id}">Ablehnen</button></div>` : ''}</article>`).join('') : '<p class="muted">Noch keine Einreichungen.</p>');
  $('#submission-day').value ||= new Date().toLocaleDateString('sv-SE');
}
$('#submission-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter,async () => {
    await api('/api/submissions',{mode:'match',first_player:Number($('#submission-first').value),second_player:Number($('#submission-second').value),day:$('#submission-day').value,consent:$('#submission-consent').checked});
    $('#submission-consent').checked=false; toast('Zur Prüfung bei der Turnierleitung eingereicht.'); await loadSubmissions(); $('#submission-list').scrollIntoView({behavior:'smooth',block:'start'});
  });
});
$('#lichess-account-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter,async () => { await api('/api/players/'+Number($('#account-player').value)+'/lichess',{username:$('#account-lichess-name').value.trim()}); event.target.reset(); toast('Lichess-Konto hinterlegt.'); await loadSubmissions(); });
});
$('#request-email-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter,async () => { await api('/api/settings',{request_email:$('#request-email').value.trim()}); toast('Adresse für Login-Anfragen gespeichert.'); });
});
$('#submission-list').addEventListener('click', event => {
  const review=event.target.closest('[data-review-submission]');
  const reject=event.target.closest('[data-reject-submission]');
  if (review) busy(review,async () => {
    const info=await api('/api/lichess/inspect',{submission_id:Number(review.dataset.reviewSubmission)});
    invalidateLichess(); location.hash='#import'; await navigate(); displayLichess(info);
  });
  if (reject) busy(reject,async () => {
    const reason=window.prompt('Begründung für die Ablehnung:');
    if (!reason) return;
    await api('/api/submissions/'+Number(reject.dataset.rejectSubmission)+'/reject',{reason}); await loadSubmissions(); toast('Einreichung abgelehnt.');
  });
});

$('#create-invitation').addEventListener('click',event => busy(event.currentTarget,async () => {
  const invite=await api('/api/invitations',{});$('#invitation-code').value=invite.code;$('#invitation-result').hidden=false;
  $('#invitation-expiry').textContent='Gültig bis '+new Date(invite.expires*1000).toLocaleString('de-DE')+' · einmalig';
  $('#invitation-result').scrollIntoView({behavior:'smooth',block:'start'});
}));
