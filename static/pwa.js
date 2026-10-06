'use strict';
const mountPwa = location.pathname.match(/^\/v\/[a-z0-9-]+/)?.[0] || '';
let installPrompt = null;
const standalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register(mountPwa + '/sw.js', {scope: mountPwa + '/', updateViaCache: 'none'}).catch(() => {});
}
const installButton = document.querySelector('#pwa-install');
const installDialog = document.querySelector('#pwa-dialog');
installButton.hidden = standalone();
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault(); installPrompt = event; installButton.hidden = false;
});
window.addEventListener('appinstalled', () => { installPrompt = null; installButton.hidden = true; });
installButton.addEventListener('click', async () => {
  if (installPrompt) {
    const prompt = installPrompt; installPrompt = null;
    await prompt.prompt(); await prompt.userChoice;
  } else {
    installDialog.showModal();
  }
});
document.querySelector('#pwa-close').addEventListener('click', () => installDialog.close());
installDialog.addEventListener('click', event => { if (event.target === installDialog) installDialog.close(); });
