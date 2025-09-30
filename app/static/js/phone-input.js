document.addEventListener('DOMContentLoaded', function () {
  const phoneInputs = document.querySelectorAll('input[type="tel"]');

  phoneInputs.forEach((input) => {
    input.value = '+1';

    input.addEventListener('input', function () {
      let value = input.value.replace(/\D/g, ''); // Remove all non-digit characters
      if (value.length > 13) {
        value = value.slice(0, 13); // Prevent more than 13 digits
      }

      let formattedValue = '';
      let countryCodeLength = 0;

      // Determine the length of the country code
      if (value.length === 11) {
        countryCodeLength = 1; // 1-digit country code
      } else if (value.length === 12) {
        countryCodeLength = 2; // 2-digit country code
      } else if (value.length === 13) {
        countryCodeLength = 3; // 3-digit country code
      }

      // Format the phone number
      if (countryCodeLength > 0) {
        formattedValue = `+${value.slice(0, countryCodeLength)} `;
        if (value.length > countryCodeLength) {
          formattedValue += `(${value.slice(countryCodeLength, countryCodeLength + 3)}`;
        }
        if (value.length > countryCodeLength + 3) {
          formattedValue += `) ${value.slice(countryCodeLength + 3, countryCodeLength + 6)}`;
        }
        if (value.length > countryCodeLength + 6) {
          formattedValue += `-${value.slice(countryCodeLength + 6, countryCodeLength + 10)}`;
        }
      } else {
        // Default formatting for numbers shorter than 11 digits
        formattedValue = `+${value.slice(0, 1)} `;
        if (value.length > 1) {
          formattedValue += `(${value.slice(1, 4)}`;
        }
        if (value.length > 4) {
          formattedValue += `) ${value.slice(4, 7)}`;
        }
        if (value.length > 7) {
          formattedValue += `-${value.slice(7, 11)}`;
        }
      }

      input.value = formattedValue.trim();
    });

    input.addEventListener('blur', function () {
      // Ensure the input is valid when the user leaves the field
      if (!input.value.match(/^\+\d{1,3} \(\d{3}\) \d{3}-\d{4}$/)) {
        input.value = ''; // Clear the input if it doesn't match the required format
      }
    });
  });
});
