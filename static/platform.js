'use strict';
const message = document.querySelector('#message');
const button = document.querySelector('#checkout');
const form = document.querySelector('#subscribe');
document.querySelector('#open-club').addEventListener('submit', event => {
  event.preventDefault(); location.assign('/v/' + new FormData(event.target).get('slug') + '/');
});
async function initialize() {
  try {
    const response = await fetch('/api/platform/config', {cache:'no-store'});
    if (!response.ok) throw new Error('Abos können gerade nicht geladen werden.');
    const config = await response.json();
    document.querySelector('#availability').textContent = config.checkout_ready ? 'Wähle deinen Abrechnungszeitraum. Der Gesamtpreis wird vor der Zahlung angezeigt.' : 'Preise und Online-Abos werden noch eingerichtet. Bestehende Vereinsbereiche bleiben erreichbar.';
    button.disabled = !config.checkout_ready;
    for (const price of config.prices || []) {
      const option = form.elements.plan.querySelector('option[value="' + price.plan + '"]');
      option.textContent = new Intl.NumberFormat('de-DE',{style:'currency',currency:price.currency}).format(price.amount / 100) + (price.plan === 'month' ? ' pro Monat' : ' pro Jahr');
    }
  } catch (error) { message.textContent = error.message; }
  const slug = new URLSearchParams(location.search).get('club');
  if (slug && /^[a-z0-9][a-z0-9-]{2,39}$/.test(slug)) {
    message.textContent = 'Zahlung wird geprüft. Dein Vereinsbereich wird nach Zahlungsbestätigung freigeschaltet.';
    for (let attempt=0; attempt<20; attempt++) {
      const result = await fetch('/api/platform/status?slug='+encodeURIComponent(slug),{cache:'no-store'}).then(r=>r.json());
      if (result.ready) {
        const link=document.createElement('a');link.href='/v/'+slug+'/';link.textContent='Dein Vereinsbereich ist bereit. Jetzt anmelden';message.replaceChildren(link);break;
      }
      await new Promise(resolve=>setTimeout(resolve,3000));
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
