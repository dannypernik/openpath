const input = document.querySelectorAll("input[type='tel']");
input.forEach((tel) => {
  const iti = window.intlTelInput(tel, {
    loadUtils: () => import('https://cdn.jsdelivr.net/npm/intl-tel-input@25.13.1/build/js/utils.js'),
    initialCountry: 'us',
    countryOrder: ['ca', 'mx', 'gb'],
  });

  const form = tel.closest('form');
  if (form) {
    form.addEventListener('submit', function () {
      tel.value = iti.getNumber();
    });
  }
});
