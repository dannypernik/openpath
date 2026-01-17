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
