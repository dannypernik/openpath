import pdfplumber
import pprint
import datetime

pp = pprint.PrettyPrinter(indent=2, width=100)


def get_student_answers(score_details_file_path):
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
      'answers': {
        'rw_modules': {
          1: {},
          2: {}
        },
        'm_modules': {
          1: {},
          2: {}
        },
      },
  }

  for i, p in enumerate(pages):
    if i == 0:
      text = p.extract_text()

      date_row = text.find('My Tests')
      date_start = text.find(' - ', date_row) + 3
      date_end = text.find('202', date_start) + 4
      date_str = text[date_start:date_end]
      date = datetime.datetime.strptime(date_str, '%B %d, %Y').strftime('%Y-%m-%d')
      score_details_data['date'] = date

      test_type_start = text.find('My Tests') + 11
      test_type_end = text.find(' ', test_type_start)
      test_type = text[test_type_start:test_type_end]
      test_number_end = date_start - 3
      test_number_start = text.rfind(' ', 0, test_number_end) + 1
      test_number = text[test_number_start:test_number_end]
      score_details_data['test_code'] = test_type.lower() + test_number
      score_details_data['test_display_name'] = f'{test_type.upper()} {test_number}'

    else:
      table = p.extract_table(table_settings={
        'horizontal_strategy': 'text',
        'vertical_strategy': 'text',
      })

      # pp.pprint(table)

      for row in table:
        if row[0]:
          if row[1][:7] == 'Reading' or row[1][:4] == 'Math':
            number = int(row[0])
            if row[1][:7] == 'Reading':
              subject = 'rw_modules'
              correct_index = 4
              if row[1] == 'Reading and Writing':
                correct_index = 2
            elif row[1] == 'Math':
              subject = 'm_modules'
              if row[2] == '':
                correct_index = 4
              else:
                correct_index = 2
            if score_details_data['answers'][subject][1].get(number):
              module = 2
            else:
              module = 1
            correct_answer = row[correct_index]
            response = row[correct_index + 1].split('; ')[0]
            if response == 'Omitted':
              response = '-'
              is_correct = False
            else:
              is_correct = row[correct_index + 1].split('; ')[1] == 'Correct'

            score_details_data['answers'][subject][module][number] = {
              'correct_answer': correct_answer,
              'response': response,
              'is_correct': is_correct
            }
    ## print answer key
    # for sub in score_details_data['answers']:
    #   print(sub)
    #   for mod in score_details_data['answers'][sub]:
    #     print(mod)
    #     for q in score_details_data['answers'][sub][mod]:
    #       print(q, score_details_data['answers'][sub][mod][q]['correct_answer'])

  return score_details_data


def mod_difficulty_check(score_details_data):
  mod_diffs = {
    'sat1': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'D',
      }

    },
    'sat2': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'A',
      },
      'm': {
        'diff_question': 3,
        'easy_answer': 'B',
        'hard_answer': 'C',
      }
    },
    'sat3': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'sat4': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'D',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'sat5': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': 2,
        'easy_answer': 'C',
        'hard_answer': 'B',
      }
    },
    'sat6': {
      'rw': {
        'diff_question': 2,
        'easy_answer': 'C',
        'hard_answer': 'B',
      },
      'm': {
        'diff_question': 2,
        'easy_answer': 'B',
        'hard_answer': 'A',
      }
    },
    'psat1': {
      'rw': {
        'diff_question': 1,
        'easy_answer': 'B',
        'hard_answer': 'C',
      },
      'm': {
        'diff_question': 1,
        'easy_answer': 'C',
        'hard_answer': 'A',
      }
    },
    'psat2': {
      'rw': {
        'diff_question': 2,
        'easy_answer': 'C',
        'hard_answer': 'D',
      },
      'm': {
        'diff_question': 1,
        'easy_answer': 'C',
        'hard_answer': 'A',
      }
    },
  }

  hard_rw_diff_answer = mod_diffs[score_details_data['test_code']]['rw']['hard_answer']
  pdf_rw_diff_answer = score_details_data['answers']['rw_modules'][2][mod_diffs[score_details_data['test_code']]['rw']['diff_question']]['correct_answer']
  print(hard_rw_diff_answer, pdf_rw_diff_answer)
  is_rw_hard = hard_rw_diff_answer == pdf_rw_diff_answer

  hard_m_diff_answer = mod_diffs[score_details_data['test_code']]['m']['hard_answer']
  pdf_m_diff_answer = score_details_data['answers']['m_modules'][2][mod_diffs[score_details_data['test_code']]['m']['diff_question']]['correct_answer']
  print(hard_m_diff_answer, pdf_m_diff_answer)
  is_m_hard = hard_m_diff_answer == pdf_m_diff_answer

  return is_rw_hard, is_m_hard