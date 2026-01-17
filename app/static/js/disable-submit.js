// Get both forms by order in DOM
var forms = document.querySelectorAll('form');
var form1 = forms[0];
var form2 = forms[1];

// Disable submit buttons initially
if (form1) form1.querySelectorAll('input[type=submit]').forEach(e => e.disabled = true);
if (form2) form2.querySelectorAll('input[type=submit]').forEach(e => e.disabled = true);

var isCaptchaPassed = false;
var isCaptcha2Passed = false;

function checkFormCompletion(targetForm, isCaptcha) {
  var isFormComplete = true;
  targetForm.querySelectorAll('input').forEach(function (input) {
    if (input.hasAttribute('required') && (input.value === '' || (input.type === 'file' && input.files.length === 0))) {
      isFormComplete = false;
    }
  });

  targetForm.querySelectorAll('input[type=submit]').forEach(function (btn) {
    btn.disabled = !(isFormComplete && isCaptcha);
  });
}

// Attach input listeners to each form's inputs
if (form1) {
  form1.querySelectorAll('input').forEach(function (input) {
    input.addEventListener('input', function () {
      checkFormCompletion(form1, isCaptchaPassed);
    });
  });
}
if (form2) {
  form2.querySelectorAll('input').forEach(function (input) {
    input.addEventListener('input', function () {
      checkFormCompletion(form2, isCaptcha2Passed);
    });
  });
}

// Captcha callbacks
function captchaPassed(response) {
  isCaptchaPassed = true;
  if (form1) checkFormCompletion(form1, isCaptchaPassed);
  return response;
}

function captcha2Passed(response) {
  isCaptcha2Passed = true;
  if (form2) checkFormCompletion(form2, isCaptcha2Passed);
  return response;
}