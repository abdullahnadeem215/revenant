from sample_pkg.stats import mean


def test_mean_of_three() -> None:
    assert mean([1.0, 2.0, 3.0]) == 2.0
