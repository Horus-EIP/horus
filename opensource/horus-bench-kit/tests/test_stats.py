# SPDX-License-Identifier: Apache-2.0
from horus_bench_kit.stats import rate, stats


class TestRate:
    def test_rate_ignores_unscored_values(self):
        assert rate([True, False, None, True]) == {"n": 3, "correct": 2, "pct": 66.7}

    def test_nothing_scored_has_no_percentage(self):
        assert rate([None]) == {"n": 0, "correct": 0, "pct": None}
        assert rate([]) == {"n": 0, "correct": 0, "pct": None}


class TestStats:
    def test_stats_of_known_values(self):
        assert stats([3.0, None, 1.0, 2.0]) == {
            "n": 3,
            "mean": 2.0,
            "median": 2.0,
            "p90": 3.0,
            "min": 1.0,
            "max": 3.0,
            "sum": 6.0,
        }

    def test_no_value_gives_only_a_count(self):
        assert stats([None]) == {"n": 0}
        assert stats([]) == {"n": 0}

    def test_p90_is_the_value_at_index_n_times_0_9(self):
        assert stats(list(range(1, 11)))["p90"] == 10
        assert stats(list(range(1, 21)))["p90"] == 19

    def test_values_are_rounded_to_three_decimals(self):
        result = stats([0.12345, 0.98765])
        assert (result["min"], result["max"], result["sum"]) == (0.123, 0.988, 1.111)
