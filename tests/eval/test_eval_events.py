from eval_events import Observation, apply_event, fold_events, is_final_answer


def step(step_type, **metadata):
    return {"type": "task_step", "step_type": step_type, "metadata": metadata}


def titled_retrieval(*titles):
    return step("retrieval.results", chunk_count=len(titles), chunks=list(titles))


def live_retrieval():
    return step("retrieval.results", chunk_count=1, chunks=[])


def answer(content, skill_used=None, agent_name="Finance-Analyst", **extra):
    return {
        "type": "task_complete",
        "content": content,
        "agent_name": agent_name,
        "skill_used": skill_used,
        **extra,
    }


class TestFoldEvents:
    def test_single_agent_stream_gives_timings_sources_and_answer(self):
        observation = fold_events(
            [
                (0.5, step("retrieval.start")),
                (1.2, titled_retrieval("1_Q4_2025_Financial_Report.md")),
                (1.3, step("reasoning.start", model="qwen3-4b", device="cpu")),
                (9.8, step("reasoning.done", duration_seconds=8.5)),
                (10.1, answer("Q4 revenue was $4.2M.")),
            ]
        )
        assert observation.done
        assert observation.first_event_s == 0.5
        assert observation.retrieval_s == 1.2
        assert observation.reasoning_start_s == 1.3
        assert observation.total_s == 10.1
        assert observation.ttft_s is None
        assert observation.answer == "Q4 revenue was $4.2M."
        assert observation.answered_by == "Finance-Analyst"
        assert observation.retrieval_steps == 1
        assert observation.retrieved_sources == [["1_Q4_2025_Financial_Report.md"]]
        assert observation.cited_sources is None
        assert observation.models == ["qwen3-4b"]
        assert observation.devices == ["cpu"]

    def test_first_streamed_token_sets_time_to_first_token(self):
        observation = fold_events(
            [
                (2.0, step("reasoning.start")),
                (4.5, step("reasoning.delta", chunk="Q4", index=0)),
                (5.0, step("reasoning.delta", chunk=" revenue", index=1)),
                (7.0, answer("Q4 revenue was $4.2M.")),
            ]
        )
        assert observation.ttft_s == 4.5

    def test_manager_messages_are_not_the_final_answer(self):
        observation = fold_events(
            [
                (1.0, answer("Plan: two specialists.", skill_used="planning", agent_name="Manager")),
                (30.0, answer("Step 1 complete.", skill_used="orchestration")),
                (31.0, answer("Wrapping up.", skill_used="review")),
                (32.0, answer("Final answer.", skill_used="research")),
            ]
        )
        assert observation.answer == "Final answer."
        assert observation.total_s == 32.0

    def test_each_retrieval_of_a_chain_keeps_its_own_ranking(self):
        observation = fold_events(
            [
                (1.0, titled_retrieval("1_Q4_2025_Financial_Report.md")),
                (20.0, titled_retrieval("4_Expense_Policy.md", "1_Q4_2025_Financial_Report.md")),
                (40.0, answer("Sarah Johnson; above $5,000.")),
            ]
        )
        assert observation.retrieval_steps == 2
        assert observation.retrieved_sources == [
            ["1_Q4_2025_Financial_Report.md"],
            ["4_Expense_Policy.md", "1_Q4_2025_Financial_Report.md"],
        ]

    def test_live_retrieval_step_without_titles_makes_sources_unobservable(self):
        observation = fold_events([(1.0, live_retrieval()), (9.0, answer("Q4 revenue was $4.2M."))])
        assert observation.retrieval_steps == 1
        assert observation.retrieval_s == 1.0
        assert observation.retrieved_sources is None

    def test_one_untitled_retrieval_in_a_chain_hides_the_rankings(self):
        observation = fold_events(
            [(1.0, titled_retrieval("4_Expense_Policy.md")), (5.0, live_retrieval())]
        )
        assert observation.retrieval_steps == 2
        assert observation.retrieved_sources is None

    def test_retrieval_that_found_nothing_is_an_empty_ranking(self):
        observation = fold_events([(1.0, step("retrieval.results", chunk_count=0, chunks=[]))])
        assert observation.retrieved_sources == [[]]

    def test_stream_without_retrieval_has_no_rankings(self):
        observation = fold_events([(2.0, answer("Hello!"))])
        assert observation.retrieval_steps == 0
        assert observation.retrieved_sources == []

    def test_late_retrieval_step_after_the_answer_still_counts(self):
        observation = fold_events(
            [
                (5.0, answer("$250 per night.")),
                (5.2, titled_retrieval("4_Expense_Policy.md")),
                (5.3, answer("a second answer")),
            ]
        )
        assert observation.answer == "$250 per night."
        assert observation.total_s == 5.0
        assert observation.retrieved_sources == [["4_Expense_Policy.md"]]

    def test_sources_cited_by_the_answer_are_kept(self):
        observation = fold_events(
            [(3.0, answer("$250.", sources=[{"doc_id": "a1", "title": "4_Expense_Policy.md"}]))]
        )
        assert observation.cited_sources == ["4_Expense_Policy.md"]

    def test_answer_with_an_empty_sources_list_cites_nothing(self):
        observation = fold_events([(3.0, answer("Hi!", sources=[]))])
        assert observation.cited_sources == []

    def test_legacy_agent_message_counts_as_an_answer(self):
        observation = fold_events([(2.0, {"type": "agent", "content": "Hello!"})])
        assert observation.done and observation.answer == "Hello!"

    def test_heartbeats_and_status_frames_do_not_count_as_task_events(self):
        observation = fold_events(
            [
                (0.1, {"type": "task_status", "status": "queued", "seq": 1}),
                (5.0, {"type": "heartbeat", "elapsed_s": 5.0, "seq": 2}),
                (6.0, step("retrieval.start")),
            ]
        )
        assert observation.events == 1
        assert observation.first_event_s == 6.0

    def test_the_route_of_the_final_answer_is_kept(self):
        observation = fold_events(
            [(1.0, {"type": "agent", "content": "4", "event": "result", "route": "direct_answer"})]
        )
        assert observation.route == "direct_answer"

    def test_an_answer_without_a_route_leaves_it_unknown(self):
        observation = fold_events([(1.0, answer("Revenue grew 12%."))])
        assert observation.route is None

    def test_stream_without_an_answer_is_not_done(self):
        observation = fold_events([(1.0, step("retrieval.start")), (2.0, {"type": "pong"})])
        assert not observation.done
        assert observation.events == 2
        assert observation.answer is None


