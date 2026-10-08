# SPDX-License-Identifier: Apache-2.0
from horus_bench_kit.markdown import (
    EMPTY,
    Metric,
    MetricRow,
    cell,
    format_change,
    format_metric,
    format_number,
    row_change,
    short_hash,
    table,
)


class TestNumbers:
    def test_units_set_the_decimals(self):
        assert format_number(1234.567, "t/s") == "1,234.6 t/s"
        assert format_number(9.5, "t/s") == "9.50 t/s"
        assert format_number(66.66, "%") == "66.7%"
        assert format_number(7.9, "count") == "7"
        assert format_number(1.23456, "GiB") == "1.23 GiB"
        assert format_number(1.23456, "widgets") == "1.23 widgets"

    def test_metrics_show_their_count_and_note(self):
        assert format_metric(Metric(12.0, n=4, note="± 0.3"), "t/s") == "12.0 t/s (n=4, ± 0.3)"
        assert format_metric(Metric("b11382"), "text") == "b11382"
        assert format_metric(Metric(None, n=3), "s") == EMPTY
        assert format_metric(None, "s") == EMPTY


class TestChanges:
    def test_changes_by_unit(self):
        assert format_change(Metric(50.0), Metric(62.5), "%") == "+12.5 pts"
        assert format_change(Metric(3), Metric(1), "count") == "-2"
        assert format_change(Metric(20.0), Metric(25.0), "t/s") == "+5.00 t/s (+25%)"
        assert format_change(Metric(0.0), Metric(25.0), "t/s") == "+25.0 t/s"
        assert format_change(Metric("a"), Metric("a"), "text") == "same"
        assert format_change(Metric("a"), Metric("b"), "text") == "changed"
        assert format_change(None, Metric(1.0), "s") == ""

    def test_totals_over_different_counts_do_not_compare(self):
        row = MetricRow("total", "Total", "sum", "s", is_total=True)
        assert row_change(row, Metric(10.0, n=3), Metric(12.0, n=4)) == "not comparable: different question counts"
        assert row_change(row, Metric(10.0, n=3), Metric(12.0, n=3)) == "+2.00 s (+20%)"


class TestTables:
    def test_table_with_empty_cells_and_escaped_pipes(self):
        assert table(["", "run"], [["Label", "a|b"], ["Model", None]]) == [
            "|  | run |",
            "|---|---|",
            "| Label | a\\|b |",
            "| Model | — |",
        ]
        assert cell("") == EMPTY

    def test_short_hash_keeps_twelve_characters(self):
        assert short_hash("0123456789abcdef") == "0123456789ab…"
        assert short_hash("short") == "short"
        assert short_hash(None) is None
