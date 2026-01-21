const input = document.querySelectorAll("input[type='tel']");
input.forEach((tel) => {
  const iti = window.intlTelInput(tel, {
    loadUtils: () => import('https://cdn.jsdelivr.net/npm/intl-tel-input@25.13.1/build/js/utils.js'),
    initialCountry: 'us',
    countryOrder: ['ca', 'mx', 'gb'],
  });

  // Create or select a hidden input for the formatted phone number
  let hidden = tel.parentNode.querySelector("input[type='hidden'][data-for='" + tel.name + "']");
  if (!hidden) {
    hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = tel.name + '_formatted';
    hidden.setAttribute('data-for', tel.name);
    tel.parentNode.insertBefore(hidden, tel.nextSibling);
  }

  const form = tel.closest('form');
  if (form) {
    form.addEventListener('submit', function () {
      hidden.value = tel.value;
      tel.value = iti.getNumber();
    });
  }
});
