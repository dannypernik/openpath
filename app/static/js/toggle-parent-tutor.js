const role = document.getElementById('role');
const parentDiv = document.getElementById('parent-div');
const tutorDiv = document.getElementById('tutor-div');
const gradYearDiv = document.getElementById('grad-year-div');
const titleDiv = document.getElementById('title-div');

if (role.value == 'student') {
  parentDiv.style.display = 'block';
  tutorDiv.style.display = 'block';
  gradYearDiv.style.display = 'block';
} else {
  parentDiv.style.display = 'none';
  tutorDiv.style.display = 'none';
  gradYearDiv.style.display = 'none';
}

if (role.value == 'tutor' || role.value == 'admin') {
  titleDiv.style.display = 'block';
} else {
  titleDiv.style.display = 'none';
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

  if (this.value == 'tutor' || this.value == 'admin') {
    titleDiv.style.display = 'block';
  } else {
    titleDiv.style.display = 'none';
  }
});
