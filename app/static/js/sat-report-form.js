function checkFormCompletion() {
  var form = document.querySelector('form');
  var isFormComplete = true;
  console.log('checking form completion');
  form.querySelectorAll('input').forEach(function (input) {
    if (input.hasAttribute('required') && (input.value === '' || (input.type === 'file' && input.files.length === 0))) {
      isFormComplete = false;
      console.log(input.name + ' is empty');
    }
  });

  if (isFormComplete && isCaptchaPassed) {
    form.querySelector('input[type=submit]').disabled = false;
  } else {
    form.querySelector('input[type=submit]').disabled = true;
  }
}

document.querySelectorAll('input').forEach(function (input) {
  input.addEventListener('input', checkFormCompletion);
});

var isCaptchaPassed = false;
function captchaPassed(response) {
  isCaptchaPassed = true;
  checkFormCompletion();
  console.log(response);
  return response;
}

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
