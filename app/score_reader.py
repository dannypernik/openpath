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

  for sub in ['rw_modules', 'm_modules']:
    for mod in range(1, 3):
      for q in range(1, total_questions[sub]['questions'] + 1):
        if score_details_data['answers'][sub][str(mod)].get(str(q)) is None:
          score_details_data['answers'][sub][str(mod)][str(q)] = {
            'correct_answer': 'not found',
            'student_answer': 'not found',
            'is_correct': False
          }

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
          if name_start != 5: # -1 + 6
            name_end = text.find('\n', name_start)
            student_name = text[name_start:name_end].strip()
            data['student_name'] = student_name

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
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
      },
      'm': {
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
      }
    },
    'sat9': {
      'rw': {
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
      },
      'm': {
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
      }
    },
    'sat10': {
      'rw': {
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
      },
      'm': {
        'diff_question': '',
        'easy_answer': '',
        'hard_answer': '',
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
  pdf_rw_diff_answer = score_details_data['answers']['rw_modules']['2'][mod_diffs[score_details_data['test_code']]['rw']['diff_question']]['correct_answer']
  if hard_rw_diff_answer == pdf_rw_diff_answer:
    score_details_data['is_rw_hard'] = True
  elif easy_rw_diff_answer == pdf_rw_diff_answer:
    score_details_data['is_rw_hard'] = False
  else:
    score_details_data['is_rw_hard'] = None

  easy_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['easy_answer']
  hard_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['hard_answer']
  pdf_m_diff_answer = score_details_data['answers']['m_modules']['2'][mod_diffs[score_details_data['test_code']]['m']['diff_question']]['correct_answer']
  if hard_m_diff_answer == pdf_m_diff_answer:
    score_details_data['is_m_hard'] = True
  elif easy_m_diff_answer == pdf_m_diff_answer:
    score_details_data['is_m_hard'] = False
  else:
    score_details_data['is_m_hard'] = None

  return score_details_data

def print_answer_key(score_details_data):
  answer_key = {
    'test_code': score_details_data['test_code'],
    'is_rw_hard': score_details_data['is_rw_hard'],
    'is_m_hard': score_details_data['is_m_hard'],
    'rw_modules': {
      '1': {},
      '2': {}
    },
    'm_modules': {
      '1': {},
      '2': {}
    }
  }
  for sub in score_details_data['answers']:
    for mod in score_details_data['answers'][sub]:
      for q in score_details_data['answers'][sub][mod]:
        answer_key[sub][mod][q] = score_details_data['answers'][sub][mod][q]['correct_answer']
  pp.pprint(answer_key)

def check_answer_key(score_details_data):
  answer_key = {
    'sat1': {
      'rw_modules': {
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
      'm_modules': {
        '1': {
          '1': 'A',
          '2': 'B',
          '3': 'A',
          '4': 'D',
          '5': 'A',
          '6': '.3,',
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
          '19': '.8823,',
          '20': '25/4,',
          '21': '24',
          '22': '20.25,'
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
      'rw_modules': {
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
      'm_modules': {
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
          '16': '.5,',
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
          '9': '15,',
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
          '12': '29/3,',
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
      'rw_modules': {
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
      'm_modules': {
        '1': {
          '1': 'C',
          '2': 'D',
          '3': '.2,',
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
      'rw_modules': {
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
      'm_modules': {
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
          '22': '59/9,'
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
          '11': '-.9333,',
          '12': '203/50,',
          '13': '289',
          '14': '44',
          '15': 'D',
          '16': '14.5,',
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
      'rw_modules': {
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
      'm_modules': {
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
          '11': '30,',
          '12': '4.51,',
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
          '12': '.5,',
          '13': 'D',
          '14': 'D',
          '15': 'D',
          '16': '7.5,',
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
      'rw_modules': {
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
      'm_modules': {
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
          '17': '.3928,',
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
          '19': '14.66,',
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
          '10': '189/5,',
          '11': 'D',
          '12': '1677',
          '13': '1728',
          '14': 'B',
          '15': '25',
          '16': 'C',
          '17': '66',
          '18': 'D',
          '19': '3.5,',
          '20': 'A',
          '21': 'D',
          '22': 'A'
        }
      }
    },
    'psat1': {
      'rw_modules': {
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
      'm_modules': {
        '1': {
          '1': 'D',
          '2': 'C',
          '3': 'C',
          '4': 'D',
          '5': 'B',
          '6': 'C',
          '7': 'C',
          '8': 'C',
          '9': '.25,',
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
          '17': '0.5,',
          '18': 'B',
          '19': 'B',
          '20': 'A',
          '21': 'D',
          '22': '.0625,'
        }
      }
    },
    'psat2': {
      'rw_modules': {
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
      'm_modules': {
        '1': {
          '1': 'C',
          '2': '17',
          '3': 'A',
          '4': 'A',
          '5': 'D',
          '6': '423.5,',
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

  changed_answers = []
  for sub in score_details_data['answers']:
    for mod in score_details_data['answers'][sub]:
      for q in score_details_data['answers'][sub][mod]:
        if score_details_data['answers'][sub][mod][q] != answer_key[score_details_data['test_code']][sub][mod][q]:
          changed_answers.append({
            'sub': sub,
            'mod': mod,
            'q': q,
            'answer_key': answer_key[score_details_data['test_code']][sub][mod][q],
            'student': score_details_data['answers'][sub][mod][q]
          })

  return changed_answers


def get_all_data(report_path, details_path):
  data = get_student_answers(details_path)
  if data == "invalid":
    data = get_student_answers(report_path)
    report_path, details_path = details_path, report_path
    if data == "invalid":
      raise FileNotFoundError('Score Details PDF does not match expected format')
  data = get_data_from_pdf(data, report_path)
  data = get_mod_difficulty(data)
  # check_answer_key(data)
  # print_answer_key(data)
  # pp.pprint(data)
  return data