class TestRoutingTime:
    def test_routing_ends_with_the_first_frame_past_the_routing_stage(self):
        observation = fold_events(
            [
                (0.1, {"type": "task_status", "status": "queued", "stage": "queued"}),
                (0.2, {"type": "task_status", "status": "routing", "stage": "routing"}),
                (5.0, {"type": "heartbeat", "elapsed_s": 5.0, "stage": "routing"}),
                (7.4, {"type": "task_status", "status": "running", "stage": "retrieval"}),
                (8.0, {**step("retrieval.start"), "stage": "retrieval"}),
                (30.0, {**answer("Q4 revenue was $4.2M."), "stage": "generation"}),
            ]
        )
        assert observation.routing_s == 7.4

    def test_heartbeat_past_routing_ends_it_when_the_status_frame_was_missed(self):
        observation = fold_events(
            [
                (0.2, {"type": "task_status", "status": "routing", "stage": "routing"}),
                (10.0, {"type": "heartbeat", "elapsed_s": 10.0, "stage": "generation"}),
            ]
        )
        assert observation.routing_s == 10.0

    def test_direct_answer_ends_routing_with_the_answer(self):
        observation = fold_events(
            [
                (0.2, {"type": "task_status", "status": "routing", "stage": "routing"}),
                (0.9, {"type": "agent", "content": "Hello!", "event": "result", "stage": "routing"}),
            ]
        )
        assert observation.routing_s == 0.9

    def test_frames_without_a_stage_leave_routing_time_unknown(self):
        observation = fold_events([(1.0, step("retrieval.start")), (9.0, answer("$250."))])
        assert observation.routing_s is None


class TestEventHelpers:
    def test_is_final_answer_skips_steps_and_manager_skills(self):
        assert is_final_answer(answer("x", skill_used="research"))
        assert not is_final_answer(answer("x", skill_used="planning"))
        assert not is_final_answer(step("reasoning.done"))

    def test_apply_event_ignores_malformed_metadata(self):
        observation = Observation()
        apply_event(observation, {"type": "task_step", "step_type": "retrieval.results", "metadata": {"chunks": "oops"}}, 1.0)
        apply_event(observation, {"type": "task_step", "step_type": "reasoning.start", "metadata": None}, 2.0)
        apply_event(observation, {"type": "task_step", "step_type": "reasoning.start", "metadata": "x"}, 3.0)
        assert observation.retrieval_steps == 1
        assert observation.retrieved_sources is None
        assert observation.models == []
        assert observation.reasoning_start_s == 2.0
