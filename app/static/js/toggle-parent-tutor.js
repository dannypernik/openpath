const role = document.getElementById('role');
const parentDiv = document.getElementById('parent-div');
const tutorDiv = document.getElementById('tutor-div');
const gradYearDiv = document.getElementById('grad-year-div');

if (role.value == 'student') {
  parentDiv.style.display = 'block';
  tutorDiv.style.display = 'block';
  gradYearDiv.style.display = 'block';
} else {
  parentDiv.style.display = 'none';
  tutorDiv.style.display = 'none';
  gradYearDiv.style.display = 'none';
}

role.addEventListener("change", function () {
  if (this.value == 'student') {
    parentDiv.style.display = 'block';
    tutorDiv.style.display = 'block';
    gradYearDiv.style.display = 'block';
  } else {
    parentDiv.style.display = 'none';
    tutorDiv.style.display = 'none';
    gradYearDiv.style.display = 'none';
    document.getElementById('parent_id').value = 0;
    document.getElementById('tutor_id').value = 0;
    document.getElementById('grad_year').value = 0;
  }
});