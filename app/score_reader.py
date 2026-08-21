import datetime
from bs4 import BeautifulSoup
from collections import Counter
import pdfplumber
import re
import pprint
from markupsafe import Markup
from flask import flash
import logging

pp = pprint.PrettyPrinter(indent=2, width=100)

def get_student_answers(score_details_file_path):
  """
  Extract student answers from a SAT practice test score details PDF.

  Parses a pdfplumber-opened PDF file containing test score details and extracts:
  - Test metadata (code, display name, date)
  - Reading/Writing and Math answers for both modules
  - Student responses, correct answers, and correctness status
  - Question attempt counts and completion status

  Rows are reconstructed from word bounding boxes rather than pdfplumber's
  line-clustered text. Wrapped Domain cells (e.g. "Problem-Solving and Data
  Analysis") and multi-line grid-in answer keys (e.g. accepted answers stacked
  across lines) otherwise land on the same y-coordinate as neighboring rows,
  which scrambles pdfplumber's text-line output and silently drops or
  corrupts data — including across a PDF page break.

  Args:
    score_details_file_path (str): File path to the score details PDF.

  Returns:
    dict: Score details containing:
      - test_code (str): Test identifier (e.g., 'psat1')
      - test_display_name (str): Human-readable test name (e.g., 'PSAT 1')
      - date (str): Test date in 'YYYY.MM.DD' format
      - is_rw_found (bool): Whether Reading/Writing data was found
      - is_math_found (bool): Whether Math data was found
      - rw_score (int): Reading/Writing score
      - math_score (int): Math score
      - is_rw_hard (bool): Whether RW was hard/adaptive module
      - is_math_hard (bool): Whether Math was hard/adaptive module
      - has_omits (bool): Whether any questions were omitted
      - rw_questions_answered (int): Count of RW questions answered
      - math_questions_answered (int): Count of Math questions answered
      - answer_key_mismatches (list): Discrepancies found
      - missing_data (list): Missing data issues
      - answers (dict): Nested structure with answers by subject/module/question number
    str: "invalid" if date cannot be extracted

  Raises:
    ValueError: If test number > 11, insufficient questions found, or too few questions answered.
  """
  total_questions = {
    'rw': {'questions': 27},
    'math': {'questions': 22}
  }
  pdf = pdfplumber.open(score_details_file_path)
  pages = pdf.pages

  score_details_data = {
    'test_code': None,
    'test_display_name': None,
    'date': None,
    'is_rw_found': False,
    'is_math_found': False,
    'rw_score': 100,
    'math_score': 100,
    'is_rw_hard': None,
    'is_math_hard': None,
    'has_omits': False,
    'answer_key_mismatches': [],
    'missing_data': [],
    'answers': {
      'rw': {
        '1': {},
        '2': {}
      },
      'math': {
        '1': {},
        '2': {}
      },
    },
  }

  # Test date/code come from the "My Tests / <Type> <N> - <Date>" breadcrumb,
  # which is plain unwrapped text on the first page.
  date = None
  test_number = None
  first_page_text = pages[0].extract_text() or ''
  for line in first_page_text.split('\n'):
    if line.find('My Tests') != -1:
      trimmed_line = line.rstrip()
      date_start = trimmed_line.find(' - ') + 3
      date_str = trimmed_line[date_start:]
      date = datetime.datetime.strptime(date_str, '%B %d, %Y').strftime('%Y.%m.%d')
      score_details_data['date'] = date

      test_type_start = line.find('My Tests') + 11
      sep = {'/', ' '}
      test_type_end = next((i for i, ch in enumerate(line[test_type_start:]) if ch in sep), None) + test_type_start
      test_type = line[test_type_start:test_type_end]
      test_number_end = date_start - 3
      test_number_start = line.rfind(" ", 0, test_number_end) + 1

      test_number = line[test_number_start:test_number_end]
      score_details_data['test_code'] = test_type.lower() + test_number
      score_details_data['test_display_name'] = f'{test_type.upper()} {test_number}'
      break

  # Gather every word on every page, offsetting vertical position by each
  # page's actual height so coordinates stay continuous across a page break
  # (a row split across pages must bucket next to its neighbors, not across
  # an arbitrary gap).
  noise_re = re.compile(r'^(https?://|MyPractice)')
  all_words = []
  cum_offset = 0
  for p in pages:
    words = p.extract_words()
    # The running header/timestamp and footer/page-number are each one text
    # line; drop every word on that line, not just the one matching noise_re,
    # since sibling words on the same line don't themselves start with
    # 'http'/'MyPractice' and would otherwise leak into a row's answer cell.
    noise_tops = {round(w['top'], 1) for w in words if noise_re.match(w['text'])}
    for w in words:
      if round(w['top'], 1) in noise_tops:
        continue
      all_words.append({
        'text': w['text'],
        'x0': w['x0'],
        'top': w['top'] + cum_offset,
      })
    cum_offset += p.height

  # Locate the Question-number column: it's the x0 where 1-99 digit words
  # cluster far more densely than anywhere else (grid-in answers scatter
  # digits elsewhere on the row, but never at this consistent left edge).
  digit_x_counts = Counter()
  for w in all_words:
    if w['text'].isdigit() and 1 <= int(w['text']) <= 99:
      digit_x_counts[round(w['x0'] / 3) * 3] += 1
  question_x = max(digit_x_counts, key=digit_x_counts.get) if digit_x_counts else None

  anchors = sorted(
    (w for w in all_words
     if w['text'].isdigit() and 1 <= int(w['text']) <= 99 and question_x is not None
     and abs(w['x0'] - question_x) <= 6),
    key=lambda w: w['top']
  )

  # "Review" is an exact, unambiguous marker for the Actions column; anything
  # at or past its x0 is the (score-irrelevant) Domain column.
  review_xs = [w['x0'] for w in all_words if w['text'] == 'Review']
  review_x = sum(review_xs) / len(review_xs) if review_xs else float('inf')

  section_words = {'Reading', 'and', 'Writing', 'Math'}

  # A row's own cells (response value, result word) don't reliably render on
  # the same sub-line as its question-number anchor — a wrapped Section or
  # Domain cell can push them a line above or below it. But every row
  # contributes exactly one result word (Correct/Incorrect/Omitted) and, for
  # non-omitted rows, exactly one response value, and rows are never
  # reordered — so matching these word-streams to anchors by document order
  # is robust where nearest-anchor-by-position is not.
  first_top = anchors[0]['top'] if anchors else 0
  results_stream = sorted(
    (w for w in all_words
     if w['text'] in ('Correct', 'Incorrect', 'Omitted')
     and w['x0'] < review_x - 5 and w['top'] >= first_top - 10),
    key=lambda w: w['top']
  )
  responses_stream = sorted(
    (w for w in all_words
     if w['text'].endswith(';') and w['x0'] < review_x - 5 and w['top'] >= first_top - 10),
    key=lambda w: w['top']
  )

  subject = 'rw'
  rw_mod_num = '1'
  m_mod_num = '1'
  subject_totals = {'rw': 0, 'math': 0}
  response_idx = 0

  for i, anchor in enumerate(anchors):
    number = anchor['text']
    prev_top = anchors[i - 1]['top'] if i > 0 else anchor['top'] - 40
    next_top = anchors[i + 1]['top'] if i + 1 < len(anchors) else anchor['top'] + 40
    row_top = (prev_top + anchor['top']) / 2
    row_bottom = (anchor['top'] + next_top) / 2
    row_words = [w for w in all_words if row_top <= w['top'] < row_bottom]

    if any(w['text'] == 'Math' for w in row_words):
      subject = 'math'

    result = results_stream[i]['text'] if i < len(results_stream) else None

    answer_parts = [
      w for w in row_words
      if w is not anchor and w['x0'] < review_x - 5
      and w['text'] not in section_words
      and w['text'] not in ('Correct', 'Incorrect', 'Omitted')
      and not w['text'].endswith(';')
    ]
    answer_parts.sort(key=lambda w: w['top'])
    correct_answer = ''.join(w['text'] for w in answer_parts).rstrip(',') or None

    if result == 'Omitted':
      response = '-'
      score_details_data['has_omits'] = True
    elif result is not None:
      response = responses_stream[response_idx]['text'].rstrip(';') if response_idx < len(responses_stream) else None
      response_idx += 1
    else:
      # No result word means this row's data wasn't captured (e.g. the PDF
      # export was truncated mid-row) — don't guess at correctness.
      response = None

    is_correct = result == 'Correct'

    if score_details_data['answers']['math']['1'].get(number):
      m_mod_num = '2'

    if score_details_data['answers']['rw']['1'].get(number):
      rw_mod_num = '2'

    if subject and number and correct_answer and response and result:
      subject_totals[subject] += 1

      if subject == 'rw':
        module = rw_mod_num
        if not score_details_data['is_rw_found']:
          score_details_data['is_rw_found'] = True
      elif subject == 'math':
        module = m_mod_num
        if not score_details_data['is_math_found']:
          score_details_data['is_math_found'] = True

      score_details_data['answers'][subject][module][number] = {
        'correct_answer': correct_answer,
        'student_answer': response,
        'is_correct': is_correct
      }

  rw_questions_answered = 0
  math_questions_answered = 0

  for sub in ['rw', 'math']:
    for mod in range(1, 3):
      for q in range(1, total_questions[sub]['questions'] + 1):
        if score_details_data['answers'][sub][str(mod)].get(str(q)) is None:
          score_details_data['answers'][sub][str(mod)][str(q)] = {
            'correct_answer': 'not found',
            'student_answer': 'not found',
            'is_correct': False
          }
        elif sub == 'rw' and score_details_data['answers'][sub][str(mod)][str(q)][
          'student_answer'] != '-':
          rw_questions_answered += 1
        elif sub == 'math' and score_details_data['answers'][sub][str(mod)][str(q)][
          'student_answer'] != '-':
          math_questions_answered += 1

  score_details_data['rw_questions_answered'] = rw_questions_answered
  score_details_data['math_questions_answered'] = math_questions_answered

  # pp.pprint(score_details_data)

  if date is None:
    return "invalid"
  elif int(test_number) > 11:
        raise ValueError('Test unavailable')
  # elif subject_totals['math'] < 5:
  #   raise ValueError('Missing math modules')
  elif subject_totals['rw'] <= 30:
    raise ValueError('Error reading score details: missing too many questions')
  # elif subject_totals['math'] < 34:
  #   raise ValueError('Error reading score details: missing Math questions')
  elif rw_questions_answered < 5 and math_questions_answered < 5:
    raise ValueError('Error reading score details: insufficient questions answered')

  return score_details_data


