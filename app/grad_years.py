"""Grad year <select> choices that roll over every June 1.

Stored values stay plain year strings; only the labels (and which years are offered) move.
"""
import re
from datetime import date

GRADES = ['Senior', 'Junior', 'Sophomore', 'Freshman',
          '8th grade', '7th grade', '6th grade', '5th grade', '4th grade', '3rd grade', '2nd grade', '1st grade']


def senior_year(today=None):
    """Class year of the current seniors: the school year turns over on June 1."""
    today = today or date.today()
    return today.year + (1 if today.month >= 6 else 0)


def grad_year_choices(current=None, blank_label='Grad year', today=None):
    """Seniors down to 1st grade, then College and Adult.

    `current` is the stored value; one the list doesn't offer (a class that already graduated,
    or a legacy 'school') is appended so it still shows as itself and passes validation.
    """
    senior = senior_year(today)
    choices = [('', blank_label)]
    choices += [(str(senior + i), f'{senior + i} ({grade})') for i, grade in enumerate(GRADES)]
    choices += [('college', 'College'), ('adult', 'Adult')]

    value = '' if current is None else str(current).strip()
    # 'None' is what the old blank option stored
    if value in ('', 'None') or value in dict(choices):
        return choices
    if value == 'school':
        label = 'Grade school'
    elif re.fullmatch(r'\d{4}', value) and int(value) < senior:
        label = f'{value} (Graduated)'
    else:
        label = value.capitalize()
    return choices + [(value, label)]
