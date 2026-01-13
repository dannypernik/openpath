// Timer per question
let timerInterval = null;
let secondsSpent = 0;
function startTimer() {
  clearInterval(timerInterval);
  secondsSpent = 0;
  timerInterval = setInterval(() => {
    secondsSpent++;
    let min = String(Math.floor(secondsSpent / 60)).padStart(2, '0');
    let sec = String(secondsSpent % 60).padStart(2, '0');
    document.getElementById('timer').textContent = `${min}:${sec}`;
  }, 1000);
}
startTimer();

// Desmos toggle (Math)
const desmosBtn = document.getElementById('desmos-btn');
if (desmosBtn) {
  desmosBtn.addEventListener('click', () => {
    document.querySelector('.practice-main').classList.toggle('with-desmos');
    let desmos = document.querySelector('.desmos-container');
    if (desmos) desmos.style.display = desmos.style.display === 'none' ? 'block' : 'none';
  });
}

// Mark for Review
const markReviewCheckbox = document.getElementById('mark-review-checkbox');
if (markReviewCheckbox) {
  markReviewCheckbox.addEventListener('change', function() {
    document.getElementById('mark-review-label').classList.toggle('marked', this.checked);
  });
}

// Cross-out mode
let crossoutMode = false;
const crossoutBtn = document.getElementById('crossout-mode-btn');
if (crossoutBtn) {
  crossoutBtn.addEventListener('click', () => {
    crossoutMode = !crossoutMode;
    document.getElementById('answer-choices').classList.toggle('crossout-mode', crossoutMode);
    document.querySelectorAll('.crossout-btn').forEach(btn => btn.style.display = crossoutMode ? 'inline' : 'none');
  });
  document.querySelectorAll('.crossout-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      this.parentElement.classList.toggle('crossed-out');
    });
  });
}

// Answer choice selection
document.querySelectorAll('.answer-choice').forEach(choice => {
  choice.addEventListener('click', function() {
    if (!crossoutMode) {
      document.querySelectorAll('.answer-choice').forEach(c => c.classList.remove('selected'));
      this.classList.add('selected');
    }
  });
});

// Highlighter logic
let highlightMode = false;
let lastHighlightColor = "#fff9c4";
let lastUnderline = false;

const highlightModeBtn = document.getElementById('highlight-mode-btn');
if (highlightModeBtn) {
  highlightModeBtn.addEventListener('click', () => {
    highlightMode = !highlightMode;
    highlightModeBtn.classList.toggle('active', highlightMode);
  });
}

// Highlight on selection
const passage = document.getElementById('passage');
if (passage) {
  passage.addEventListener('mouseup', function(e) {
    let selection = window.getSelection();
    if (selection && selection.toString().length > 0) {
      let range = selection.getRangeAt(0);
      if (highlightMode) {
        applyHighlight(range, lastHighlightColor, lastUnderline);
        selection.removeAllRanges();
      } else {
        showHighlightTooltip(e.pageX, e.pageY, range);
      }
    }
  });
}

function showHighlightTooltip(x, y, range) {
  const tooltip = document.getElementById('highlight-tooltip');
  tooltip.style.left = x + 'px';
  tooltip.style.top = y + 'px';
  tooltip.style.display = 'flex';

  // Color buttons
  tooltip.querySelectorAll('.highlight-color').forEach(btn => {
    btn.onclick = () => {
      lastHighlightColor = btn.getAttribute('data-color');
      applyHighlight(range, lastHighlightColor, lastUnderline);
      tooltip.style.display = 'none';
      window.getSelection().removeAllRanges();
    };
  });
  // Underline
  tooltip.querySelector('.highlight-underline').onclick = () => {
    lastUnderline = !lastUnderline;
    applyHighlight(range, lastHighlightColor, lastUnderline);
    tooltip.style.display = 'none';
    window.getSelection().removeAllRanges();
  };
  // Delete highlight (removes highlight from selection)
  tooltip.querySelector('.highlight-delete').onclick = () => {
    removeHighlight(range);
    tooltip.style.display = 'none';
    window.getSelection().removeAllRanges();
  };
  // Add note (not implemented)
  tooltip.querySelector('.highlight-add-note').onclick = () => {
    alert('Add note feature coming soon!');
    tooltip.style.display = 'none';
  };
}

// Hide tooltip on click elsewhere
document.addEventListener('mousedown', function(e) {
  const tooltip = document.getElementById('highlight-tooltip');
  if (!tooltip.contains(e.target)) {
    tooltip.style.display = 'none';
  }
});

// Highlight application
function applyHighlight(range, color, underline) {
  let span = document.createElement('span');
  span.className = 'highlighted';
  span.style.background = color;
  span.setAttribute('data-color', color);
  if (underline) span.classList.add('underline');
  span.appendChild(range.extractContents());
  range.insertNode(span);
}

// Remove highlight from selection
function removeHighlight(range) {
  // Simple version: unwrap all .highlighted spans in range
  let contents = range.cloneContents();
  let spans = contents.querySelectorAll('.highlighted');
  spans.forEach(span => {
    let parent = span.parentNode;
    while (span.firstChild) parent.insertBefore(span.firstChild, span);
    parent.removeChild(span);
  });
}