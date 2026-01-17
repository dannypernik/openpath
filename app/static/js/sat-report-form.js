// Transfer spreadsheet URL to form input
document.getElementById('save-url').addEventListener('click', function (event) {
  var ssUrl = document.getElementById('ss-url-entry').value;
  document.getElementById('spreadsheet_url').value = ssUrl;
});

// Disable submit button on form submit and show loading screen
const form = document.querySelector('form');
const submitButton = form.querySelector('input[type=submit]');
form.addEventListener('submit', function () {
  window.setTimeout('this.disabled=true', 0);
  document.querySelector('.loading-screen').style.display = 'block';
});

// Copy service worker email to clipboard
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('service-email').addEventListener('click', function (event) {
    event.preventDefault();
    var emailText = this.childNodes[0].nodeValue.trim(); //this.innerText;
    navigator.clipboard.writeText(emailText);
    document.getElementById('copy-icon').classList.add('d-none');
    document.getElementById('copy-check').classList.remove('d-none');
    setTimeout(function () {
      document.getElementById('copy-icon').classList.remove('d-none');
      document.getElementById('copy-check').classList.add('d-none');
    }, 1000);
  });
});
