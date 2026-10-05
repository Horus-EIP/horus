"""Behavioural coverage for the three "reasoning" agent modules.

Targets:
- ai_agents.decision_making_agent
- ai_agents.knowledge_retrieval_agent
- ai_agents.rag_pipeline

Environment is hermetic: ``tests/agent/conftest.py`` installs MagicMock stand-ins
for ``torch``/``transformers``/``langchain`` in ``sys.modules`` and an autouse
fixture stubs ``AutoTokenizer.from_pretrained`` / ``AutoModelForCausalLM.from_pretrained``
so no Hugging Face weights are ever downloaded.

Because ``torch`` is a bare ``MagicMock`` here, a couple of helpers behave in
torch-flavoured ways that real torch would not (e.g. ``torch.cuda.is_available()``
returns a truthy MagicMock by default). Tests that care patch those explicitly
so the assertions stay meaningful rather than asserting "a mock returned a mock".
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ai_agents.decision_making_agent as dma
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.knowledge_retrieval_agent import (
    KnowledgeRetrievalAgent,
    _summarize_retrieved,
)
from ai_agents.rag_pipeline import RAGPipeline

# ---------------------------------------------------------------------------
# Helpers: build tokenizer / model mocks that drive the real _generate_causal
# path deterministically.
# ---------------------------------------------------------------------------


def _make_tokenizer(decoded: str = "  clean answer  ") -> MagicMock:
    """A tokenizer mock matching what _generate_causal expects."""
    tok = MagicMock()
    tok.apply_chat_template.return_value = "formatted-prompt"

    enc = MagicMock()
    ids = MagicMock()
    ids.to.return_value = ids
    ids.size.return_value = 3  # prompt length -> slice offset for gen_only
    attn = MagicMock()
    attn.to.return_value = attn
    enc.__getitem__.side_effect = lambda k: ids if k == "input_ids" else attn
    enc.get.return_value = attn

    def tok_call(*args, **kwargs):
        # _generate_causal calls tok(phrase, add_special_tokens=False) to build
        # bad_words_ids; return an object with .input_ids for those calls.
        if kwargs.get("add_special_tokens") is False:
            m = MagicMock()
            m.input_ids = [7]
            return m
        return enc

    tok.side_effect = tok_call
    tok.eos_token_id = 0
    tok.decode.return_value = decoded
    return tok


def _make_model() -> MagicMock:
    model = MagicMock()
    seq = MagicMock()
    seq.__getitem__.return_value = "gen_only_tokens"
    gen_ret = MagicMock()
    gen_ret.sequences = [seq]
    model.generate.return_value = gen_ret
    return model


def _causal_agent(decoded: str = "  clean answer  ") -> DecisionMakingAgent:
    """A DecisionMakingAgent wired for the local-causal generation path.

    Built via __new__ so we skip __init__'s model-loading entirely and inject
    our own tokenizer/model mocks.
    """
    agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
    agent.model_name = "test-model"
    agent.device = "cpu"
    agent.decision_model = None
    agent._causal_tokenizer = _make_tokenizer(decoded)
    agent._causal_model = _make_model()
    return agent


# ===========================================================================
# decision_making_agent: module-level helper functions
# ===========================================================================


class TestDecisionHelpers:
    def test_is_degenerate_output_short_text(self):
        # Anything under 200 chars is never flagged regardless of markers.
        assert dma._is_degenerate_output("wait, no — actually, wait,") is False

    def test_is_degenerate_output_empty(self):
        assert dma._is_degenerate_output("") is False

    def test_is_degenerate_output_clean_long_text(self):
        text = "This is a perfectly normal answer. " * 20
        assert dma._is_degenerate_output(text) is False

    def test_is_degenerate_output_spiral(self):
        # >= 5 markers in a >=200 char body -> flagged as a self-correction loop.
        spiral = (
            "padding " * 30
            + "wait — no — actually, but actually we conclude we surrender "
            "impossible absurd"
        )
        assert len(spiral) >= 200
        assert dma._is_degenerate_output(spiral) is True

    def test_normalize_model_text_folds_full_width_digits_and_ideographic_full_stop(self):
        assert dma._normalize_model_text("Ｑ４ ２０２５ $4。2M") == "Q4 2025 $4.2M"

    def test_normalize_model_text_folds_halfwidth_ideographic_full_stop(self):
        assert dma._normalize_model_text("$4｡2M") == "$4.2M"

    def test_normalize_model_text_leaves_plain_markdown_unchanged(self):
        text = "## Q4 2025\n- **Revenue:** $4.2M — up 12% → ahead of plan"
        assert dma._normalize_model_text(text) == text

    def test_max_new_tokens_default(self, monkeypatch):
        monkeypatch.delenv("AGENT_MAX_NEW_TOKENS", raising=False)
        assert dma._max_new_tokens() == 256

    def test_max_new_tokens_floor(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_NEW_TOKENS", "2")
        assert dma._max_new_tokens() == 8  # clamped up to minimum of 8

    def test_max_new_tokens_custom(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_NEW_TOKENS", "512")
        assert dma._max_new_tokens() == 512

    def test_max_new_tokens_invalid(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_NEW_TOKENS", "not-a-number")
        assert dma._max_new_tokens() == 256  # ValueError fallback

    def test_lazy_model_enabled_true(self, monkeypatch):
        monkeypatch.setenv("AGENT_LAZY_DECISION_MODEL", "TRUE")
        assert dma._lazy_model_enabled() is True

    def test_lazy_model_enabled_false(self, monkeypatch):
        monkeypatch.setenv("AGENT_LAZY_DECISION_MODEL", "0")
        assert dma._lazy_model_enabled() is False

    def test_agent_force_cpu(self, monkeypatch):
        monkeypatch.setenv("AGENT_FORCE_CPU", "yes")
        assert dma._agent_force_cpu() is True
        monkeypatch.setenv("AGENT_FORCE_CPU", "")
        assert dma._agent_force_cpu() is False

    def test_accelerate_max_memory_unset(self, monkeypatch):
        monkeypatch.delenv("AGENT_GPU_MEMORY_CAP", raising=False)
        monkeypatch.delenv("LLM_GPU_MEMORY_CAP", raising=False)
        assert dma._agent_accelerate_max_memory() is None

    def test_accelerate_max_memory_default_cpu(self, monkeypatch):
        monkeypatch.setenv("AGENT_GPU_MEMORY_CAP", "10GiB")
        monkeypatch.delenv("AGENT_CPU_OFFLOAD_CAP", raising=False)
        monkeypatch.delenv("LLM_CPU_OFFLOAD_CAP", raising=False)
        assert dma._agent_accelerate_max_memory() == {0: "10GiB", "cpu": "8GiB"}

    def test_accelerate_max_memory_custom_cpu(self, monkeypatch):
        monkeypatch.setenv("AGENT_GPU_MEMORY_CAP", "20GiB")
        monkeypatch.setenv("AGENT_CPU_OFFLOAD_CAP", "4GiB")
        assert dma._agent_accelerate_max_memory() == {0: "20GiB", "cpu": "4GiB"}

    def test_resolve_local_model_dir_explicit(self, monkeypatch):
        monkeypatch.setenv("MODEL_DIR", "/tmp/explicit-model-dir")
        assert str(dma._resolve_local_model_dir()) == "/tmp/explicit-model-dir"

    def test_resolve_local_model_dir_default(self, monkeypatch):
        monkeypatch.delenv("MODEL_DIR", raising=False)
        resolved = dma._resolve_local_model_dir()
        # Leaf of the default model id, nested under app/models.
        assert resolved.name == dma.DEFAULT_MODEL_ID.split("/")[-1]
        assert resolved.parent.name == "models"

    def test_local_model_ready_missing_dir(self, tmp_path):
        with patch.object(dma, "LOCAL_MODEL_DIR", tmp_path / "missing"):
            assert dma._local_model_ready() is False

    def test_local_model_ready_missing_files(self, tmp_path):
        # Directory exists but required files are absent.
        with patch.object(dma, "LOCAL_MODEL_DIR", tmp_path):
            assert dma._local_model_ready() is False

    def test_local_model_ready_all_present(self, tmp_path):
        for fname in dma.REQUIRED_LOCAL_FILES:
            (tmp_path / fname).write_text("x")
        with patch.object(dma, "LOCAL_MODEL_DIR", tmp_path):
            assert dma._local_model_ready() is True

    def test_configure_torch_threads_explicit(self, monkeypatch):
        monkeypatch.setenv("AGENT_TORCH_INTRAOP_THREADS", "3")
        fake_torch = MagicMock()
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            dma._configure_agent_torch_threads()
        fake_torch.set_num_threads.assert_called_once_with(3)

    def test_configure_torch_threads_invalid_value(self, monkeypatch):
        monkeypatch.setenv("AGENT_TORCH_INTRAOP_THREADS", "garbage")
        fake_torch = MagicMock()
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            dma._configure_agent_torch_threads()
        # Falls back to min(8, cpu_count) -> a positive int, never the bad string.
        (called_with,), _ = fake_torch.set_num_threads.call_args
        assert isinstance(called_with, int) and called_with >= 1

    def test_configure_torch_threads_noop_without_torch(self):
        with patch.object(dma, "_TORCH_AVAILABLE", False):
            # Must simply return without touching torch.
            assert dma._configure_agent_torch_threads() is None

    def test_bnb4bit_selects_bf16_on_capable_gpu(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = True
        fake_torch.cuda.is_bf16_supported.return_value = True
        fake_torch.bfloat16 = "BF16"
        fake_torch.float16 = "F16"
        fake_bnb = MagicMock()
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "BitsAndBytesConfig", fake_bnb
        ):
            dma._bnb4bit()
        # bf16-capable GPU -> compute dtype is bfloat16.
        assert fake_bnb.call_args.kwargs["bnb_4bit_compute_dtype"] == "BF16"
        assert fake_bnb.call_args.kwargs["load_in_4bit"] is True

    def test_bnb4bit_selects_f16_without_bf16(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        fake_torch.bfloat16 = "BF16"
        fake_torch.float16 = "F16"
        fake_bnb = MagicMock()
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "BitsAndBytesConfig", fake_bnb
        ):
            dma._bnb4bit()
        # No bf16 support -> falls back to float16.
        assert fake_bnb.call_args.kwargs["bnb_4bit_compute_dtype"] == "F16"


class TestDetectDevice:
    def test_auto_selects_cuda(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = True
        fake_torch.cuda.get_device_name.return_value = "Tesla"
        fake_torch.version.cuda = "12.1"
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            assert dma.detect_device("auto") == "cuda"

    def test_auto_selects_cpu_when_no_cuda(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            assert dma.detect_device("auto") == "cpu"

    def test_auto_cpu_when_torch_unavailable(self):
        with patch.object(dma, "_TORCH_AVAILABLE", False):
            assert dma.detect_device("auto") == "cpu"

    def test_cuda_request_falls_back_to_cpu(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            assert dma.detect_device("cuda:0") == "cpu"

    def test_cuda_request_passthrough_when_available(self):
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = True
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_TORCH_AVAILABLE", True
        ):
            assert dma.detect_device("cuda:0") == "cuda:0"

    def test_explicit_cpu_passthrough(self):
        assert dma.detect_device("cpu") == "cpu"


class TestModelDevice:
    def test_uses_first_parameter_device(self):
        model = MagicMock()
        param = MagicMock()
        param.device = "cuda:1"
        model.parameters.return_value = iter([param])
        assert dma._model_device(model) == "cuda:1"

    def test_falls_back_to_torch_device_when_no_params(self):
        model = MagicMock()
        model.parameters.return_value = iter([])  # StopIteration path
        model.device = None  # getattr returns None -> final torch.device branch
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        fake_torch.device.side_effect = lambda s: f"torch.device({s})"
        with patch.object(dma, "torch", fake_torch):
            assert dma._model_device(model) == "torch.device(cpu)"

    def test_wraps_string_device_attribute(self):
        model = MagicMock()
        model.parameters.return_value = iter([])
        model.device = "cpu"  # a str, not a torch.device instance
        fake_torch = MagicMock()

        class FakeDevice:
            # Used both as the isinstance target *and* the factory the code
            # calls as torch.device(str(dev)).
            def __init__(self, spec):
                self.spec = spec

        fake_torch.device = FakeDevice
        with patch.object(dma, "torch", fake_torch):
            result = dma._model_device(model)
        # "cpu" is not a FakeDevice instance -> torch.device("cpu") constructed.
        assert isinstance(result, FakeDevice)
        assert result.spec == "cpu"


# ===========================================================================
# decision_making_agent: DecisionMakingAgent.__init__ branches
# ===========================================================================


class TestDecisionAgentInit:
    def test_init_with_injected_model_skips_loading(self):
        sentinel = MagicMock()
        agent = DecisionMakingAgent(decision_model=sentinel, device="cpu")
        assert agent.decision_model is sentinel
        assert agent.device == "cpu"
        # Injected model means no causal model/tokenizer were ever loaded.
        assert agent._causal_model is None
        assert agent._causal_tokenizer is None

    def test_init_custom_model_name(self):
        agent = DecisionMakingAgent(
            decision_model=MagicMock(), model_name="my/model", device="cpu"
        )
        assert agent.model_name == "my/model"

    def test_init_default_model_name(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        assert agent.model_name == dma.DEFAULT_MODEL_ID

    def test_init_raises_without_transformers(self):
        with patch.object(dma, "_TRANSFORMERS_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="needs transformers/torch"):
                DecisionMakingAgent(device="cpu")

    def test_init_lazy_defers_model_load(self, monkeypatch):
        monkeypatch.setenv("AGENT_LAZY_DECISION_MODEL", "1")
        with patch.object(
            DecisionMakingAgent, "_load_causal_model"
        ) as load:
            agent = DecisionMakingAgent(device="cpu")
        # Lazy mode: model load is NOT called during construction.
        load.assert_not_called()
        assert agent._lazy is True

    def test_init_eager_loads_model(self, monkeypatch):
        monkeypatch.setenv("AGENT_LAZY_DECISION_MODEL", "0")
        with patch.object(
            DecisionMakingAgent, "_load_causal_model"
        ) as load:
            agent = DecisionMakingAgent(device="cpu")
        load.assert_called_once()
        assert agent._lazy is False


# ===========================================================================
# decision_making_agent: _resolve_model_path / _use_gpu_for_load / loading
# ===========================================================================


class TestModelPathAndGpu:
    def test_resolve_model_path_local_ready(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        with patch.object(dma, "_local_model_ready", return_value=True), patch.object(
            dma, "LOCAL_MODEL_DIR", "/some/local/dir"
        ):
            assert agent._resolve_model_path() == "/some/local/dir"

    def test_resolve_model_path_falls_back_to_name(self):
        agent = DecisionMakingAgent(
            decision_model=MagicMock(), model_name="hub/model", device="cpu"
        )
        with patch.object(dma, "_local_model_ready", return_value=False):
            assert agent._resolve_model_path() == "hub/model"

    def test_use_gpu_false_when_force_cpu(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cuda")
        with patch.object(dma, "_agent_force_cpu", return_value=True):
            assert agent._use_gpu_for_load() is False

    def test_use_gpu_false_on_cpu_device(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        with patch.object(dma, "_agent_force_cpu", return_value=False):
            assert agent._use_gpu_for_load() is False

    def test_use_gpu_true_on_cuda_device_with_cuda(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        agent.device = "cuda:0"
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = True
        with patch.object(dma, "_agent_force_cpu", return_value=False), patch.object(
            dma, "torch", fake_torch
        ):
            assert agent._use_gpu_for_load() is True


class TestLoadCausalModel:
    def _bare_agent(self) -> DecisionMakingAgent:
        agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
        agent.model_name = "test/model"
        agent.device = "cpu"
        agent.decision_model = None
        agent._causal_tokenizer = None
        agent._causal_model = None
        import threading

        agent._load_lock = threading.Lock()
        return agent

    def test_load_cpu_path(self):
        agent = self._bare_agent()
        tok = MagicMock()
        model = MagicMock()
        with patch.object(agent, "_resolve_model_path", return_value="p"), patch.object(
            agent, "_use_gpu_for_load", return_value=False
        ), patch.object(
            dma.AutoTokenizer, "from_pretrained", return_value=tok
        ), patch.object(
            dma.AutoModelForCausalLM, "from_pretrained", return_value=model
        ) as load_model, patch.object(
            dma, "_model_device", return_value="cpu"
        ):
            agent._load_causal_model()
        assert agent._causal_tokenizer is tok
        assert agent._causal_model is model
        model.eval.assert_called_once()
        # CPU path -> device_map pins everything to cpu.
        _, kwargs = load_model.call_args
        assert kwargs["device_map"] == {"": "cpu"}

    def test_load_already_loaded_is_noop(self):
        agent = self._bare_agent()
        agent._causal_tokenizer = MagicMock()
        agent._causal_model = MagicMock()
        with patch.object(
            dma.AutoModelForCausalLM, "from_pretrained"
        ) as load_model:
            agent._load_causal_model()
        load_model.assert_not_called()

    def test_load_gpu_path_success(self):
        agent = self._bare_agent()
        agent.device = "cuda:0"
        tok = MagicMock()
        model = MagicMock()
        with patch.object(agent, "_resolve_model_path", return_value="p"), patch.object(
            agent, "_use_gpu_for_load", return_value=True
        ), patch.object(
            dma, "_agent_accelerate_max_memory", return_value=None
        ), patch.object(dma, "_bnb4bit", return_value="bnb-cfg"), patch.object(
            dma.AutoTokenizer, "from_pretrained", return_value=tok
        ), patch.object(
            dma.AutoModelForCausalLM, "from_pretrained", return_value=model
        ) as load_model, patch.object(
            dma, "_model_device", return_value="cuda:0"
        ):
            agent._load_causal_model()
        assert agent._causal_model is model
        _, kwargs = load_model.call_args
        assert kwargs["device_map"] == "auto"
        assert kwargs["quantization_config"] == "bnb-cfg"

    def test_load_gpu_path_with_max_memory(self):
        agent = self._bare_agent()
        agent.device = "cuda:0"
        with patch.object(agent, "_resolve_model_path", return_value="p"), patch.object(
            agent, "_use_gpu_for_load", return_value=True
        ), patch.object(
            dma, "_agent_accelerate_max_memory", return_value={0: "10GiB"}
        ), patch.object(dma, "_bnb4bit", return_value="bnb-cfg"), patch.object(
            dma.AutoTokenizer, "from_pretrained", return_value=MagicMock()
        ), patch.object(
            dma.AutoModelForCausalLM, "from_pretrained", return_value=MagicMock()
        ) as load_model, patch.object(
            dma, "_model_device", return_value="cuda:0"
        ):
            agent._load_causal_model()
        _, kwargs = load_model.call_args
        assert kwargs["max_memory"] == {0: "10GiB"}
        assert "offload_folder" in kwargs

    def test_load_gpu_failure_falls_back_to_cpu(self):
        agent = self._bare_agent()
        agent.device = "cuda:0"
        cpu_model = MagicMock()

        def from_pretrained(path, **kwargs):
            # First (GPU) call raises; second (CPU) call succeeds.
            if kwargs.get("device_map") == "auto":
                raise RuntimeError("CUDA OOM")
            return cpu_model

        with patch.object(agent, "_resolve_model_path", return_value="p"), patch.object(
            agent, "_use_gpu_for_load", return_value=True
        ), patch.object(
            dma, "_agent_accelerate_max_memory", return_value=None
        ), patch.object(dma, "_bnb4bit", return_value="bnb-cfg"), patch.object(
            dma.AutoTokenizer, "from_pretrained", return_value=MagicMock()
        ), patch.object(
            dma.AutoModelForCausalLM, "from_pretrained", side_effect=from_pretrained
        ), patch.object(dma, "_model_device", return_value="cpu"):
            agent._load_causal_model()
        # After GPU failure the agent retries on CPU and flips its device.
        assert agent._causal_model is cpu_model
        assert agent.device == "cpu"

    def test_load_cpu_failure_raises_runtime_error(self):
        agent = self._bare_agent()
        with patch.object(agent, "_resolve_model_path", return_value="p"), patch.object(
            agent, "_use_gpu_for_load", return_value=False
        ), patch.object(
            dma.AutoTokenizer, "from_pretrained", return_value=MagicMock()
        ), patch.object(
            dma.AutoModelForCausalLM,
            "from_pretrained",
            side_effect=OSError("no disk"),
        ):
            with pytest.raises(RuntimeError, match="Could not load the Hugging Face"):
                agent._load_causal_model()


class TestEnsureCausalLoaded:
    def test_skips_when_injected_model(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        with patch.object(agent, "_load_causal_model") as load:
            agent._ensure_causal_loaded()
        load.assert_not_called()

    def test_skips_when_already_loaded(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        agent.decision_model = None
        agent._causal_model = MagicMock()
        with patch.object(agent, "_load_causal_model") as load:
            agent._ensure_causal_loaded()
        load.assert_not_called()

    def test_loads_when_needed(self):
        agent = DecisionMakingAgent(decision_model=MagicMock(), device="cpu")
        agent.decision_model = None
        agent._causal_model = None
        with patch.object(agent, "_load_causal_model") as load:
            agent._ensure_causal_loaded()
        load.assert_called_once()


# ===========================================================================
# decision_making_agent: _coerce_callable_output
# ===========================================================================


class TestCoerceCallableOutput:
    def test_generated_text_list_shape(self):
        out = DecisionMakingAgent._coerce_callable_output(
            [{"generated_text": "  hello  "}]
        )
        assert out == "hello"

    def test_plain_string(self):
        assert DecisionMakingAgent._coerce_callable_output("  raw  ") == "raw"

    def test_non_string_object(self):
        assert DecisionMakingAgent._coerce_callable_output(42) == "42"

    def test_empty_list(self):
        # Empty list does not match the generated_text shape -> str([]).
        assert DecisionMakingAgent._coerce_callable_output([]) == "[]"


# ===========================================================================
# decision_making_agent: _generate_causal
# ===========================================================================


class TestGenerateCausal:
    def test_returns_decoded_generation(self):
        agent = _causal_agent(decoded="  the generated text  ")
        with patch.object(dma, "_model_device", return_value="cpu"):
            out = agent._generate_causal("user msg", "system msg")
        assert out == "the generated text"
        # The chat template was applied to a system+user message pair.
        agent._causal_tokenizer.apply_chat_template.assert_called_once()
        msgs = agent._causal_tokenizer.apply_chat_template.call_args[0][0]
        assert msgs[0]["role"] == "system" and msgs[0]["content"] == "system msg"
        assert msgs[1]["role"] == "user" and msgs[1]["content"] == "user msg"
        agent._causal_model.generate.assert_called_once()

    def test_no_attn_mask_and_no_cuda_and_empty_bad_words(self):
        # Exercises the branches where: there is no attention_mask, CUDA is
        # unavailable (so empty_cache is skipped), and a bad-word phrase encodes
        # to empty ids (so it is not appended).
        agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
        agent.model_name = "m"
        agent.device = "cpu"
        agent.decision_model = None

        tok = MagicMock()
        tok.apply_chat_template.return_value = "prompt"
        ids = MagicMock()
        ids.to.return_value = ids
        ids.size.return_value = 3
        enc = MagicMock()
        enc.__getitem__.side_effect = lambda k: ids
        enc.get.return_value = None  # no attention_mask

        def tok_call(*args, **kwargs):
            if kwargs.get("add_special_tokens") is False:
                # Every anti-loop phrase encodes to empty ids -> skipped.
                m = MagicMock()
                m.input_ids = []
                return m
            return enc

        tok.side_effect = tok_call
        tok.eos_token_id = 0
        tok.decode.return_value = "no-cuda answer"
        agent._causal_tokenizer = tok

        model = MagicMock()
        seq = MagicMock()
        seq.__getitem__.return_value = "gen"
        gen_ret = MagicMock()
        gen_ret.sequences = [seq]
        model.generate.return_value = gen_ret
        agent._causal_model = model

        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        with patch.object(dma, "torch", fake_torch), patch.object(
            dma, "_model_device", return_value="cpu"
        ):
            out = agent._generate_causal("u", "s")
        assert out == "no-cuda answer"
        # CUDA unavailable -> empty_cache never called.
        fake_torch.cuda.empty_cache.assert_not_called()
        # No bad_words collected -> generate called with bad_words_ids=None.
        assert model.generate.call_args.kwargs["bad_words_ids"] is None


def _capture_delta_chunks():
    chunks: list[str] = []

    def fake_emit(step_type, title, detail="", **md):
        if step_type == "reasoning.delta":
            chunks.append(md["chunk"])

    return chunks, fake_emit


def _sse_line(payload: dict) -> bytes:
    return ("data: " + json.dumps(payload)).encode("utf-8")


class TestStreamingNormalization:
    def _stream_causal(self, pieces: list[str]) -> list[str]:
        agent = _causal_agent()
        chunks, fake_emit = _capture_delta_chunks()
        with patch.object(
            dma, "TextIteratorStreamer", MagicMock(return_value=pieces)
        ), patch("ai_agents.step_emitter.emit_step", fake_emit):
            out = agent._generate_streaming(
                agent._causal_model, agent._causal_tokenizer, {}
            )
        assert out is agent._causal_model.generate.return_value
        return chunks

    def test_short_streamed_answer_is_emitted_normalized(self):
        chunks = self._stream_causal(["Ｑ４ ", "２０２５ ", "$4。2M"])
        assert chunks == ["Q4 2025 $4.2M"]

    def test_long_streamed_answer_is_emitted_normalized_in_every_flush(self):
        held = "Ｑ４ ２０２５ revenue " * 40
        chunks = self._stream_causal([held, "$4。2M"])
        assert chunks == ["Q4 2025 revenue " * 40, "$4.2M"]

    def test_vllm_streamed_answer_is_emitted_and_returned_normalized(self):
        agent = _causal_agent()
        resp = MagicMock()
        resp.iter_lines.return_value = [
            _sse_line({"choices": [{"delta": {"content": "Ｑ４ ２０２５ "}}]}),
            _sse_line({"choices": [{"delta": {"content": "$4。2M"}}]}),
            _sse_line(
                {"choices": [], "usage": {"completion_tokens": 5, "prompt_tokens": 9}}
            ),
            b"data: [DONE]",
        ]
        post = MagicMock()
        post.return_value.__enter__.return_value = resp
        chunks, fake_emit = _capture_delta_chunks()
        with patch("requests.post", post), patch(
            "ai_agents.step_emitter.emit_step", fake_emit
        ):
            out = agent._generate_vllm_streaming(
                [{"role": "user", "content": "Q?"}], 64
            )
        assert out == "Q4 2025 $4.2M"
        assert chunks == ["Q4 2025 $4.2M"]
        assert agent._last_gen_tokens == 5


class TestSpiralEarlyStop:
    PROMPT_LEN = 10

    def _stops(self, decoded: str, generated: int = dma._EARLY_STOP_MIN_TOKENS) -> bool:
        tokenizer = MagicMock()
        tokenizer.decode.return_value = decoded
        input_ids = MagicMock()
        input_ids.shape = (1, self.PROMPT_LEN + generated)
        return dma._generated_tail_spirals(tokenizer, input_ids, self.PROMPT_LEN)

    def test_waits_for_enough_generated_tokens(self):
        assert not self._stops("wait, actually, " * 20, generated=dma._EARLY_STOP_MIN_TOKENS - 1)

    def test_stops_on_a_spiral_written_with_full_width_punctuation(self):
        assert self._stops("revenue " * 30 + "wait， actually， " * 5)

    def test_stops_on_a_spiral_written_in_full_width_letters(self):
        assert self._stops("revenue " * 30 + "ｗａｉｔ， ａｃｔｕａｌｌｙ， " * 5)

    def test_stops_on_an_ascii_spiral(self):
        assert self._stops("revenue " * 30 + "wait, actually, " * 5)

    def test_keeps_generating_a_clean_full_width_answer(self):
        assert not self._stops("Ｑ４ ２０２５ revenue was $4。2M. " * 20)


# ===========================================================================
# decision_making_agent: decide()
# ===========================================================================


class TestDecide:
    def test_decide_injected_no_context(self):
        model = MagicMock(return_value="plain response")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        out = agent.decide("hello there")
        assert out == "plain response"
        # No-context path forwards the query as the user message; the prompt
        # should literally contain the query text.
        prompt = model.call_args[0][0]
        assert "hello there" in prompt

    def test_decide_injected_with_context(self):
        model = MagicMock(return_value=[{"generated_text": "grounded answer"}])
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        out = agent.decide("What is revenue?", context="Revenue was $5M.")
        assert out == "grounded answer"
        # Context path builds a grounded prompt embedding both context + query.
        prompt = model.call_args[0][0]
        assert "Revenue was $5M." in prompt
        assert "What is revenue?" in prompt

    def test_decide_causal_path_no_injected_model(self):
        agent = _causal_agent(decoded="causal output")
        with patch.object(dma, "_model_device", return_value="cpu"), patch.object(
            agent, "_ensure_causal_loaded"
        ):
            out = agent.decide("Q?", context="some context")
        assert out == "causal output"

    def test_decide_applies_persona_prefix(self):
        captured = {}

        def model(prompt):
            captured["prompt"] = prompt
            return "ok"

        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        # Patch the contextvar import target so a persona is active.
        from agent_server import profiles

        token = profiles.current_persona.set("PERSONA: You are a finance expert.")
        try:
            agent.decide("hello")
        finally:
            profiles.current_persona.reset(token)
        # No-context path => prompt = "{system}\n\n{user}"; the persona must be
        # prepended to the system block at the very front of the prompt.
        assert captured["prompt"].startswith("PERSONA: You are a finance expert.")

    def test_decide_degenerate_output_replaced(self):
        spiral = (
            "padding " * 30
            + "wait — no — actually, but actually we conclude we surrender "
            "impossible absurd"
        )
        model = MagicMock(return_value=spiral)
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        out = agent.decide("Q?", context="ctx")
        # Spiral detected -> replaced by the clean fallback message.
        assert out != spiral
        assert "couldn't extract a consistent answer" in out

    def test_decide_normalizes_full_width_digits_and_ideographic_full_stop(self):
        model = MagicMock(return_value="Ｑ４ ２０２５ $4。2M")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        out = agent.decide("What was Q4 2025 revenue?", context="Revenue was $4.2M.")
        assert out == "Q4 2025 $4.2M"

    def test_decide_detects_spiral_written_with_full_width_punctuation(self):
        spiral = "padding " * 30 + "wait， wait， wait， actually， actually，"
        assert dma._is_degenerate_output(spiral) is False
        model = MagicMock(return_value=spiral)
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        out = agent.decide("Q?", context="ctx")
        assert "couldn't extract a consistent answer" in out

    def test_decide_truncates_long_context_in_causal_path(self):
        # The causal path tokenizes ``user_content``, which embeds the capped
        # context. A 20k-char context exceeds the 12k cap, so the truncation
        # marker must appear in the user_content handed to the tokenizer.
        agent = _causal_agent(decoded="ok")
        long_ctx = "A" * 20000
        with patch.object(dma, "_model_device", return_value="cpu"), patch.object(
            agent, "_ensure_causal_loaded"
        ):
            agent.decide("Q?", context=long_ctx)
        messages = agent._causal_tokenizer.apply_chat_template.call_args[0][0]
        user_content = messages[1]["content"]
        assert "[retrieved content truncated]" in user_content

    def _vllm_user_content(self, context: str) -> str:
        agent = _causal_agent()
        with patch.object(dma, "_llm_backend", return_value="vllm"), patch.object(
            agent, "_generate_vllm", return_value="ok"
        ) as generate:
            agent.decide("Q?", context=context)
        return generate.call_args.args[0]

    def test_decide_caps_context_at_twelve_thousand_characters_by_default(
        self, monkeypatch
    ):
        monkeypatch.delenv("AGENT_MAX_CONTEXT_CHARS", raising=False)
        user_content = self._vllm_user_content("A" * 20000)
        assert "A" * 12000 + "\n…[retrieved content truncated]" in user_content
        assert "A" * 12001 not in user_content

    def test_decide_caps_context_at_agent_max_context_chars(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "6000")
        user_content = self._vllm_user_content("A" * 20000)
        assert "A" * 6000 + "\n…[retrieved content truncated]" in user_content
        assert "A" * 6001 not in user_content

    def test_context_within_the_cap_is_not_marked_truncated(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "6000")
        user_content = self._vllm_user_content("B" * 6000)
        assert "B" * 6000 in user_content
        assert "truncated" not in user_content

    @pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
    def test_an_unusable_context_cap_falls_back_to_the_default(self, monkeypatch, raw):
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", raw)
        assert dma._max_context_chars() == dma.DEFAULT_MAX_CONTEXT_CHARS == 12000

    def test_decide_reraises_on_model_error(self):
        model = MagicMock(side_effect=RuntimeError("inference blew up"))
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        with pytest.raises(RuntimeError, match="inference blew up"):
            agent.decide("hello")

    def test_decide_records_metrics_on_success(self):
        model = MagicMock(return_value="ok")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        fake_dur = MagicMock()
        fake_total = MagicMock()
        metrics_mod = MagicMock()
        metrics_mod.model_inference_duration = fake_dur
        metrics_mod.model_inference_total = fake_total
        with patch.dict("sys.modules", {"core.metrics": metrics_mod}):
            out = agent.decide("hello")
        assert out == "ok"
        # Success metric incremented with status="success".
        fake_total.labels.assert_called_with(
            model_name=agent.model_name, device="cpu", status="success"
        )
        fake_total.labels.return_value.inc.assert_called_once()

    def test_decide_records_metrics_on_error(self):
        model = MagicMock(side_effect=ValueError("boom"))
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        fake_total = MagicMock()
        metrics_mod = MagicMock()
        metrics_mod.model_inference_duration = MagicMock()
        metrics_mod.model_inference_total = fake_total
        with patch.dict("sys.modules", {"core.metrics": metrics_mod}):
            with pytest.raises(ValueError):
                agent.decide("hello")
        fake_total.labels.assert_called_with(
            model_name=agent.model_name, device="cpu", status="error"
        )

    def test_decide_emits_steps(self):
        # emit_step is imported lazily inside decide() from ai_agents.step_emitter;
        # patch it there and assert the reasoning lifecycle is emitted.
        model = MagicMock(return_value="ok")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        emitted = []

        def fake_emit(step_type, title, detail="", **md):
            emitted.append(step_type)

        with patch("ai_agents.step_emitter.emit_step", fake_emit):
            agent.decide("hello")
        assert "reasoning.start" in emitted
        assert "reasoning.done" in emitted

    def test_decide_emits_error_step_on_failure(self):
        model = MagicMock(side_effect=RuntimeError("kaboom"))
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        emitted = []

        def fake_emit(step_type, title, detail="", **md):
            emitted.append(step_type)

        with patch("ai_agents.step_emitter.emit_step", fake_emit):
            with pytest.raises(RuntimeError):
                agent.decide("hello")
        assert "error" in emitted

    def test_decide_succeeds_when_metrics_unavailable(self):
        # core.metrics import failing must not break inference (success path).
        model = MagicMock(return_value="ok answer")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        with patch.dict("sys.modules", {"core.metrics": None}):
            out = agent.decide("hello")
        assert out == "ok answer"

    def test_decide_reraises_when_metrics_unavailable(self):
        # core.metrics import failing must not swallow the inference error.
        model = MagicMock(side_effect=RuntimeError("boom"))
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        with patch.dict("sys.modules", {"core.metrics": None}):
            with pytest.raises(RuntimeError, match="boom"):
                agent.decide("hello")

    def test_decide_tolerates_persona_import_failure(self):
        # If agent_server.profiles can't be imported, decide() proceeds with no
        # persona rather than raising.
        model = MagicMock(return_value="answer")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        with patch.dict("sys.modules", {"agent_server.profiles": None}):
            out = agent.decide("hello")
        assert out == "answer"

    def test_decide_tolerates_emit_step_import_failure(self):
        # If the step emitter module can't be imported, decide() uses a no-op
        # emitter and still returns the answer.
        model = MagicMock(return_value="answer")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        with patch.dict("sys.modules", {"ai_agents.step_emitter": None}):
            out = agent.decide("hello")
        assert out == "answer"

    def test_decide_truncates_long_query_in_emit(self):
        # query_preview is truncated to 200 chars + ellipsis before emitting.
        model = MagicMock(return_value="answer")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        captured = {}

        def fake_emit(step_type, title, detail="", **md):
            if step_type == "reasoning.start":
                captured.update(md)

        with patch("ai_agents.step_emitter.emit_step", fake_emit):
            agent.decide("Q" * 500)
        assert captured["query"].endswith("…")
        assert len(captured["query"]) == 201


# ===========================================================================
# knowledge_retrieval_agent
# ===========================================================================


class TestSummarizeRetrieved:
    def test_non_dict_returns_empty(self):
        assert _summarize_retrieved(["not", "a", "dict"]) == (0, [], "")
        assert _summarize_retrieved("string") == (0, [], "")

    def test_list_of_dict_chunks_collects_titles(self):
        data = {
            "data": [
                {"title": "Report"},
                {"filename": "policy.pdf"},
                {"source": "src-doc"},
                {"title": "Report"},  # duplicate ignored
            ]
        }
        count, titles, preview = _summarize_retrieved(data)
        assert count == 4
        assert titles == ["Report", "policy.pdf", "src-doc"]
        assert preview == ""

    def test_string_chunks_set_preview(self):
        count, titles, preview = _summarize_retrieved({"data": "hello world"})
        assert count == 1
        assert preview == "hello world"

    def test_blank_string_chunks_zero_count(self):
        count, _, _ = _summarize_retrieved({"data": "   "})
        assert count == 0

    def test_sources_list_merged_into_titles(self):
        data = {"data": [], "sources": [{"title": "S1"}, "S2", {"title": "S1"}]}
        _, titles, _ = _summarize_retrieved(data)
        assert titles == ["S1", "S2"]

    def test_passages_give_the_passage_count_and_the_distinct_titles_in_rank_order(self):
        data = {
            "data": "[Source: B.md]\nb1\n\n[Source: A.md]\na\n\n[Source: B.md]\nb2",
            "passages": [
                {"chunk_id": "b:1", "title": "B.md"},
                {"chunk_id": "a:0", "title": "A.md"},
                {"chunk_id": "b:2", "title": "B.md"},
            ],
        }
        count, titles, _ = _summarize_retrieved(data)
        assert count == 3
        assert titles == ["B.md", "A.md"]

    def test_caps_chunk_titles_at_ten(self):
        data = {"data": [{"title": f"doc{i}"} for i in range(20)]}
        count, titles, _ = _summarize_retrieved(data)
        assert count == 20
        # Only the first 10 chunks are inspected for titles.
        assert len(titles) == 10


class TestKnowledgeRetrievalAgent:
    async def test_fetch_sync_store(self):
        def store(query):
            return {"data": [{"title": "DocA"}], "sources": [{"title": "SrcA"}]}

        agent = KnowledgeRetrievalAgent(store)
        result = await agent.fetch("find docs")
        assert result["data"][0]["title"] == "DocA"

    async def test_fetch_async_store(self):
        async def store(query):
            return {"data": "async context result"}

        agent = KnowledgeRetrievalAgent(store)
        result = await agent.fetch("query")
        assert result == {"data": "async context result"}

    async def test_fetch_non_dict_result(self):
        # _summarize_retrieved handles non-dict gracefully; fetch returns as-is.
        def store(query):
            return "a plain string response"

        agent = KnowledgeRetrievalAgent(store)
        result = await agent.fetch("query")
        assert result == "a plain string response"

    async def test_fetch_empty_results_summary(self):
        def store(query):
            return {"data": []}

        agent = KnowledgeRetrievalAgent(store)
        emitted = []
        with patch(
            "ai_agents.knowledge_retrieval_agent.emit_step",
            lambda *a, **k: emitted.append((a, k)),
        ):
            result = await agent.fetch("query")
        assert result == {"data": []}
        # retrieval.start + retrieval.results both fire.
        step_types = [a[0] for a, _ in emitted]
        assert "retrieval.start" in step_types
        assert "retrieval.results" in step_types

    async def test_fetch_preview_summary_branch(self):
        # The "Got context preview" branch fires when the summary has no chunk
        # count but does have a preview. _summarize_retrieved never produces
        # that pair on its own (a non-empty string sets count=1 AND preview),
        # so patch it to the (0 chunks, preview) shape to drive fetch's branch.
        def store(query):
            return {"data": "irrelevant"}

        agent = KnowledgeRetrievalAgent(store)
        details = []
        with patch(
            "ai_agents.knowledge_retrieval_agent._summarize_retrieved",
            return_value=(0, [], "a short preview of context"),
        ), patch(
            "ai_agents.knowledge_retrieval_agent.emit_step",
            lambda step_type, title, detail="", **k: details.append(detail),
        ):
            await agent.fetch("query")
        assert any("context preview" in d for d in details)

    async def test_fetch_long_query_truncated_in_step(self):
        def store(query):
            return {"data": [{"title": "D"}]}

        agent = KnowledgeRetrievalAgent(store)
        captured = {}
        with patch(
            "ai_agents.knowledge_retrieval_agent.emit_step",
            lambda step_type, title, detail="", **k: captured.update(k),
        ):
            await agent.fetch("Q" * 500)
        # query is truncated to 200 chars + ellipsis before emitting.
        assert captured["query"].endswith("…")
        assert len(captured["query"]) == 201

    async def test_fetch_raises_and_emits_error(self):
        def store(query):
            raise RuntimeError("store offline")

        agent = KnowledgeRetrievalAgent(store)
        emitted = []
        with patch(
            "ai_agents.knowledge_retrieval_agent.emit_step",
            lambda step_type, *a, **k: emitted.append(step_type),
        ):
            with pytest.raises(RuntimeError, match="store offline"):
                await agent.fetch("query")
        assert "error" in emitted

    async def test_fetch_async_store_raises(self):
        async def store(query):
            raise ValueError("async failure")

        agent = KnowledgeRetrievalAgent(store)
        with pytest.raises(ValueError, match="async failure"):
            await agent.fetch("query")


# ===========================================================================
# rag_pipeline
# ===========================================================================


def _pipeline(use_react: bool = False, tool_registry=None):
    retrieval = MagicMock()
    decision = MagicMock()
    return (
        RAGPipeline(
            retrieval, decision, tool_registry=tool_registry, use_react=use_react
        ),
        retrieval,
        decision,
    )


class TestRAGPipelineConstruction:
    def test_builds_default_registry(self):
        pipe, _, _ = _pipeline()
        # Default registry registers the standard tool suite + aliases.
        assert pipe.tool_registry.has("calc")
        assert pipe.tool_registry.has("summarize")
        assert pipe.tool_registry.has("extract_data")
        assert pipe.tool_registry.has("payment")

    def test_accepts_custom_registry(self):
        reg = MagicMock()
        pipe, _, _ = _pipeline(tool_registry=reg)
        assert pipe.tool_registry is reg

    def test_use_react_flag_stored(self):
        pipe, _, _ = _pipeline(use_react=True)
        assert pipe.use_react is True


class TestReactAgentProperty:
    def test_lazy_creation_and_caching(self):
        reg = MagicMock()
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        sentinel = object()
        with patch(
            "ai_agents.react_agent.ReactAgent", return_value=sentinel
        ) as ReactAgent:
            first = pipe.react_agent
            second = pipe.react_agent
        assert first is sentinel
        assert second is sentinel
        # Created exactly once (cached), wired with the pipeline's collaborators.
        ReactAgent.assert_called_once_with(
            decision_agent=decision,
            retrieval_agent=retrieval,
            tool_registry=reg,
        )


class TestGenerateResponse:
    async def test_returns_decision_output(self):
        pipe, retrieval, decision = _pipeline()
        retrieval.fetch = AsyncMock(return_value={"data": "context text"})
        decision.decide.return_value = "final insight"
        out = await pipe.generate_response("what is x?")
        assert out == "final insight"
        # decide is invoked with the query and the retrieved context.
        _, kwargs = decision.decide.call_args
        assert kwargs["query"] == "what is x?"
        assert kwargs["context"] == "context text"

    async def test_missing_data_key_defaults_to_empty_context(self):
        pipe, retrieval, decision = _pipeline()
        retrieval.fetch = AsyncMock(return_value={})
        decision.decide.return_value = "answer"
        await pipe.generate_response("q")
        _, kwargs = decision.decide.call_args
        assert kwargs["context"] == ""

    async def test_timeout_returns_friendly_message(self):
        pipe, retrieval, decision = _pipeline()
        retrieval.fetch = AsyncMock(return_value={"data": "ctx"})

        async def fake_wait_for(coro, timeout):
            # Close the wrapped coroutine to avoid 'never awaited' warnings.
            if asyncio.iscoroutine(coro):
                coro.close()
            raise TimeoutError()

        with patch("asyncio.wait_for", fake_wait_for):
            out = await pipe.generate_response("a question")
        assert "took too long" in out
        assert "REACT_TIMEOUT_SECONDS" in out


class TestGenerateResponseReact:
    async def test_delegates_to_react_agent(self):
        pipe, _, _ = _pipeline()
        fake_react = MagicMock()
        fake_react.run = AsyncMock(
            return_value={"answer": "react answer", "sources": [], "history": []}
        )
        with patch.object(
            type(pipe), "react_agent", new_callable=lambda: property(lambda self: fake_react)
        ):
            result = await pipe.generate_response_react("q")
        assert result["answer"] == "react answer"
        fake_react.run.assert_awaited_once_with("q")


class TestProcessTask:
    async def test_tool_operation_dispatches_to_registry(self):
        reg = MagicMock()
        reg.has.return_value = True
        reg.run.return_value = "tool result text"
        pipe, _, _ = _pipeline(tool_registry=reg)
        result = await pipe.process_task(
            {"task_id": "T1", "operation": "Calc", "query": "ignored"}
        )
        assert result == {
            "task_id": "T1",
            "response": "tool result text",
            "status": "completed",
        }
        # Operation is lowercased/stripped before the registry lookup.
        reg.has.assert_called_with("calc")
        reg.run.assert_called_once()

    async def test_single_shot_mode(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={"data": "ctx"})
        decision.decide.return_value = "single shot answer"
        result = await pipe.process_task({"task_id": "T2", "query": "hello"})
        assert result == {
            "task_id": "T2",
            "response": "single shot answer",
            "status": "completed",
        }

    async def test_react_mode_via_task_flag(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, _, _ = _pipeline(tool_registry=reg)
        pipe.generate_response_react = AsyncMock(
            return_value={
                "answer": "react answer",
                "sources": ["doc1"],
                "history": [{"step": 1}],
            }
        )
        result = await pipe.process_task(
            {"task_id": "T3", "query": "complex q", "mode": "ReAct"}
        )
        assert result["response"] == "react answer"
        assert result["sources"] == ["doc1"]
        assert result["reasoning_history"] == [{"step": 1}]
        assert result["status"] == "completed"

    async def test_react_mode_via_pipeline_default(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, _, _ = _pipeline(use_react=True, tool_registry=reg)
        pipe.generate_response_react = AsyncMock(
            return_value={"answer": "A", "sources": [], "history": None}
        )
        result = await pipe.process_task({"task_id": "T4", "query": "q"})
        assert result["response"] == "A"
        assert result["status"] == "completed"

    async def test_no_operation_falls_through_to_single_shot(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={"data": "ctx"})
        decision.decide.return_value = "answer"
        # Empty operation string -> registry lookup is skipped entirely.
        result = await pipe.process_task(
            {"task_id": "T5", "operation": "", "query": "q"}
        )
        assert result["response"] == "answer"
        reg.run.assert_not_called()

    async def test_attached_files_come_first_and_their_own_passages_are_not_retrieved_again(
        self,
    ):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={
            "data": "ignored",
            "passages": [
                {"doc_id": "doc-q4", "title": "q4.md", "text": "Q4 REVENUE 4.2M"},
                {"doc_id": "doc-budget", "title": "budget.md", "text": "2026 BUDGET 5M"},
            ],
        })
        decision.decide.return_value = "4.2M"
        block = "[file: q4.md (source=knowledge_store)]\nQ4 REVENUE 4.2M"
        result = await pipe.process_task(
            {
                "task_id": "T6",
                "query": f"{block}\n\nwhat was the revenue?",
                "demand": "what was the revenue?",
                "attached_context": block,
                "files": [{"filename": "q4.md", "source": "knowledge_store", "doc_id": "doc-q4"}],
            }
        )
        assert result["response"] == "4.2M"
        retrieval.fetch.assert_awaited_once_with("what was the revenue?")
        _, kwargs = decision.decide.call_args
        assert kwargs["query"] == "what was the revenue?"
        assert kwargs["context"] == (
            f"{block}\n--- Other Knowledge Store Passages ---\n"
            "[Source: budget.md]\n2026 BUDGET 5M"
        )
        assert kwargs["context"].count("Q4 REVENUE 4.2M") == 1

    async def test_passages_of_an_attached_file_without_doc_id_are_dropped_by_title(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={
            "passages": [{"doc_id": "doc-q4", "title": "q4.md", "text": "Q4 REVENUE 4.2M"}],
        })
        decision.decide.return_value = "4.2M"
        block = "[file: q4.md (source=inline)]\nQ4 REVENUE 4.2M"
        await pipe.process_task(
            {
                "task_id": "T6b",
                "query": block,
                "demand": "what was the revenue?",
                "attached_context": block,
                "files": [{"filename": "q4.md", "source": "inline"}],
            }
        )
        _, kwargs = decision.decide.call_args
        assert kwargs["context"] == block

    async def test_a_failing_retrieval_still_answers_from_the_attached_files(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(side_effect=RuntimeError("knowledge store down"))
        decision.decide.return_value = "4.2M"
        block = "[file: q4.md (source=knowledge_store)]\nQ4 REVENUE 4.2M"
        result = await pipe.process_task(
            {
                "task_id": "T6d",
                "query": block,
                "demand": "what was the revenue?",
                "attached_context": block,
                "files": [{"filename": "q4.md", "source": "knowledge_store", "doc_id": "doc-q4"}],
            }
        )
        assert result["response"] == "4.2M"
        _, kwargs = decision.decide.call_args
        assert kwargs["context"] == block

    async def test_attachments_that_fill_the_context_cap_are_not_joined_by_retrieval(
        self, monkeypatch
    ):
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "1500")
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={"data": "x", "passages": []})
        decision.decide.return_value = "answer"
        block = "[file: big.md (source=knowledge_store)]\n" + "y" * 1000
        await pipe.process_task(
            {
                "task_id": "T6c",
                "query": block,
                "demand": "summarise",
                "attached_context": block,
                "files": [{"filename": "big.md", "source": "knowledge_store"}],
            }
        )
        retrieval.fetch.assert_not_called()
        _, kwargs = decision.decide.call_args
        assert kwargs["context"] == block

    async def test_attached_file_text_appears_once_in_the_prompt(self):
        body = "Q4 REVENUE WAS 4.2M"
        block = (
            "--- Attached Files ---\n[file: q4.md (source=knowledge_store)]\n"
            f"{body}\n--- End Attached Files ---\n"
        )
        prompts = []

        def served(_self, user_content, system_content):
            prompts.append(f"{system_content}\n\n{user_content}")
            return "4.2M"

        retrieval = MagicMock()
        retrieval.fetch = AsyncMock(return_value={"data": body})
        pipe = RAGPipeline(retrieval, _causal_agent())
        with patch.dict("os.environ", {"LLM_BACKEND": "vllm"}), patch.object(
            DecisionMakingAgent, "_generate_vllm", served
        ):
            result = await pipe.process_task(
                {
                    "task_id": "T7",
                    "query": f"{block}\nwhat was the revenue?",
                    "demand": "what was the revenue?",
                    "attached_context": block,
                }
            )
        assert result["response"] == "4.2M"
        assert prompts[0].count(body) == 1
        assert "what was the revenue?" in prompts[0]

    async def test_without_attached_context_retrieval_runs_on_the_query(self):
        reg = MagicMock()
        reg.has.return_value = False
        pipe, retrieval, decision = _pipeline(tool_registry=reg)
        retrieval.fetch = AsyncMock(return_value={"data": "ctx"})
        decision.decide.return_value = "answer"
        await pipe.process_task(
            {"task_id": "T8", "query": "full q", "demand": "q", "attached_context": None}
        )
        retrieval.fetch.assert_awaited_once_with("full q")
        _, kwargs = decision.decide.call_args
        assert kwargs["query"] == "full q"
