'use strict';
const form = document.querySelector('#private-login');
const submit = document.querySelector('#private-submit');
const error = document.querySelector('#login-error');
let setup = false;
const showError = message => { error.textContent = message; error.hidden = false; };
async function initialize() {
  try {
    const response = await fetch('/api/me', {cache: 'no-store'});
    if (!response.ok) throw new Error('Verbindung fehlgeschlagen. Bitte neu laden.');
    const me = await response.json();
    if (me.user) { location.reload(); return; }
    setup = me.needs_setup;
    document.querySelector('#bootstrap-label').hidden = !setup;
    form.elements.token.required = setup;
    submit.textContent = setup ? 'Administrator anlegen →' : 'Anmelden →';
    submit.disabled = false;
  } catch (e) { showError(e.message); }
}
form.addEventListener('submit', async event => {
  event.preventDefault(); submit.disabled = true; error.hidden = true;
  try {
    const response = await fetch(setup ? '/api/setup' : '/api/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form)))
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Anmeldung fehlgeschlagen');
    if (setup) { form.elements.token.value = ''; form.elements.password.value = ''; await initialize(); }
    else location.reload();
  } catch (e) { showError(e.message); }
  finally { submit.disabled = false; }
});
initialize();
