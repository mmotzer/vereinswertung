'use strict';
let tenantDomain='';
const message = document.querySelector('#message');
const button = document.querySelector('#checkout');
const form = document.querySelector('#subscribe');
const signupRoute = location.pathname === '/start';
for (const id of ['product-hero','benefits','try','product-faq','club-entry']) document.getElementById(id).hidden=signupRoute;
document.querySelector('#signup-panel').hidden=!signupRoute;
if(signupRoute)document.title='Verein einrichten · Vereinswertung';
document.querySelector('#open-club').addEventListener('submit', event => {
  event.preventDefault(); const slug=new FormData(event.target).get('slug');location.assign(tenantDomain ? 'https://'+slug+'.'+tenantDomain+'/' : '/v/'+slug+'/');
});
async function initialize() {
  try {
    const response = await fetch('/api/platform/config', {cache:'no-store'});
    if (!response.ok) throw new Error('Abos können gerade nicht geladen werden.');
    const config = await response.json();tenantDomain=config.tenant_domain || '';
    document.querySelector('#availability').textContent = config.checkout_ready ? 'Wähle deinen Abrechnungszeitraum. Der Gesamtpreis wird vor der Zahlung angezeigt.' : 'Preise und Online-Abos werden noch eingerichtet. Bestehende Vereinsbereiche bleiben erreichbar.';
    button.disabled = !config.checkout_ready;
    for (const price of config.prices || []) {
      const option = form.elements.plan.querySelector('option[value="' + price.plan + '"]');
      option.textContent = new Intl.NumberFormat('de-DE',{style:'currency',currency:price.currency}).format(price.amount / 100) + (price.plan === 'month' ? ' pro Monat' : ' pro Jahr');
    }
  } catch (error) { message.textContent = error.message; }
  const params=new URLSearchParams(location.search);
  if(params.get('cancelled')) {document.querySelector('#signup-panel').hidden=false;message.textContent='Zahlung abgebrochen. Es wurde kein Vereinsbereich freigeschaltet. Du kannst die Einrichtung mit denselben Angaben erneut beginnen.';}
  const slug = params.get('club');
  if (slug && /^[a-z0-9][a-z0-9-]{2,39}$/.test(slug)) {
    document.querySelector('#signup-panel').hidden=false;
    document.querySelector('#subscribe').hidden=true;
    message.textContent = 'Zahlung wird geprüft. Dein Vereinsbereich wird nach Zahlungsbestätigung freigeschaltet.';
    for (let attempt=0; attempt<20; attempt++) {
      let result;
      try{const response=await fetch('/api/platform/status?slug='+encodeURIComponent(slug),{cache:'no-store'});if(!response.ok)throw new Error();result=await response.json();}
      catch(error){message.textContent='Die Verbindung wurde unterbrochen. Bitte diese Seite erneut laden, um die Freischaltung zu prüfen.';break;}
      if (result.ready) {
        const link=document.createElement('a');link.href=result.url || '/v/'+slug+'/';link.textContent='Dein Vereinsbereich ist bereit. Jetzt anmelden';message.replaceChildren(link);break;
      }
      if(attempt===19)message.textContent='Die Freischaltung dauert noch. Bitte diese Seite später erneut laden. Registriere den Verein nicht nochmals mit einem anderen Kürzel.';
      else await new Promise(resolve=>setTimeout(resolve,3000));
    }
  }
}
form.addEventListener('submit', async event => {
  event.preventDefault(); button.disabled=true;
  try {
    const data=Object.fromEntries(new FormData(form));
    if (data.password!==data.repeat) throw new Error('Die Passwörter stimmen nicht überein.');
    delete data.repeat;data.terms=form.elements.terms.checked;
    const response=await fetch('/api/platform/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();if (!response.ok) throw new Error(result.error || 'Zahlung konnte nicht gestartet werden.');
    location.assign(result.url);
  } catch (error) { message.textContent=error.message;button.disabled=false; }
});
initialize();

const trialFile=document.querySelector('#trial-file'),trialButton=document.querySelector('#trial-button');
trialFile.addEventListener('change',()=>{trialButton.textContent=trialFile.files.length?'Eigenes Turnier berechnen':'Beispielturnier berechnen';});
function node(tag,text,className) {const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
document.querySelector('#trial-form').addEventListener('submit',async event=>{
 event.preventDefault();trialButton.disabled=true;const status=document.querySelector('#trial-message'),panel=document.querySelector('#trial-result');
 status.textContent='Turnier wird geprüft und berechnet …';panel.hidden=true;
 try {
  const file=trialFile.files[0],data={sample:!file,category:document.querySelector('#trial-category').value};
  const day=document.querySelector('#trial-day').value;if(day)data.day=day;
  const dates=document.querySelector('#trial-dates').value.trim();if(dates)data.round_dates=dates.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
  if(file){if(file.size>1048576)throw new Error('Die TRF-Datei darf höchstens 1 MB groß sein.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let start=0;start<bytes.length;start+=8192)binary+=String.fromCharCode(...bytes.subarray(start,start+8192));data.content=btoa(binary);}
  const response=await fetch('/api/platform/try',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Probeimport fehlgeschlagen.');
  panel.replaceChildren(node('h3',result.name),node('p',`${result.players.length} Spieler · ${result.games} gespielte Partien · ${result.rounds} Runden`));
  const table=node('table'),head=node('thead'),header=node('tr');for(const text of ['Spieler','Testwertung','Partien','Seit Start'])header.append(node('th',text));head.append(header);table.append(head);
  const body=node('tbody');for(const player of result.players){const row=node('tr');for(const text of [player.name,player.rating+' ?',player.games,(player.change>0?'+':'')+player.change])row.append(node('td',String(text)));body.append(row);}table.append(body);const wrapper=node('div',undefined,'trial-table');wrapper.append(table);panel.append(wrapper);
  const mobile=node('div',undefined,'trial-mobile');for(const player of result.players){const card=node('article',undefined,'trial-player'),stats=node('dl');card.append(node('h4',player.name));for(const [label,value] of [['Testwertung',player.rating+' ?'],['Partien',player.games],['Seit Start',(player.change>0?'+':'')+player.change]]){const item=node('div');item.append(node('dt',label),node('dd',String(value)));stats.append(item);}card.append(stats);mobile.append(card);}panel.append(mobile);
  panel.append(node('p','Alle Spieler beginnen hier bei 1500. Die Testwertungen sind vorläufig; große Änderungen nach wenigen Partien sind normal. Im echten Vereinsbereich wird mit dem gespeicherten Stand weitergerechnet.','note'));
  if(result.skipped.length)panel.append(node('p',result.skipped.length+' Einträge ohne gespielte Partie wurden ausgelassen.','note'));
  for(const warning of result.warnings)panel.append(node('p',warning,'note'));
  const action=node('a','Eigenen Vereinsbereich anlegen →','button');action.href='/start';panel.append(action,node('p','Der Test wurde nicht gespeichert. Nach der Einrichtung importierst du deine TRF im geschützten Vereinsbereich.','note'));
  panel.hidden=false;status.textContent='Probeimport fertig. Ergebnisse stehen direkt darunter.';panel.scrollIntoView({behavior:'smooth',block:'start'});panel.tabIndex=-1;panel.focus({preventScroll:true});
 }catch(error){status.textContent=error.message;status.scrollIntoView({behavior:'smooth',block:'center'});}
 finally{trialButton.disabled=false;}
});
