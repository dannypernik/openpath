const form = document.querySelector('form');
const submitButton = form.querySelector('input[type=submit]');
form.addEventListener('submit', function () {
  submitButton.setAttribute('disabled', 'true');
});
