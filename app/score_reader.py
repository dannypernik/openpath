import datetime
from bs4 import BeautifulSoup
import pdfplumber
import re
import pprint
from flask import flash, Markup
import logging

pp = pprint.PrettyPrinter(indent=2, width=100)

def get_student_answers(score_details_file_path):
  total_questions = {
    'rw_modules': {'questions': 27},
    'm_modules': {'questions': 22}
  }

  pdf = pdfplumber.open(score_details_file_path)
  pages = pdf.pages

  score_details_data = {
      'test_code': None,
      'test_display_name': None,
      'date': None,
      'rw_score': 100,
      'm_score': 100,
      'is_rw_hard': None,
      'is_m_hard': None,
      'has_omits': False,
      'answers': {
        'rw_modules': {
          '1': {},
          '2': {}
        },
        'm_modules': {
          '1': {},
          '2': {}
        },
      },
  }

  date = None
  subject_totals = {
    'rw_modules': 0,
    'm_modules': 0
  }

  for i, p in enumerate(pages):
    text = p.extract_text()

    for line in read_text_line_by_line(text):
      # print(line)
      # print(list(line))
      if date is None and line.find('My Tests') != -1:
        trimmed_line = line.rstrip() # ensures no trailing whitespace
        date_start = trimmed_line.find(' - ') + 3
        date_str = trimmed_line[date_start:]
        date = datetime.datetime.strptime(date_str, '%B %d, %Y').strftime('%Y.%m.%d')
        score_details_data['date'] = date

        test_type_start = line.find('My Tests') + 11
        sep = {'/',' '}
        test_type_end = next((i for i, ch  in enumerate(line[test_type_start:]) if ch in sep),None) + test_type_start
        # test_type_end = line.find(' ', test_type_start)
        test_type = line[test_type_start:test_type_end]
        test_number_end = date_start - 3
        test_number_start = line.rfind(" ", 0, test_number_end) + 1

        test_number = line[test_number_start:test_number_end]
        score_details_data['test_code'] = test_type.lower() + test_number
        score_details_data['test_display_name'] = f'{test_type.upper()} {test_number}'

      if line.count(' ') >= 3:
        if line.split()[1] == 'Reading' or line.split()[1] == 'Math':
          number = str(line.split(' ')[0])
          if line.split()[1] == 'Reading':
              subject = 'rw_modules'
              correct_index = 4
          elif line.split()[1] == 'Math':
            subject = 'm_modules'
            correct_index = 2
          if score_details_data['answers'][subject]['1'].get(number):
            module = '2'
          else:
            module = '1'
          correct_answer = line.split()[correct_index]
          s_line = line.split(' ')
          if s_line[-1] == 'Review':
            offset = 0
          else:
            offset = 1
          is_correct = s_line[-2 + offset] == 'Correct'
          if s_line[-2 + offset] == 'Omitted':
            response = '-'
            score_details_data['has_omits'] = True
          else:
            response = s_line[-3+offset][:-1]

          subject_totals[subject] += 1

          score_details_data['answers'][subject][module][number] = {
            'correct_answer': correct_answer,
            'student_answer': response,
            'is_correct': is_correct
          }

  missing_questions = 0
  for sub in ['rw_modules', 'm_modules']:
    for mod in range(1, 3):
      for q in range(1, total_questions[sub]['questions'] + 1):
        if score_details_data['answers'][sub][str(mod)].get(str(q)) is None:
          score_details_data['answers'][sub][str(mod)][str(q)] = {
            'correct_answer': 'not found',
            'student_answer': 'not found',
            'is_correct': False
          }

  # print answer key
  # for sub in score_details_data['answers']:
  #   print(sub)
  #   for mod in score_details_data['answers'][sub]:
  #     print(mod)
  #     for q in score_details_data['answers'][sub][mod]:
  #       print(q, score_details_data['answers'][sub][mod][q]['correct_answer'])
  # pp.pprint(score_details_data)

  if date is None:
    print(score_details_data)
    return "invalid"
  elif subject_totals['m_modules'] < 5:
    raise ValueError('Missing math modules')
  elif subject_totals['rw_modules'] < 44:
    raise ValueError('Error reading score details: missing RW questions')
  elif subject_totals['m_modules'] < 34:
    raise ValueError('Error reading score details: missing Math questions')

  return score_details_data


def read_text_line_by_line(text):
  for line in text.split('\n'):
    yield line


def get_data_from_pdf(data, pdf_path):
  pdf = pdfplumber.open(pdf_path)
  pages = pdf.pages

  data['student_name'] = None
  data['rw_score'] = None
  data['m_score'] = None
  data['total_score'] = None

  reportConfirmed = False
  if pages[0].extract_text().find('This practice score report is provided by') != -1:
    reportConfirmed = True

  if reportConfirmed:
    try:
      for page in pages:
        text = page.extract_text()
        # print(text)
        # Extract student name
        if not data['student_name']:
          name_start = text.find('Name: ') + 6
          if name_start != -1:
            name_end = text.find('\n', name_start)
            student_name = text[name_start:name_end].strip()
            data['student_name'] = student_name

        # Extract total score and remaining values
        scores = re.findall(r'(\s\d{3}\s|\s\d{4}\s)', text)
        scores = [int(score) for score in scores if 200 <= int(score) <= 1600]
        if scores:
          data['total_score'] = max(scores)
          remaining_values = [int(value) for value in scores if value != data['total_score']]
          if len(remaining_values) >= 2:
            for i in range(len(remaining_values) - 1):
              for j in range(i+1, len(remaining_values)):
                if remaining_values[i] + remaining_values[j] == data['total_score']:
                  data['rw_score'] = remaining_values[i]
                  data['m_score'] = remaining_values[j]
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
        date_str = sat_line[date_start:]
        date = datetime.datetime.strptime(date_str, '%B %d, %Y').strftime('%Y.%m.%d')
      if date != data['date'] or test_code != data['test_code']:
        raise ValueError(f'Score report error: date or test code mismatch. {date} != {data["date"]} or {test_code} != {data["test_code"]}')
      if not data['rw_score'] or not data['m_score']:
        raise ValueError('Score report error: rw_score or m_score not found')
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
        'easy_answer': 'C',
        'hard_answer': 'A',
      }
    },
  }

  hard_rw_diff_answer = mod_diffs[score_details_data['test_code']]['rw']['hard_answer']
  pdf_rw_diff_answer = score_details_data['answers']['rw_modules']['2'][mod_diffs[score_details_data['test_code']]['rw']['diff_question']]['correct_answer']
  score_details_data['is_rw_hard'] = hard_rw_diff_answer == pdf_rw_diff_answer

  hard_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['hard_answer']
  pdf_m_diff_answer = score_details_data['answers']['m_modules']['2'][mod_diffs[score_details_data['test_code']]['m']['diff_question']]['correct_answer']
  score_details_data['is_m_hard'] = hard_m_diff_answer == pdf_m_diff_answer

  return score_details_data


def get_all_data(report_path, details_path):
  data = get_student_answers(details_path)
  if data == "invalid":
    data = get_student_answers(report_path)
    report_path, details_path = details_path, report_path
    if data == "invalid":
      raise FileNotFoundError('Score Details PDF does not match expected format')
  data = get_data_from_pdf(data, report_path)
  data = get_mod_difficulty(data)
  # pp.pprint(data)
  return data