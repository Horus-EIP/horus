import json
import os
from pathlib import Path

import torch
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          BitsAndBytesConfig)

from core.config import settings
from core.logger import get_logger

logger = get_logger("llm_setup")

os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:64"
)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
torch.set_num_threads(1)
torch.backends.cuda.matmul.allow_tf32 = True

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_DIR = BASE_DIR / "models/Qwen3_instruct_4B"
OFFLOAD_DIR = BASE_DIR / "offload"
OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "model.safetensors.index.json",
]


def is_model_dir_exists():
    if not os.path.exists(MODEL_DIR):
        return False
    missing = [f for f in REQUIRED_FILES if not (MODEL_DIR / f).exists()]
    if missing:
        logger.warning(f"Model files missing in folder {MODEL_DIR}: {missing}")
        return False
    return True


GPU_BUDGET = "3.2GiB"
CPU_BUDGET = "2GiB"  # Adjusted for tight system memory


def _bnb4bit():
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=(
            torch.bfloat16
            if (torch.cuda.is_available() and torch.cuda.is_bf16_supported())
            else torch.float16
        ),
    )


def get_llm():

    if not torch.cuda.is_available():
        logger.warning("No NVIDIA GPU detected. LLM will not be loaded.")
        return None, None

    if is_model_dir_exists():
        model_path = MODEL_DIR
    else:
        model_path = MODEL_ID

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, use_fast=True, trust_remote_code=True
    )

    if torch.cuda.is_available():
        max_memory = {0: GPU_BUDGET, "cpu": CPU_BUDGET}
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=_bnb4bit(),
            device_map="auto",
            max_memory=max_memory,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
            offload_folder=str(OFFLOAD_DIR),
            trust_remote_code=True,
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            device_map={"": "cpu"},
            dtype=torch.float32,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )

    model.eval()
    return tokenizer, model


tokenizer = None
model = None

# Prevent loading LLM in test mode or if disabled
if settings.llm_autoinit == 1 and os.environ.get("TEST_MODE") != "1":
    tokenizer, model = get_llm()


def ask_llm(messages: list, max_new_tokens: int = 256):
    logger.info("Entering ask_llm, checking model...")
    if tokenizer is None or model is None:
        logger.warning("LLM not initialized. Returning mock response.")
        return json.dumps(
            {
                "next_action": "run_agents",
                "actions": [
                    {"agent": "test_agent_math_fixed", "input": "Calculate sqrt(16)"}
                ],
                "final_answer": "",
            }
        )

    logger.info("Tokenizing prompt...")
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    enc = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=1024,
        add_special_tokens=True,
    )
    input_ids = enc["input_ids"].to(model.device)
    attn_mask = enc.get("attention_mask")
    if attn_mask is not None:
        attn_mask = attn_mask.to(model.device)

    logger.info(f"Starting generation with max_new_tokens={max_new_tokens}...")
    import time

    start_time = time.time()
    torch.cuda.empty_cache()  # Clear cache before generation
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            attention_mask=attn_mask,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            return_dict_in_generate=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    logger.info(f"Generation finished in {time.time() - start_time:.2f}s")

    seq = out.sequences[0]
    gen_only = seq[input_ids.size(1) :]
    text = tokenizer.decode(
        gen_only, skip_special_tokens=True, clean_up_tokenization_spaces=False
    ).strip()

    return text