# def read_text_line_by_line(text):
#   for line in text.split('\n'):
#     yield line


def get_data_from_score_report(data, pdf_path):
  pdf = pdfplumber.open(pdf_path)
  pages = pdf.pages

  data['student_name'] = None
  data['rw_score'] = None
  data['math_score'] = None
  data['total_score'] = None

  reportConfirmed = False
  page0 = pages[0].extract_text()

  if page0.replace(' ', '').find('Thispracticescorereportisprovidedby') != -1:
    reportConfirmed = True

  if reportConfirmed:
    try:
      for page in pages:
        text = page.extract_text()
        # print(text)
        # Extract student name
        if not data['student_name']:
          name_start = text.find('Name:') + 5
          if text[5] == ' ':
            name_start = text.find('Name:') + 6
          if name_start >= 4: # -1 + 5 => not found
            name_end = text.find('\n', name_start)
            data['student_name'] = text[name_start:name_end].strip()

            if data['student_name'].find(' ') == -1:
              for char in data['student_name'][1:]:
                if char.isupper():
                  data['student_name'] = data['student_name'].replace(char, ' ' + char)
                  break

        # Extract total score and remaining values
        scores = re.findall(r'(\s\d{3}\s|\s\d{4}\s)', text)
        scores = [int(score) for score in scores if 160 <= int(score) <= 1600]
        if scores:
          data['total_score'] = max(scores)
          remaining_values = [int(value) for value in scores if value != data['total_score']]
          if len(remaining_values) >= 2:
            for i in range(len(remaining_values) - 1):
              for j in range(i+1, len(remaining_values)):
                if remaining_values[i] + remaining_values[j] == data['total_score']:
                  data['rw_score'] = remaining_values[i]
                  data['math_score'] = remaining_values[j]
                  break
              if not data['rw_score']:
                break

        # Find lines that start with SAT or PSAT
        sat_lines = [line for line in text.split('\n') if line.startswith('SAT') or line.startswith('PSAT')]
        valid_sat_lines = [line for line in sat_lines if line.endswith(tuple(str(year) for year in range(2020, 2100)))]
        sat_line = valid_sat_lines[0] if valid_sat_lines else None
        title_line = sat_line.rstrip() if sat_line else None # ensures no trailing whitespace
        if title_line:
          test_type = sat_line[0:sat_line.find('SAT') + 3]
        test_number_start = sat_line.find('Practice') + 9
        test_number_end = sat_line.find(' ', test_number_start)
        test_number = sat_line[test_number_start:test_number_end]
        test_code = test_type.lower() + test_number

        date_start = sat_line.find(' ', test_number_end) + 1
        date_str_condensed = sat_line[date_start:].replace(' ', '')
        date = datetime.datetime.strptime(date_str_condensed, '%B%d,%Y').strftime('%Y.%m.%d')
      if date != data['date'] or test_code != data['test_code']:
        raise ValueError(f'Score report error: date or test code mismatch. {date} != {data["date"]} or {test_code} != {data["test_code"]}')
      if not data['rw_score'] or not data['math_score']:
        raise ValueError('Score report error: rw_score or math_score not found')
      return data
    except Exception as e:
      logging.error(f'Error reading score report: {e}')
      raise
  else:
    raise FileNotFoundError('Score Report PDF does not match expected format')


def get_mod_difficulty(score_details_data):
  mod_diffs = {
    'sat1': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'D',
      }

    },
    'sat2': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'A',
      },
      'm': {
        'diff_question': '3',
        'easy_answer': 'B',
        'hard_answer': 'C',
      }
    },
    'sat3': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'sat4': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'D',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'sat5': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': '2',
        'easy_answer': 'C',
        'hard_answer': 'B',
      }
    },
    'sat6': {
      'rw': {
        'diff_question': '2',
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': '2',
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'sat7': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'A',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'A',
        'hard_answer': 'D',
      }
    },
    'sat8': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'C',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '2',
        'easy_answer': 'D',
        'hard_answer': 'C',
      }
    },
    'sat9': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '2',
        'easy_answer': 'C',
        'hard_answer': 'B',
      }
    },
    'sat10': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'A',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '2',
        'easy_answer': 'C',
        'hard_answer': 'B',
      }
    },
    'sat11': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'C',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': '4',
        'hard_answer': 'B',
      }
    },
    'psat1': {
      'rw': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': 'C',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'C',
        'hard_answer': 'A',
      }
    },
    'psat2': {
      'rw': {
        'diff_question': '2',
        'easy_answer': 'C',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': '1',
        'easy_answer': 'B',
        'hard_answer': '7',
      }
    },
  }

  easy_rw_diff_answer = mod_diffs[score_details_data['test_code']]['rw']['easy_answer']
  hard_rw_diff_answer = mod_diffs[score_details_data['test_code']]['rw']['hard_answer']
  pdf_rw_diff_answer = score_details_data['answers']['rw']['2'][mod_diffs[score_details_data['test_code']]['rw']['diff_question']]['correct_answer']
  if hard_rw_diff_answer == pdf_rw_diff_answer:
    score_details_data['is_rw_hard'] = True
  elif easy_rw_diff_answer == pdf_rw_diff_answer:
    score_details_data['is_rw_hard'] = False
  else:
    score_details_data['is_rw_hard'] = None

  easy_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['easy_answer']
  hard_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['hard_answer']
  pdf_m_diff_answer = score_details_data['answers']['math']['2'][mod_diffs[score_details_data['test_code']]['m']['diff_question']]['correct_answer']
  if hard_m_diff_answer == pdf_m_diff_answer:
    score_details_data['is_math_hard'] = True
  elif easy_m_diff_answer == pdf_m_diff_answer:
    score_details_data['is_math_hard'] = False
  else:
    score_details_data['is_math_hard'] = None

  return score_details_data


