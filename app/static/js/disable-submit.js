const forms = document.querySelectorAll('form');
const form1 = forms[0];
const form2 = forms[1];

if (form1) form1.querySelectorAll('input[type=submit]').forEach(e => e.disabled = true);
if (form2) form2.querySelectorAll('input[type=submit]').forEach(e => e.disabled = true);

let isCaptchaPassed = false;
let isCaptcha2Passed = false;

function requiresCaptcha(form, callbackName) {
  let captcha = form.querySelector('.h-captcha[data-callback="' + callbackName + '"]');
  return !!captcha;
}

function checkFormCompletion(targetForm, isCaptcha, callbackName) {
  let isFormComplete = true;
  targetForm.querySelectorAll('input').forEach(function (input) {
    if (input.hasAttribute('required') && (input.value === '' || (input.type === 'file' && input.files.length === 0))) {
      isFormComplete = false;
    }
  });

  // Check required textareas
  targetForm.querySelectorAll('textarea').forEach(function (textarea) {
    if (textarea.hasAttribute('required') && textarea.value === '') {
      isFormComplete = false;
    }
  });

  let needsCaptcha = requiresCaptcha(targetForm, callbackName);
  let enable = isFormComplete && (!needsCaptcha || isCaptcha);

  targetForm.querySelectorAll('input[type=submit]').forEach(function (btn) {
    btn.disabled = !enable;
  });
}

// Attach input listeners to each form's inputs and textareas
if (form1) {
  form1.querySelectorAll('input, textarea').forEach(function (input) {
    input.addEventListener('input', function () {
      checkFormCompletion(form1, isCaptchaPassed, 'captchaPassed');
    });
  });
}
if (form2) {
  form2.querySelectorAll('input, textarea').forEach(function (input) {
    input.addEventListener('input', function () {
      checkFormCompletion(form2, isCaptcha2Passed, 'captcha2Passed');
    });
  });
}

// Captcha callbacks
function captchaPassed(response) {
  isCaptchaPassed = true;
  if (form1) checkFormCompletion(form1, isCaptchaPassed, 'captchaPassed');
  return response;
}

function captcha2Passed(response) {
  isCaptcha2Passed = true;
  if (form2) checkFormCompletion(form2, isCaptcha2Passed, 'captcha2Passed');
  return response;
}