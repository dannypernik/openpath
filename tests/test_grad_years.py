from datetime import date

from app.grad_years import grad_year_choices, senior_year


def test_senior_class_rolls_over_on_june_1():
    assert senior_year(date(2026, 5, 31)) == 2026
    assert senior_year(date(2026, 6, 1)) == 2027
    assert senior_year(date(2026, 12, 31)) == 2027
    assert senior_year(date(2027, 1, 1)) == 2027


def test_choices_run_from_seniors_to_1st_grade_then_college_and_adult():
    c = grad_year_choices(None, 'Grad year', date(2026, 11, 7))
    assert c[0] == ('', 'Grad year')
    assert c[1] == ('2027', '2027 (Senior)')
    assert c[4] == ('2030', '2030 (Freshman)')
    assert c[5] == ('2031', '2031 (8th grade)')
    assert c[12] == ('2038', '2038 (1st grade)')
    assert c[13:] == [('college', 'College'), ('adult', 'Adult')]


def test_same_stored_year_is_junior_before_june_1_and_senior_after():
    label = lambda today: dict(grad_year_choices(None, '', today))['2027']
    assert label(date(2026, 5, 31)) == '2027 (Junior)'
    assert label(date(2026, 6, 1)) == '2027 (Senior)'


def test_stored_values_not_offered_still_show_as_themselves():
    today = date(2026, 11, 7)
    assert grad_year_choices('2026', '', today)[-1] == ('2026', '2026 (Graduated)')
    assert grad_year_choices('school', '', today)[-1] == ('school', 'Grade school')
    assert grad_year_choices('graduated', '', today)[-1] == ('graduated', 'Graduated')
    assert len(grad_year_choices('2027', '', today)) == 15


def test_blank_and_legacy_none_string_add_no_option():
    today = date(2026, 11, 7)
    for blank in (None, '', 'None'):
        assert len(grad_year_choices(blank, '', today)) == 15
