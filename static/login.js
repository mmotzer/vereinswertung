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
    if (me.request_email) {
      document.querySelector('#request-access-link').href = 'mailto:'+me.request_email+'?subject='+encodeURIComponent('Mitgliederzugang · SK1912 Vereinswertung')+'&body='+encodeURIComponent('Hallo,\n\nich möchte einen Mitgliederzugang zur Vereinswertung anfragen.\n\nMein Name:\nGewünschter Benutzername:\nMein Lichess-Name:\n\nBitte kein Passwort per E-Mail senden.\n');
      document.querySelector('#request-access').hidden = false;
    }
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

const registration=document.querySelector('#member-register');
registration.addEventListener('submit',async event => {
  event.preventDefault();const button=event.submitter;button.disabled=true;
  const message=document.querySelector('#register-message');message.hidden=false;
  try {
    const data=Object.fromEntries(new FormData(registration));
    if (data.password!==data.repeat) throw new Error('Die Passwörter stimmen nicht überein.');
    delete data.repeat;
    const response=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();
    if (!response.ok) throw new Error(result.error || 'Registrierung fehlgeschlagen');
    form.elements.username.value=data.username;registration.reset();
    message.className='success';message.textContent='Zugang angelegt. Du kannst dich oben mit deinem Benutzernamen und Passwort anmelden.';
    form.scrollIntoView({behavior:'smooth',block:'start'});
  } catch(e) {message.className='error';message.textContent=e.message;}
  finally {button.disabled=false;}
});