def print_answer_key(score_details_data):
  answer_key = {
    'test_code': score_details_data['test_code'],
    'is_rw_hard': score_details_data['is_rw_hard'],
    'is_math_hard': score_details_data['is_math_hard'],
    'rw': {
      '1': {},
      '2': {}
    },
    'math': {
      '1': {},
      '2': {}
    }
  }
  for sub in score_details_data['answers']:
    for mod in score_details_data['answers'][sub]:
      for q in score_details_data['answers'][sub][mod]:
        correct_answer = score_details_data['answers'][sub][mod][q]['correct_answer'].rstrip(',')
        answer_key[sub][mod][q] = correct_answer
  pp.pprint(answer_key)


def check_answer_key(score_details_data):
  answer_key = {
    'sat1': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'C',
          '3': 'C',
          '4': 'B',
          '5': 'C',
          '6': 'D',
          '7': 'D',
          '8': 'D',
          '9': 'B',
          '10': 'C',
          '11': 'D',
          '12': 'C',
          '13': 'A',
          '14': 'D',
          '15': 'B',
          '16': 'B',
          '17': 'D',
          '18': 'A',
          '19': 'C',
          '20': 'D',
          '21': 'C',
          '22': 'D',
          '23': 'A',
          '24': 'D',
          '25': 'C',
          '26': 'B',
          '27': 'A'
        },
        '2': {
          '1': 'C',
          '2': 'D',
          '3': 'B',
          '4': 'D',
          '5': 'A',
          '6': 'A',
          '7': 'C',
          '8': 'D',
          '9': 'B',
          '10': 'C',
          '11': 'C',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'A',
          '16': 'D',
          '17': 'A',
          '18': 'A',
          '19': 'A',
          '20': 'C',
          '21': 'B',
          '22': 'D',
          '23': 'A',
          '24': 'C',
          '25': 'A',
          '26': 'A',
          '27': 'D'
        },
        '3': {
          '1': 'B',
          '2': 'A',
          '3': 'B',
          '4': 'C',
          '5': 'D',
          '6': 'B',
          '7': 'D',
          '8': 'B',
          '9': 'D',
          '10': 'B',
          '11': 'A',
          '12': 'A',
          '13': 'D',
          '14': 'D',
          '15': 'D',
          '16': 'B',
          '17': 'D',
          '18': 'D',
          '19': 'C',
          '20': 'A',
          '21': 'B',
          '22': 'A',
          '23': 'A',
          '24': 'B',
          '25': 'D',
          '26': 'C',
          '27': 'A'
        }
      },
      'math': {
        '1': {
          '1': 'A',
          '2': 'B',
          '3': 'A',
          '4': 'D',
          '5': 'A',
          '6': '0.3',
          '7': 'C',
          '8': '5',
          '9': 'B',
          '10': 'A',
          '11': 'B',
          '12': 'B',
          '13': 'C',
          '14': 'B',
          '15': '40',
          '16': 'D',
          '17': 'C',
          '18': 'A',
          '19': '.8823',
          '20': '25/4',
          '21': '24',
          '22': '20.25'
        },
        '2': {
          '1': 'B',
          '2': '55',
          '3': 'C',
          '4': 'B',
          '5': 'D',
          '6': 'A',
          '7': '240',
          '8': 'B',
          '9': '27',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': '47',
          '14': 'D',
          '15': 'A',
          '16': 'C',
          '17': 'D',
          '18': 'D',
          '19': 'B',
          '20': 'D',
          '21': 'A',
          '22': 'D'
        },
        '3': {
          '1': 'D',
          '2': 'D',
          '3': '60',
          '4': 'C',
          '5': 'A',
          '6': 'B',
          '7': 'D',
          '8': 'B',
          '9': '16',
          '10': 'B',
          '11': 'A',
          '12': 'C',
          '13': 'B',
          '14': 'A',
          '15': 'A',
          '16': 'B',
          '17': '8',
          '18': 'C',
          '19': 'D',
          '20': '52',
          '21': 'A',
          '22': 'D'
        }
      }
    },
    'sat2': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'C',
          '3': 'B',
          '4': 'C',
          '5': 'A',
          '6': 'B',
          '7': 'A',
          '8': 'D',
          '9': 'D',
          '10': 'A',
          '11': 'A',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'C',
          '16': 'B',
          '17': 'D',
          '18': 'A',
          '19': 'C',
          '20': 'D',
          '21': 'A',
          '22': 'B',
          '23': 'C',
          '24': 'C',
          '25': 'C',
          '26': 'D',
          '27': 'C'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': 'D',
          '4': 'D',
          '5': 'A',
          '6': 'B',
          '7': 'C',
          '8': 'D',
          '9': 'C',
          '10': 'A',
          '11': 'D',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'B',
          '16': 'B',
          '17': 'C',
          '18': 'C',
          '19': 'D',
          '20': 'C',
          '21': 'A',
          '22': 'B',
          '23': 'A',
          '24': 'A',
          '25': 'B',
          '26': 'A',
          '27': 'D'
        },
        '3': {
          '1': 'A',
          '2': 'B',
          '3': 'D',
          '4': 'C',
          '5': 'B',
          '6': 'A',
          '7': 'D',
          '8': 'D',
          '9': 'B',
          '10': 'C',
          '11': 'C',
          '12': 'C',
          '13': 'B',
          '14': 'C',
          '15': 'C',
          '16': 'C',
          '17': 'B',
          '18': 'B',
          '19': 'B',
          '20': 'D',
          '21': 'A',
          '22': 'B',
          '23': 'D',
          '24': 'A',
          '25': 'C',
          '26': 'A',
          '27': 'D'
        }
      },
      'math': {
        '1': {
          '1': 'C',
          '2': 'D',
          '3': '9',
          '4': 'A',
          '5': 'D',
          '6': '52',
          '7': 'D',
          '8': 'B',
          '9': 'B',
          '10': 'C',
          '11': '11875',
          '12': 'C',
          '13': 'B',
          '14': '410',
          '15': 'A',
          '16': '.5',
          '17': '100',
          '18': 'B',
          '19': 'D',
          '20': 'A',
          '21': 'B',
          '22': 'C'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': 'B',
          '4': 'C',
          '5': '192',
          '6': '50',
          '7': 'D',
          '8': '10',
          '9': '15',
          '10': 'D',
          '11': 'A',
          '12': 'D',
          '13': 'A',
          '14': 'A',
          '15': 'D',
          '16': '986',
          '17': 'C',
          '18': 'A',
          '19': 'D',
          '20': 'A',
          '21': 'D',
          '22': 'C'
        },
        '3': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'A',
          '5': 'C',
          '6': '3',
          '7': 'D',
          '8': '113',
          '9': 'A',
          '10': 'C',
          '11': 'C',
          '12': '29/3',
          '13': 'A',
          '14': 'A',
          '15': '33',
          '16': '8',
          '17': 'A',
          '18': 'B',
          '19': 'A',
          '20': '-34',
          '21': 'D',
          '22': 'D'
        }
      }
    },
    'sat3': {
      'rw': {
        '1': {
          '1': 'B',
          '2': 'D',
          '3': 'C',
          '4': 'B',
          '5': 'A',
          '6': 'D',
          '7': 'A',
          '8': 'A',
          '9': 'A',
          '10': 'D',
          '11': 'A',
          '12': 'B',
          '13': 'A',
          '14': 'C',
          '15': 'A',
          '16': 'D',
          '17': 'D',
          '18': 'D',
          '19': 'C',
          '20': 'C',
          '21': 'B',
          '22': 'D',
          '23': 'C',
          '24': 'A',
          '25': 'D',
          '26': 'D',
          '27': 'C'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'B',
          '5': 'D',
          '6': 'A',
          '7': 'D',
          '8': 'A',
          '9': 'A',
          '10': 'C',
          '11': 'C',
          '12': 'C',
          '13': 'B',
          '14': 'D',
          '15': 'A',
          '16': 'D',
          '17': 'A',
          '18': 'B',
          '19': 'B',
          '20': 'A',
          '21': 'D',
          '22': 'D',
          '23': 'D',
          '24': 'A',
          '25': 'C',
          '26': 'B',
          '27': 'D'
        },
        '3': {
          '1': 'D',
          '2': 'D',
          '3': 'C',
          '4': 'A',
          '5': 'C',
          '6': 'A',
          '7': 'D',
          '8': 'D',
          '9': 'A',
          '10': 'A',
          '11': 'A',
          '12': 'C',
          '13': 'B',
          '14': 'C',
          '15': 'A',
          '16': 'C',
          '17': 'B',
          '18': 'C',
          '19': 'C',
          '20': 'A',
          '21': 'A',
          '22': 'B',
          '23': 'B',
          '24': 'A',
          '25': 'D',
          '26': 'B',
          '27': 'B'
        }
      },
      'math': {
        '1': {
          '1': 'C',
          '2': 'D',
          '3': '.2',
          '4': 'B',
          '5': 'B',
          '6': 'C',
          '7': 'B',
          '8': 'A',
          '9': 'A',
          '10': 'C',
          '11': '24',
          '12': 'D',
          '13': 'C',
          '14': '80',
          '15': '7',
          '16': 'A',
          '17': '27556',
          '18': 'C',
          '19': 'C',
          '20': 'B',
          '21': '-3',
          '22': 'C'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': '40',
          '4': '9',
          '5': '2',
          '6': 'A',
          '7': 'D',
          '8': 'C',
          '9': 'D',
          '10': 'D',
          '11': '70',
          '12': 'D',
          '13': 'D',
          '14': 'A',
          '15': 'B',
          '16': 'A',
          '17': '9',
          '18': '6',
          '19': 'D',
          '20': 'D',
          '21': 'B',
          '22': 'A'
        },
        '3': {
          '1': 'A',
          '2': 'D',
          '3': 'A',
          '4': '9',
          '5': 'D',
          '6': 'B',
          '7': 'A',
          '8': '3',
          '9': '76',
          '10': '36504',
          '11': 'C',
          '12': 'C',
          '13': 'B',
          '14': 'D',
          '15': '4',
          '16': '182',
          '17': 'C',
          '18': 'B',
          '19': 'B',
          '20': '50',
          '21': 'A',
          '22': 'B',
        }
      }
    },
    'sat4': {
      'rw': {
        '1': {
          '1': 'B',
          '2': 'B',
          '3': 'A',
          '4': 'B',
          '5': 'A',
          '6': 'D',
          '7': 'A',
          '8': 'A',
          '9': 'D',
          '10': 'B',
          '11': 'C',
          '12': 'B',
          '13': 'B',
          '14': 'D',
          '15': 'D',
          '16': 'B',
          '17': 'C',
          '18': 'A',
          '19': 'D',
          '20': 'D',
          '21': 'D',
          '22': 'C',
          '23': 'D',
          '24': 'A',
          '25': 'C',
          '26': 'D',
          '27': 'C'
        },
        '2': {
          '1': 'D',
          '2': 'D',
          '3': 'A',
          '4': 'A',
          '5': 'B',
          '6': 'C',
          '7': 'C',
          '8': 'A',
          '9': 'C',
          '10': 'A',
          '11': 'C',
          '12': 'A',
          '13': 'D',
          '14': 'A',
          '15': 'D',
          '16': 'C',
          '17': 'B',
          '18': 'A',
          '19': 'A',
          '20': 'D',
          '21': 'C',
          '22': 'D',
          '23': 'B',
          '24': 'D',
          '25': 'D',
          '26': 'A',
          '27': 'B'
        },
        '3': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'C',
          '5': 'D',
          '6': 'A',
          '7': 'A',
          '8': 'C',
          '9': 'B',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'C',
          '14': 'B',
          '15': 'D',
          '16': 'A',
          '17': 'D',
          '18': 'D',
          '19': 'B',
          '20': 'A',
          '21': 'A',
          '22': 'C',
          '23': 'B',
          '24': 'C',
          '25': 'D',
          '26': 'A',
          '27': 'D'
        }
      },
      'math': {
        '1': {
          '1': 'C',
          '2': 'B',
          '3': 'B',
          '4': 'A',
          '5': 'C',
          '6': '5',
          '7': 'D',
          '8': 'A',
          '9': '28',
          '10': 'C',
          '11': '11',
          '12': '9',
          '13': 'A',
          '14': 'D',
          '15': 'D',
          '16': 'B',
          '17': 'C',
          '18': 'C',
          '19': 'D',
          '20': 'B',
          '21': 'B',
          '22': '59/9'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': '2520',
          '4': '40',
          '5': '7',
          '6': '30',
          '7': '180',
          '8': 'C',
          '9': 'A',
          '10': 'D',
          '11': 'D',
          '12': 'A',
          '13': 'A',
          '14': 'C',
          '15': 'A',
          '16': 'D',
          '17': 'D',
          '18': 'C',
          '19': 'D',
          '20': 'C',
          '21': 'D',
          '22': 'A'
        },
        '3': {
          '1': 'A',
          '2': 'B',
          '3': 'B',
          '4': 'C',
          '5': 'D',
          '6': 'C',
          '7': 'C',
          '8': 'C',
          '9': 'A',
          '10': 'C',
          '11': '-.9333',
          '12': '203/50',
          '13': '289',
          '14': '44',
          '15': 'D',
          '16': '14.5',
          '17': 'C',
          '18': 'C',
          '19': 'A',
          '20': '10',
          '21': 'B',
          '22': 'D',
        }
      }
    },
    'sat5': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'B',
          '3': 'B',
          '4': 'B',
          '5': 'D',
          '6': 'D',
          '7': 'A',
          '8': 'A',
          '9': 'D',
          '10': 'D',
          '11': 'C',
          '12': 'A',
          '13': 'D',
          '14': 'A',
          '15': 'C',
          '16': 'D',
          '17': 'C',
          '18': 'B',
          '19': 'A',
          '20': 'C',
          '21': 'D',
          '22': 'B',
          '23': 'D',
          '24': 'B',
          '25': 'C',
          '26': 'B',
          '27': 'C'
        },
        '2': {
          '1': 'C',
          '2': 'B',
          '3': 'D',
          '4': 'A',
          '5': 'D',
          '6': 'A',
          '7': 'B',
          '8': 'D',
          '9': 'C',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'C',
          '14': 'D',
          '15': 'A',
          '16': 'A',
          '17': 'C',
          '18': 'C',
          '19': 'D',
          '20': 'A',
          '21': 'D',
          '22': 'D',
          '23': 'D',
          '24': 'B',
          '25': 'D',
          '26': 'D',
          '27': 'B'
        },
        '3': {
          '1': 'B',
          '2': 'D',
          '3': 'B',
          '4': 'D',
          '5': 'D',
          '6': 'B',
          '7': 'B',
          '8': 'A',
          '9': 'C',
          '10': 'D',
          '11': 'C',
          '12': 'B',
          '13': 'D',
          '14': 'D',
          '15': 'A',
          '16': 'A',
          '17': 'D',
          '18': 'C',
          '19': 'C',
          '20': 'A',
          '21': 'D',
          '22': 'C',
          '23': 'B',
          '24': 'D',
          '25': 'D',
          '26': 'B',
          '27': 'C'
        }
      },
      'math': {
        '1': {
          '1': 'D',
          '2': 'A',
          '3': 'C',
          '4': '11',
          '5': 'C',
          '6': '10',
          '7': 'A',
          '8': 'D',
          '9': 'B',
          '10': 'D',
          '11': '30',
          '12': '4.51',
          '13': 'A',
          '14': 'D',
          '15': 'D',
          '16': '4205',
          '17': '18',
          '18': 'A',
          '19': 'D',
          '20': 'B',
          '21': 'D',
          '22': 'D'
        },
        '2': {
          '1': 'B',
          '2': 'C',
          '3': 'B',
          '4': 'B',
          '5': 'A',
          '6': '6',
          '7': 'B',
          '8': 'B',
          '9': 'A',
          '10': '29',
          '11': '4',
          '12': '.5',
          '13': 'D',
          '14': 'D',
          '15': 'D',
          '16': '7.5',
          '17': 'A',
          '18': '6',
          '19': 'B',
          '20': 'A',
          '21': 'A',
          '22': 'B'
        },
        '3': {
          '1': 'B',
          '2': 'B',
          '3': 'B',
          '4': 'A',
          '5': 'C',
          '6': '29',
          '7': 'D',
          '8': 'D',
          '9': 'A',
          '10': '-10',
          '11': 'A',
          '12': 'D',
          '13': 'D',
          '14': 'A',
          '15': '10',
          '16': '-24',
          '17': 'A',
          '18': '480',
          '19': 'A',
          '20': 'A',
          '21': '4176',
          '22': 'A'
        }
      }
    },
    'sat6': {
      'rw': {
        '1': {
          '1': 'D',
          '2': 'D',
          '3': 'D',
          '4': 'B',
          '5': 'C',
          '6': 'C',
          '7': 'B',
          '8': 'B',
          '9': 'A',
          '10': 'B',
          '11': 'C',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'B',
          '16': 'B',
          '17': 'D',
          '18': 'B',
          '19': 'B',
          '20': 'D',
          '21': 'A',
          '22': 'D',
          '23': 'D',
          '24': 'D',
          '25': 'C',
          '26': 'A',
          '27': 'C'
        },
        '2': {
          '1': 'A',
          '2': 'C',
          '3': 'C',
          '4': 'A',
          '5': 'C',
          '6': 'C',
          '7': 'A',
          '8': 'D',
          '9': 'D',
          '10': 'A',
          '11': 'D',
          '12': 'A',
          '13': 'D',
          '14': 'A',
          '15': 'A',
          '16': 'A',
          '17': 'A',
          '18': 'D',
          '19': 'B',
          '20': 'C',
          '21': 'C',
          '22': 'C',
          '23': 'C',
          '24': 'D',
          '25': 'B',
          '26': 'D',
          '27': 'B'
        },
        '3': {
          '1': 'A',
          '2': 'B',
          '3': 'B',
          '4': 'D',
          '5': 'A',
          '6': 'C',
          '7': 'D',
          '8': 'C',
          '9': 'C',
          '10': 'D',
          '11': 'D',
          '12': 'D',
          '13': 'B',
          '14': 'A',
          '15': 'A',
          '16': 'B',
          '17': 'B',
          '18': 'B',
          '19': 'C',
          '20': 'B',
          '21': 'D',
          '22': 'B',
          '23': 'B',
          '24': 'B',
          '25': 'A',
          '26': 'D',
          '27': 'C'
        }
      },
      'math': {
        '1': {
          '1': 'A',
          '2': 'D',
          '3': 'B',
          '4': 'B',
          '5': 'B',
          '6': 'A',
          '7': 'A',
          '8': 'C',
          '9': 'B',
          '10': '18',
          '11': 'B',
          '12': 'C',
          '13': 'D',
          '14': '4',
          '15': 'D',
          '16': 'A',
          '17': '.3928',
          '18': 'C',
          '19': '54',
          '20': '336',
          '21': '79',
          '22': 'A'
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': 'B',
          '4': 'A',
          '5': 'A',
          '6': '3',
          '7': 'B',
          '8': 'D',
          '9': '6',
          '10': 'D',
          '11': 'C',
          '12': 'D',
          '13': 'C',
          '14': '20',
          '15': 'D',
          '16': '774',
          '17': 'D',
          '18': 'C',
          '19': '14.66',
          '20': '66',
          '21': 'D',
          '22': 'C',
        },
        '3': {
          '1': 'B',
          '2': 'A',
          '3': 'A',
          '4': '3',
          '5': 'D',
          '6': 'B',
          '7': 'D',
          '8': 'A',
          '9': 'D',
          '10': '189/5',
          '11': 'D',
          '12': '1677',
          '13': '1728',
          '14': 'B',
          '15': '25',
          '16': 'C',
          '17': '66',
          '18': 'D',
          '19': '3.5',
          '20': 'A',
          '21': 'D',
          '22': 'A'
        }
      }
    },
    'sat7': {
      'rw': {
        '1': {
          '1': 'D',
          '2': 'D',
          '3': 'D',
          '4': 'B',
          '5': 'A',
          '6': 'B',
          '7': 'D',
          '8': 'D',
          '9': 'A',
          '10': 'B',
          '11': 'B',
          '12': 'A',
          '13': 'C',
          '14': 'A',
          '15': 'C',
          '16': 'B',
          '17': 'C',
          '18': 'C',
          '19': 'D',
          '20': 'C',
          '21': 'B',
          '22': 'A',
          '23': 'B',
          '24': 'D',
          '25': 'B',
          '26': 'D',
          '27': 'C'
        },
        '2': {
          '1': 'A',
          '2': 'C',
          '3': 'D',
          '4': 'C',
          '5': 'A',
          '6': 'C',
          '7': 'A',
          '8': 'B',
          '9': 'D',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'C',
          '14': 'B',
          '15': 'A',
          '16': 'D',
          '17': 'D',
          '18': 'A',
          '19': 'B',
          '20': 'D',
          '21': 'C',
          '22': 'B',
          '23': 'A',
          '24': 'D',
          '25': 'D',
          '26': 'C',
          '27': 'C'
        },
        '3': {
          '1': 'B',
          '2': 'D',
          '3': 'A',
          '4': 'D',
          '5': 'C',
          '6': 'B',
          '7': 'D',
          '8': 'D',
          '9': 'B',
          '10': 'A',
          '11': 'B',
          '12': 'D',
          '13': 'C',
          '14': 'B',
          '15': 'C',
          '16': 'B',
          '17': 'C',
          '18': 'D',
          '19': 'A',
          '20': 'B',
          '21': 'D',
          '22': 'A',
          '23': 'D',
          '24': 'D',
          '25': 'C',
          '26': 'D',
          '27': 'A'
        }
      },
      'math': {
        '1': {
          '1': 'A',
          '2': 'C',
          '3': 'A',
          '4': 'B',
          '5': 'B',
          '6': 'B',
          '7': '90',
          '8': 'D',
          '9': 'C',
          '10': 'D',
          '11': '14',
          '12': '11/4',
          '13': 'A',
          '14': '4.41',
          '15': '5',
          '16': 'D',
          '17': 'B',
          '18': '11',
          '19': 'A',
          '20': '120',
          '21': 'A',
          '22': 'C',
        },
        '2': {
          '1': 'A',
          '2': 'B',
          '3': 'B',
          '4': 'B',
          '5': 'D',
          '6': 'C',
          '7': 'A',
          '8': 'C',
          '9': 'B',
          '10': '162',
          '11': 'C',
          '12': 'D',
          '13': '2850',
          '14': '27',
          '15': 'C',
          '16': 'A',
          '17': '9',
          '18': 'D',
          '19': 'D',
          '20': 'D',
          '21': 'C',
          '22': '87'
        },
        '3': {
          '1': 'D',
          '2': 'D',
          '3': '110',
          '4': 'D',
          '5': 'C',
          '6': 'A',
          '7': 'A',
          '8': '42',
          '9': 'C',
          '10': 'C',
          '11': 'B',
          '12': '153',
          '13': 'A',
          '14': '.2857',
          '15': 'B',
          '16': '17.5',
          '17': 'D',
          '18': 'A',
          '19': 'D',
          '20': 'D',
          '21': 'A',
          '22': 'B'
        }
      }
    },
    'sat8': {
      'rw': {
        '1': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'C',
          '5': 'A',
          '6': 'C',
          '7': 'A',
          '8': 'D',
          '9': 'A',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'D',
          '14': 'B',
          '15': 'D',
          '16': 'B',
          '17': 'B',
          '18': 'C',
          '19': 'C',
          '20': 'A',
          '21': 'B',
          '22': 'C',
          '23': 'B',
          '24': 'A',
          '25': 'D',
          '26': 'D',
          '27': 'C'
        },
        '2': {
          '1': 'C',
          '2': 'D',
          '3': 'B',
          '4': 'A',
          '5': 'A',
          '6': 'C',
          '7': 'A',
          '8': 'B',
          '9': 'D',
          '10': 'A',
          '11': 'B',
          '12': 'C',
          '13': 'A',
          '14': 'C',
          '15': 'D',
          '16': 'D',
          '17': 'A',
          '18': 'C',
          '19': 'B',
          '20': 'A',
          '21': 'D',
          '22': 'D',
          '23': 'D',
          '24': 'C',
          '25': 'B',
          '26': 'C',
          '27': 'B'
        },
        '3': {
          '1': 'D',
          '2': 'B',
          '3': 'B',
          '4': 'A',
          '5': 'D',
          '6': 'C',
          '7': 'D',
          '8': 'A',
          '9': 'C',
          '10': 'C',
          '11': 'D',
          '12': 'C',
          '13': 'B',
          '14': 'D',
          '15': 'C',
          '16': 'A',
          '17': 'C',
          '18': 'A',
          '19': 'C',
          '20': 'B',
          '21': 'B',
          '22': 'B',
          '23': 'A',
          '24': 'C',
          '25': 'D',
          '26': 'B',
          '27': 'A'
        }
      },
      'math': {
        '1': {
          '1': 'D',
          '2': 'D',
          '3': 'D',
          '4': 'D',
          '5': 'B',
          '6': 'A',
          '7': 'C',
          '8': 'B',
          '9': '46',
          '10': 'D',
          '11': 'A',
          '12': '52',
          '13': '410',
          '14': 'C',
          '15': '5',
          '16': 'B',
          '17': 'A',
          '18': 'D',
          '19': '0.25',
          '20': 'B',
          '21': 'C',
          '22': 'A'
        },
        '2': {
          '1': 'C',
          '2': 'D',
          '3': 'B',
          '4': 'C',
          '5': 'D',
          '6': 'D',
          '7': 'B',
          '8': 'A',
          '9': 'D',
          '10': '70',
          '11': '9',
          '12': 'A',
          '13': 'B',
          '14': 'B',
          '15': 'C',
          '16': '25',
          '17': '2',
          '18': 'A',
          '19': '104',
          '20': 'B',
          '21': '6',
          '22': 'C'
        },
        '3': {
          '1': 'C',
          '2': 'C',
          '3': 'A',
          '4': 'B',
          '5': 'B',
          '6': 'D',
          '7': 'B',
          '8': 'C',
          '9': '35',
          '10': 'A',
          '11': '29/3',
          '12': 'C',
          '13': 'B',
          '14': 'C',
          '15': '338',
          '16': '1.8',
          '17': 'C',
          '18': '-34',
          '19': 'D',
          '20': '104',
          '21': 'B',
          '22': 'B'
        }
      }
    },
    'sat9': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'C',
          '3': 'D',
          '4': 'B',
          '5': 'D',
          '6': 'D',
          '7': 'B',
          '8': 'A',
          '9': 'D',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'D',
          '14': 'A',
          '15': 'D',
          '16': 'B',
          '17': 'D',
          '18': 'A',
          '19': 'D',
          '20': 'A',
          '21': 'D',
          '22': 'A',
          '23': 'A',
          '24': 'C',
          '25': 'C',
          '26': 'A',
          '27': 'C'
        },
        '2': {
          '1': 'B',
          '2': 'D',
          '3': 'B',
          '4': 'B',
          '5': 'D',
          '6': 'A',
          '7': 'C',
          '8': 'C',
          '9': 'B',
          '10': 'D',
          '11': 'D',
          '12': 'A',
          '13': 'A',
          '14': 'B',
          '15': 'A',
          '16': 'C',
          '17': 'A',
          '18': 'A',
          '19': 'C',
          '20': 'B',
          '21': 'C',
          '22': 'A',
          '23': 'B',
          '24': 'B',
          '25': 'B',
          '26': 'A',
          '27': 'C'
        },
        '3': {
          '1': 'D',
          '2': 'D',
          '3': 'C',
          '4': 'A',
          '5': 'B',
          '6': 'A',
          '7': 'D',
          '8': 'C',
          '9': 'B',
          '10': 'A',
          '11': 'B',
          '12': 'C',
          '13': 'B',
          '14': 'A',
          '15': 'C',
          '16': 'D',
          '17': 'A',
          '18': 'D',
          '19': 'A',
          '20': 'B',
          '21': 'D',
          '22': 'C',
          '23': 'D',
          '24': 'D',
          '25': 'B',
          '26': 'C',
          '27': 'A'
        }
      },
      'math': {
        '1': {
          '1': 'D',
          '2': 'C',
          '3': 'A',
          '4': 'C',
          '5': 'C',
          '6': '224',
          '7': 'B',
          '8': '1',
          '9': '14',
          '10': 'D',
          '11': 'D',
          '12': 'B',
          '13': 'D',
          '14': 'A',
          '15': 'B',
          '16': '76',
          '17': '35',
          '18': 'D',
          '19': 'D',
          '20': '-3',
          '21': 'C',
          '22': 'B'
        },
        '2': {
          '1': 'B',
          '2': 'C',
          '3': 'B',
          '4': '3',
          '5': 'A',
          '6': 'B',
          '7': '240',
          '8': 'B',
          '9': 'A',
          '10': '9',
          '11': 'C',
          '12': 'D',
          '13': '986',
          '14': '45',
          '15': 'B',
          '16': 'D',
          '17': 'D',
          '18': 'B',
          '19': 'C',
          '20': 'C',
          '21': 'D',
          '22': 'C'
        },
        '3': {
          '1': '79',
          '2': 'B',
          '3': 'B',
          '4': 'C',
          '5': 'D',
          '6': 'A',
          '7': 'B',
          '8': 'D',
          '9': '46',
          '10': 'B',
          '11': '113',
          '12': 'D',
          '13': 'D',
          '14': '33',
          '15': 'C',
          '16': 'B',
          '17': 'C',
          '18': 'D',
          '19': 'C',
          '20': '168',
          '21': 'A',
          '22': 'B'
        }
      }
    },
    'sat10': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'C',
          '3': 'C',
          '4': 'A',
          '5': 'B',
          '6': 'B',
          '7': 'A',
          '8': 'C',
          '9': 'A',
          '10': 'D',
          '11': 'A',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'D',
          '16': 'C',
          '17': 'D',
          '18': 'C',
          '19': 'C',
          '20': 'B',
          '21': 'A',
          '22': 'D',
          '23': 'D',
          '24': 'A',
          '25': 'C',
          '26': 'A',
          '27': 'C',
        },
        '2': {
          '1': 'A',
          '2': 'D',
          '3': 'B',
          '4': 'A',
          '5': 'D',
          '6': 'C',
          '7': 'D',
          '8': 'A',
          '9': 'A',
          '10': 'D',
          '11': 'A',
          '12': 'B',
          '13': 'A',
          '14': 'A',
          '15': 'C',
          '16': 'A',
          '17': 'B',
          '18': 'C',
          '19': 'C',
          '20': 'A',
          '21': 'A',
          '22': 'A',
          '23': 'B',
          '24': 'A',
          '25': 'B',
          '26': 'B',
          '27': 'C'
        },
        '3': {
          '1': 'D',
          '2': 'C',
          '3': 'C',
          '4': 'A',
          '5': 'A',
          '6': 'D',
          '7': 'B',
          '8': 'D',
          '9': 'A',
          '10': 'C',
          '11': 'C',
          '12': 'A',
          '13': 'C',
          '14': 'C',
          '15': 'A',
          '16': 'C',
          '17': 'C',
          '18': 'C',
          '19': 'C',
          '20': 'A',
          '21': 'A',
          '22': 'D',
          '23': 'C',
          '24': 'D',
          '25': 'B',
          '26': 'B',
          '27': 'D'
        }
      },
      'math': {
        '1': {
          '1': 'C',
          '2': 'D',
          '3': 'C',
          '4': 'A',
          '5': 'D',
          '6': 'D',
          '7': '77',
          '8': 'B',
          '9': 'D',
          '10': '24',
          '11': 'D',
          '12': 'C',
          '13': 'D',
          '14': '7',
          '15': '27556',
          '16': '25',
          '17': 'A',
          '18': 'D',
          '19': 'A',
          '20': 'D',
          '21': 'B',
          '22': 'D'
        },
        '2': {
          '1': '40',
          '2': 'C',
          '3': 'A',
          '4': 'C',
          '5': '39000',
          '6': '2',
          '7': 'B',
          '8': 'D',
          '9': 'B',
          '10': 'A',
          '11': 'A',
          '12': 'D',
          '13': 'D',
          '14': 'D',
          '15': '41',
          '16': 'D',
          '17': 'A',
          '18': 'B',
          '19': 'B',
          '20': 'D',
          '21': '11875',
          '22': 'C',
        },
        '3': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'B',
          '5': '67',
          '6': 'B',
          '7': 'D',
          '8': 'A',
          '9': 'B',
          '10': '36504',
          '11': '3',
          '12': 'D',
          '13': 'C',
          '14': '182',
          '15': 'A',
          '16': 'C',
          '17': 'B',
          '18': 'C',
          '19': 'C',
          '20': '50',
          '21': 'B',
          '22': 'A'
        }
      }
    },
    'sat11': {
      'rw': {
        '1': {
          '1': 'C',
          '2': 'D',
          '3': 'B',
          '4': 'A',
          '5': 'B',
          '6': 'D',
          '7': 'D',
          '8': 'D',
          '9': 'B',
          '10': 'D',
          '11': 'B',
          '12': 'A',
          '13': 'A',
          '14': 'D',
          '15': 'B',
          '16': 'A',
          '17': 'B',
          '18': 'B',
          '19': 'B',
          '20': 'B',
          '21': 'C',
          '22': 'D',
          '23': 'B',
          '24': 'C',
          '25': 'C',
          '26': 'A',
          '27': 'C',
        },
        '2': {
          '1': 'C',
          '2': 'D',
          '3': 'D',
          '4': 'D',
          '5': 'B',
          '6': 'A',
          '7': 'B',
          '8': 'C',
          '9': 'D',
          '10': 'C',
          '11': 'B',
          '12': 'C',
          '13': 'A',
          '14': 'C',
          '15': 'C',
          '16': 'D',
          '17': 'D',
          '18': 'A',
          '19': 'B',
          '20': 'B',
          '21': 'B',
          '22': 'D',
          '23': 'D',
          '24': 'B',
          '25': 'C',
          '26': 'A',
          '27': 'A',
        },
        '3': {
          '1': 'D',
          '2': 'B',
          '3': 'B',
          '4': 'B',
          '5': 'B',
          '6': 'C',
          '7': 'B',
          '8': 'A',
          '9': 'D',
          '10': 'C',
          '11': 'A',
          '12': 'B',
          '13': 'A',
          '14': 'A',
          '15': 'A',
          '16': 'B',
          '17': 'A',
          '18': 'A',
          '19': 'A',
          '20': 'D',
          '21': 'B',
          '22': 'A',
          '23': 'B',
          '24': 'D',
          '25': 'D',
          '26': 'B',
          '27': 'A',
        }
      },
      'math': {
        '1': {
          '1': 'A',
          '2': 'A',
          '3': '8',
          '4': '13',
          '5': 'B',
          '6': 'C',
          '7': '63',
          '8': 'C',
          '9': 'C',
          '10': 'A',
          '11': 'A',
          '12': 'A',
          '13': 'C',
          '14': 'D',
          '15': '15000',
          '16': 'A',
          '17': 'B',
          '18': 'B',
          '19': 'A',
          '20': 'D',
          '21': '3331',
          '22': 'B'
        },
        '2': {
          '1': '4',
          '2': 'A',
          '3': 'B',
          '4': 'A',
          '5': '8.6',
          '6': '75',
          '7': 'C',
          '8': 'A',
          '9': 'A',
          '10': 'B',
          '11': 'D',
          '12': 'A',
          '13': 'C',
          '14': '3600',
          '15': 'A',
          '16': 'D',
          '17': '45',
          '18': 'A',
          '19': 'B',
          '20': 'C',
          '21': 'B',
          '22': 'B'
        },
        '3': {
          '1': 'B',
          '2': '30',
          '3': 'A',
          '4': 'C',
          '5': 'B',
          '6': 'D',
          '7': '100',
          '8': 'A',
          '9': '29',
          '10': 'A',
          '11': 'D',
          '12': 'A',
          '13': 'B',
          '14': 'C',
          '15': '.5061',
          '16': 'A',
          '17': 'A',
          '18': 'A',
          '19': 'C',
          '20': 'B',
          '21': 'D',
          '22': '60000'
        }
      },
    },
    'psat1': {
      'rw': {
        '1': {
          '1': 'A',
          '2': 'D',
          '3': 'B',
          '4': 'C',
          '5': 'D',
          '6': 'A',
          '7': 'A',
          '8': 'D',
          '9': 'B',
          '10': 'C',
          '11': 'C',
          '12': 'A',
          '13': 'A',
          '14': 'C',
          '15': 'B',
          '16': 'B',
          '17': 'A',
          '18': 'B',
          '19': 'A',
          '20': 'D',
          '21': 'C',
          '22': 'B',
          '23': 'D',
          '24': 'A',
          '25': 'B',
          '26': 'C',
          '27': 'D',
        },
        '2': {
          '1': 'B',
          '2': 'B',
          '3': 'C',
          '4': 'C',
          '5': 'A',
          '6': 'D',
          '7': 'C',
          '8': 'B',
          '9': 'C',
          '10': 'D',
          '11': 'A',
          '12': 'C',
          '13': 'D',
          '14': 'D',
          '15': 'C',
          '16': 'C',
          '17': 'C',
          '18': 'A',
          '19': 'C',
          '20': 'C',
          '21': 'D',
          '22': 'A',
          '23': 'C',
          '24': 'A',
          '25': 'B',
          '26': 'C',
          '27': 'A'
        },
        '3': {
          '1': 'C',
          '2': 'A',
          '3': 'C',
          '4': 'A',
          '5': 'C',
          '6': 'D',
          '7': 'C',
          '8': 'B',
          '9': 'D',
          '10': 'D',
          '11': 'D',
          '12': 'A',
          '13': 'D',
          '14': 'B',
          '15': 'B',
          '16': 'D',
          '17': 'C',
          '18': 'D',
          '19': 'D',
          '20': 'B',
          '21': 'D',
          '22': 'C',
          '23': 'B',
          '24': 'D',
          '25': 'D',
          '26': 'C',
          '27': 'A'
        }
      },
      'math': {
        '1': {
          '1': 'D',
          '2': 'C',
          '3': 'C',
          '4': 'D',
          '5': 'B',
          '6': 'C',
          '7': 'C',
          '8': 'C',
          '9': '.25',
          '10': 'A',
          '11': 'B',
          '12': 'A',
          '13': 'A',
          '14': '99',
          '15': 'D',
          '16': 'A',
          '17': '241',
          '18': '57',
          '19': '-2',
          '20': 'C',
          '21': '-7',
          '22': 'B'
        },
        '2': {
          '1': 'C',
          '2': 'C',
          '3': 'B',
          '4': 'D',
          '5': '54',
          '6': 'B',
          '7': 'B',
          '8': 'B',
          '9': 'B',
          '10': 'A',
          '11': 'C',
          '12': 'A',
          '13': '348',
          '14': 'C',
          '15': 'C',
          '16': 'D',
          '17': 'B',
          '18': 'B',
          '19': '-9',
          '20': '56',
          '21': 'C',
          '22': 'B'
        },
        '3': {
          '1': 'A',
          '2': '21',
          '3': '9',
          '4': 'A',
          '5': 'A',
          '6': '19',
          '7': 'B',
          '8': 'B',
          '9': 'A',
          '10': 'C',
          '11': 'A',
          '12': 'D',
          '13': 'C',
          '14': '16606',
          '15': 'C',
          '16': 'B',
          '17': '0.5',
          '18': 'B',
          '19': 'B',
          '20': 'A',
          '21': 'D',
          '22': '.0625'
        }
      }
    },
    'psat2': {
      'rw': {
        '1': {
          '1': 'C',
          '2': 'A',
          '3': 'D',
          '4': 'B',
          '5': 'C',
          '6': 'C',
          '7': 'D',
          '8': 'B',
          '9': 'B',
          '10': 'A',
          '11': 'D',
          '12': 'A',
          '13': 'C',
          '14': 'B',
          '15': 'C',
          '16': 'D',
          '17': 'A',
          '18': 'A',
          '19': 'A',
          '20': 'C',
          '21': 'D',
          '22': 'A',
          '23': 'D',
          '24': 'D',
          '25': 'A',
          '26': 'B',
          '27': 'C',
        },
        '2': {
          '1': 'B',
          '2': 'C',
          '3': 'A',
          '4': 'B',
          '5': 'A',
          '6': 'C',
          '7': 'B',
          '8': 'D',
          '9': 'D',
          '10': 'A',
          '11': 'A',
          '12': 'B',
          '13': 'B',
          '14': 'A',
          '15': 'B',
          '16': 'B',
          '17': 'D',
          '18': 'C',
          '19': 'D',
          '20': 'A',
          '21': 'C',
          '22': 'B',
          '23': 'B',
          '24': 'B',
          '25': 'B',
          '26': 'C',
          '27': 'B',
        },
        '3': {
          '1': 'B',
          '2': 'D',
          '3': 'B',
          '4': 'A',
          '5': 'B',
          '6': 'B',
          '7': 'B',
          '8': 'C',
          '9': 'A',
          '10': 'C',
          '11': 'C',
          '12': 'D',
          '13': 'B',
          '14': 'A',
          '15': 'C',
          '16': 'C',
          '17': 'C',
          '18': 'C',
          '19': 'B',
          '20': 'D',
          '21': 'B',
          '22': 'B',
          '23': 'D',
          '24': 'C',
          '25': 'C',
          '26': 'B',
          '27': 'B'
        }
      },
      'math': {
        '1': {
          '1': 'C',
          '2': '17',
          '3': 'A',
          '4': 'A',
          '5': 'D',
          '6': '423.5',
          '7': '4',
          '8': 'A',
          '9': 'D',
          '10': 'B',
          '11': 'A',
          '12': 'C',
          '13': 'B',
          '14': '34',
          '15': '3630',
          '16': 'A',
          '17': 'C',
          '18': 'A',
          '19': 'B',
          '20': 'B',
          '21': 'D',
          '22': 'B',
        },
        '2': {
          '1': 'B',
          '2': 'A',
          '3': '180',
          '4': 'C',
          '5': 'A',
          '6': 'C',
          '7': 'B',
          '8': 'A',
          '9': 'C',
          '10': '40',
          '11': '130',
          '12': '6',
          '13': 'C',
          '14': 'B',
          '15': 'D',
          '16': '3',
          '17': 'A',
          '18': 'A',
          '19': 'A',
          '20': '14',
          '21': 'D',
          '22': 'D'
        },
        '3': {
          '1': '7',
          '2': 'A',
          '3': 'C',
          '4': 'B',
          '5': 'C',
          '6': 'C',
          '7': 'B',
          '8': '6',
          '9': '24',
          '10': 'D',
          '11': 'C',
          '12': 'C',
          '13': 'B',
          '14': 'B',
          '15': 'D',
          '16': '14',
          '17': '48',
          '18': 'B',
          '19': 'D',
          '20': 'A',
          '21': '47',
          '22': '231',
        }
      }
    }
  }

  for sub in score_details_data['answers']:
    for mod in score_details_data['answers'][sub]:
      key_mod = mod
      if mod == '2' and ((sub == 'rw' and score_details_data['is_rw_hard']) or (sub == 'math' and score_details_data['is_math_hard'])):
        key_mod = '3'
      for q in score_details_data['answers'][sub][mod]:
        if score_details_data[f'is_{sub}_found']:
          if score_details_data['answers'][sub][mod][q]['correct_answer'] == 'not found':
            score_details_data['missing_data'].append({
              'sub': sub,
              'mod': mod,
              'q': q
            })
          elif score_details_data['answers'][sub][mod][q]['correct_answer'] != answer_key[score_details_data['test_code']][sub][key_mod][q]:
            score_details_data['answer_key_mismatches'].append({
              'sub': sub,
              'mod': mod,
              'q': q,
              'previous_key': answer_key[score_details_data['test_code']][sub][key_mod][q],
              'new_key': score_details_data['answers'][sub][mod][q]['correct_answer']
            })

  return score_details_data


def get_all_data(report_path, details_path):
  data = get_student_answers(details_path)
  if data == "invalid":
    data = get_student_answers(report_path)
    report_path, details_path = details_path, report_path
    if data == "invalid":
      raise FileNotFoundError('Score Details PDF does not match expected format')
  data = get_data_from_score_report(data, report_path)
  data = get_mod_difficulty(data)
  data = check_answer_key(data)
  # print_answer_key(data)
  # pp.pprint(data)
  return data