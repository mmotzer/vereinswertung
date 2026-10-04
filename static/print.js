'use strict';
const sheets = document.querySelector('#print-sheets');
const status = document.querySelector('#print-status');
const button = document.querySelector('#print-button');
let lists = null;
const loadedAt = new Date();
function element(tag, text, className) {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
function render() {
  if (!lists) return;
  sheets.replaceChildren();
  const selected = document.querySelector('#print-category').value;
  for (const cat of selected === 'both' ? ['blitz','rapid'] : [selected]) {
    const players = lists[cat].players.filter(p => p.games || document.querySelector('#include-new').checked);
    const section = element('section', '', 'sheet'), header = element('header','');
    header.append(element('h1', document.querySelector('#club-title').value.trim() || 'Vereinswertung'),
      element('h2', cat === 'blitz' ? 'Blitz · Vereinsrangliste' : 'Schnellschach · Vereinsrangliste'),
      element('p', 'Stand: ' + loadedAt.toLocaleString('de-DE') + ' · ' + players.length + ' Spieler'));
    section.append(header);
    if (!players.length) section.append(element('p', 'Noch keine gewerteten Partien in dieser Kategorie.'));
    else {
      const table = element('table',''), head = element('thead',''), row = element('tr','');
      ['Platz','Spieler','Wertung','Partien'].forEach((title,i) => row.append(element('th',title,i>1?'number':'')));
      head.append(row); table.append(head); const body = element('tbody','');
      let previous = null, rank = 0, played = 0;
      players.forEach(p => {
        if (p.games) { played++; if (p.rating !== previous) rank = played; previous = p.rating; }
        const r = element('tr','');
        r.append(element('td',p.games?String(rank):'–'),element('td',p.name,'name'),
          element('td',String(p.display)+(p.provisional?' *':''),'number'),element('td',String(p.games),'number'));
        body.append(r);
      }); table.append(body); section.append(table);
    }
    section.append(element('p','* Vorläufige Wertung: Es liegen noch zu wenige verlässliche Ergebnisse vor oder die letzte Partie liegt länger zurück. Blitz und Schnellschach werden getrennt berechnet. Vereinsinterne Glicko-2-Wertung; alle beginnen bei 1500.','notes'));
    sheets.append(section);
  }
}
document.querySelectorAll('.controls input,.controls select').forEach(input => input.addEventListener('input',render));
button.addEventListener('click',() => window.print());
(async () => {
  try {
    const results = await Promise.all(['blitz','rapid'].map(async cat => {
      const response = await fetch('/api/rankings?category='+cat,{cache:'no-store'});
      if (response.status===401) { location.replace('/'); throw new Error('Bitte anmelden.'); }
      if (!response.ok) throw new Error('Wertungen konnten nicht geladen werden. Bitte neu laden.');
      return response.json();
    }));
    if (results[0].revision !== results[1].revision) throw new Error('Während des Ladens wurde ein Turnier geändert. Bitte neu laden.');
    lists = {blitz:results[0],rapid:results[1]}; render(); button.disabled=false;
    status.textContent='Druckvorschau bereit. Änderungen an der Überschrift gelten nur für diesen Aushang.';
  } catch (e) { status.textContent=e.message; }
})();
