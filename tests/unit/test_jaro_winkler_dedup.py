from decisionssearch.application.shared.jaro_winkler import jaro_similarity, jaro_winkler


def test_identical_strings():
    assert jaro_winkler("hello", "hello") == 1.0


def test_completely_different():
    assert jaro_winkler("abc", "xyz") == 0.0


def test_empty_strings():
    assert jaro_winkler("", "") == 1.0
    assert jaro_winkler("abc", "") == 0.0


def test_similar_strings():
    score = jaro_winkler("design pattern", "design patterns")
    assert 0.9 < score <= 1.0


def test_prefix_bonus():
    jw = jaro_winkler("design rule", "design pattern")
    jaro = jaro_similarity("design rule", "design pattern")
    assert jw > jaro


def test_case_sensitivity():
    assert jaro_winkler("Hello", "hello") < 1.0


def test_near_duplicates_detected():
    assert (
        jaro_winkler("use guard clauses for validation", "use guard clause for validations") > 0.90
    )
