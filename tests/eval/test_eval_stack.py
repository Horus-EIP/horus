from eval_stack import parse_routing_decisions, routing_decision

MAS_METRICS_BEFORE = """# HELP mas_routing_decision_seconds Time the router took to choose a task's route
# TYPE mas_routing_decision_seconds histogram
mas_routing_decision_seconds_bucket{le="0.001",method="embedding"} 0.0
mas_routing_decision_seconds_bucket{le="+Inf",method="embedding"} 3.0
mas_routing_decision_seconds_count{method="embedding"} 3.0
mas_routing_decision_seconds_sum{method="embedding"} 0.036
mas_routing_decision_seconds_count{method="rules"} 1.0
mas_routing_decision_seconds_sum{method="rules"} 0.0004
# HELP mas_routing_decision_seconds_created Time the router took to choose a task's route
# TYPE mas_routing_decision_seconds_created gauge
mas_routing_decision_seconds_created{method="embedding"} 1.791212389653553e+09
mas_routing_decisions_total{method="embedding",route="SINGLE_AGENT"} 3.0
http_requests_total{handler="/metrics",method="GET",status="2xx"} 12.0
"""

MAS_METRICS_AFTER_ONE_LLM_DECISION = """# TYPE mas_routing_decision_seconds histogram
mas_routing_decision_seconds_count{method="embedding"} 3.0
mas_routing_decision_seconds_sum{method="embedding"} 0.036
mas_routing_decision_seconds_count{method="rules"} 1.0
mas_routing_decision_seconds_sum{method="rules"} 0.0004
mas_routing_decision_seconds_count{method="llm"} 1.0
mas_routing_decision_seconds_sum{method="llm"} 2.4
"""


class TestRoutingDecisions:
    def test_router_histogram_count_and_sum_per_method(self):
        assert parse_routing_decisions(MAS_METRICS_BEFORE) == {
            "embedding": {"count": 3.0, "seconds": 0.036},
            "rules": {"count": 1.0, "seconds": 0.0004},
        }

    def test_a_mas_without_the_router_histogram_gives_nothing(self):
        assert parse_routing_decisions('http_requests_total{method="GET"} 12.0\n') is None
        assert parse_routing_decisions(None) is None

    def test_a_router_that_has_not_decided_yet_gives_no_methods(self):
        assert parse_routing_decisions("# TYPE mas_routing_decision_seconds histogram\n") == {}

    def test_one_question_routed_by_the_llm(self):
        decision = routing_decision(
            parse_routing_decisions(MAS_METRICS_BEFORE),
            parse_routing_decisions(MAS_METRICS_AFTER_ONE_LLM_DECISION),
        )
        assert decision == {"decisions": 1, "methods": {"llm": 1}, "seconds": 2.4}

    def test_a_question_the_router_did_not_see(self):
        before = parse_routing_decisions(MAS_METRICS_BEFORE)
        assert routing_decision(before, dict(before)) == {"decisions": 0, "methods": {}, "seconds": 0.0}

    def test_counters_going_down_or_disappearing_mean_mas_restarted(self):
        before = parse_routing_decisions(MAS_METRICS_BEFORE)
        assert routing_decision(before, {"embedding": {"count": 1.0, "seconds": 0.01}}) == {"restarted": True}
        assert routing_decision(before, {}) == {"restarted": True}

    def test_missing_scrape_gives_no_decision(self):
        assert routing_decision(None, {}) is None
        assert routing_decision({}, None) is None
