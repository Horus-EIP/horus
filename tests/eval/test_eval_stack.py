import json

from eval_stack import (
    build_tag,
    llm_usage,
    parse_memory_events,
    parse_memory_stat,
    parse_process_status,
    parse_prometheus,
    parse_props,
    parse_routing_decisions,
    parse_server_args,
    parse_whole_number,
    routing_decision,
)

METRICS_BEFORE = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 1200
llamacpp:prompt_seconds_total 30.5
llamacpp:tokens_predicted_total 300
llamacpp:tokens_predicted_seconds_total 25
llamacpp:n_decode_total 310
llamacpp:requests_processing 0
"""

METRICS_AFTER = """llamacpp:prompt_tokens_total 3200
llamacpp:prompt_seconds_total 70.5
llamacpp:tokens_predicted_total 460
llamacpp:tokens_predicted_seconds_total 41
llamacpp:n_decode_total 472
llamacpp:requests_processing 1
"""

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

LLM_MEMORY_STAT = """anon 1879048192
file 2621440000
kernel 41943040
shmem 0
file_mapped 2550136832
file_dirty 0
active_anon 1879048192
inactive_anon 0
active_file 52428800
inactive_file 2569011200
unevictable 0
"""

LLAMA_SERVER_STATUS = """Name:\tllama-server
Umask:\t0022
State:\tS (sleeping)
Pid:\t1
VmRSS:\t 4329984 kB
RssAnon:\t 1835008 kB
RssFile:\t 2490368 kB
RssShmem:\t    4608 kB
Threads:\t8
"""

COMPOSE_CPU_COMMAND = [
    "--model", "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
    "--alias", "qwen3-4b",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--ctx-size", "8192",
    "--parallel", "1",
    "--load-mode", "mmap",
    "--cache-ram", "1024",
    "--threads", "6",
    "--metrics",
]


class TestPrometheus:
    def test_counters_are_read_and_comments_skipped(self):
        values = parse_prometheus(METRICS_BEFORE)
        assert values["llamacpp:prompt_tokens_total"] == 1200.0
        assert values["llamacpp:prompt_seconds_total"] == 30.5
        assert "# HELP" not in "".join(values)

    def test_labelled_and_malformed_lines_are_skipped(self):
        text = 'llamacpp:x{slot="0"} 4\nnot a metric line here\nllamacpp:y NaN\nllamacpp:z abc\n'
        values = parse_prometheus(text)
        assert "llamacpp:x" not in values
        assert "llamacpp:z" not in values
        assert values["llamacpp:y"] != values["llamacpp:y"]

    def test_nothing_read_gives_an_empty_dict(self):
        assert parse_prometheus(None) == {}


class TestLlmUsage:
    def test_question_usage_is_the_counter_difference(self):
        usage = llm_usage(parse_prometheus(METRICS_BEFORE), parse_prometheus(METRICS_AFTER))
        assert usage == {
            "prompt_tokens": 2000,
            "prompt_s": 40.0,
            "generated_tokens": 160,
            "generation_s": 16.0,
            "decode_calls": 162,
            "prompt_tps": 50.0,
            "generation_tps": 10.0,
        }

    def test_counters_going_down_mean_the_server_restarted(self):
        usage = llm_usage(parse_prometheus(METRICS_AFTER), parse_prometheus(METRICS_BEFORE))
        assert usage == {"restarted": True}

    def test_missing_scrape_gives_no_usage(self):
        assert llm_usage(None, parse_prometheus(METRICS_AFTER)) is None
        assert llm_usage(parse_prometheus(METRICS_BEFORE), {}) is None
        assert llm_usage({"other": 1.0}, {"other": 2.0}) is None

    def test_idle_server_has_no_rates(self):
        before = parse_prometheus(METRICS_BEFORE)
        usage = llm_usage(before, dict(before))
        assert usage["prompt_tokens"] == 0
        assert usage["prompt_tps"] is None
        assert usage["generation_tps"] is None


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


class TestServerArgs:
    def test_compose_command_of_the_cpu_overlay(self):
        settings = parse_server_args(COMPOSE_CPU_COMMAND)
        assert settings == {
            "model": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "alias": "qwen3-4b",
            "port": 8080,
            "ctx_size": 8192,
            "parallel": 1,
            "load_mode": "mmap",
            "cache_ram_mib": 1024,
            "threads": 6,
            "cache_type_k": "f16",
            "cache_type_v": "f16",
        }

    def test_short_flags_and_equals_form_set_the_kv_cache(self):
        settings = parse_server_args(["-c", "4096", "-ctk", "q8_0", "--cache-type-v=q8_0", "-fa", "on"])
        assert settings["ctx_size"] == 4096
        assert settings["cache_type_k"] == "q8_0"
        assert settings["cache_type_v"] == "q8_0"
        assert settings["flash_attn"] == "on"

    def test_unknown_switches_do_not_swallow_the_next_flag(self):
        settings = parse_server_args(["--metrics", "--threads", "4", "--jinja"])
        assert settings["threads"] == 4

    def test_no_arguments_mean_the_default_kv_cache(self):
        assert parse_server_args(None) == {"cache_type_k": "f16", "cache_type_v": "f16"}


class TestProps:
    def test_build_model_and_context_are_read(self):
        props = {
            "build_info": "b11382-11fe0215",
            "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "total_slots": 1,
            "default_generation_settings": {"n_ctx": 8192},
        }
        assert parse_props(json.dumps(props)) == {
            "build_info": "b11382-11fe0215",
            "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "n_ctx": 8192,
            "total_slots": 1,
        }

    def test_unreadable_props_give_nothing(self):
        assert parse_props(None) == {}
        assert parse_props("[1, 2]") == {}

    def test_build_tag_from_build_info_and_image_tags(self):
        assert build_tag("b11382-11fe0215") == "b11382"
        assert build_tag("server-b11382") == "b11382"
        assert build_tag("11382 (11fe0215)") == "b11382"
        assert build_tag("latest") is None
        assert build_tag(None) is None


class TestCgroup:
    def test_memory_peak_and_restart_count_are_whole_numbers(self):
        assert parse_whole_number("4294967296\n") == 4294967296
        assert parse_whole_number("3\n") == 3
        assert parse_whole_number("max") is None
        assert parse_whole_number("") is None
        assert parse_whole_number(None) is None

    def test_memory_events_count_oom_kills(self):
        events = "low 0\nhigh 0\nmax 12\noom 1\noom_kill 1\noom_group_kill 0\n"
        assert parse_memory_events(events)["oom_kill"] == 1
        assert parse_memory_events(None) == {}

    def test_memory_stat_keeps_the_page_cache_split(self):
        assert parse_memory_stat(LLM_MEMORY_STAT) == {
            "anon": 1879048192,
            "file": 2621440000,
            "active_file": 52428800,
            "inactive_file": 2569011200,
            "file_mapped": 2550136832,
        }

    def test_memory_stat_without_the_page_cache_split_is_unread(self):
        assert parse_memory_stat("total_cache 100\ntotal_rss 200\n") is None
        assert parse_memory_stat(None) is None


class TestProcessStatus:
    def test_resident_mapped_file_pages_of_llama_server(self):
        assert parse_process_status(LLAMA_SERVER_STATUS) == {"name": "llama-server", "rss_file_bytes": 2490368 * 1024}

    def test_a_kernel_without_rss_file_gives_no_figure(self):
        assert parse_process_status("Name:\tllama-server\nVmRSS:\t 100 kB\n") == {
            "name": "llama-server",
            "rss_file_bytes": None,
        }

    def test_an_unread_status_gives_nothing(self):
        assert parse_process_status(None) is None
        assert parse_process_status("") is None
