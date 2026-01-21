"""
LLM Setup Module - Supports multiple backends:
1. Local model with NVIDIA GPU (fast, quantized)
2. Local model with CPU (slower, for macOS/no GPU)
3. OpenAI API (cloud-based)
4. Mock responses (for testing)

Configure via environment variables:
- LLM_BACKEND: "local" | "openai" | "mock" (default: "mock")
- LLM_AUTOINIT: 1 to enable local model loading
- LLM_FORCE_CPU: 1 to force CPU mode even if GPU available
- OPENAI_API_KEY: Your OpenAI API key (for openai backend)
- OPENAI_MODEL: Model to use (default: gpt-4o-mini)
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple

from core.logger import get_logger
from core.config import settings

logger = get_logger("llm_setup")

# LLM Backend configuration
LLM_BACKEND = os.getenv("LLM_BACKEND", "mock")  # "local", "openai", or "mock"
LLM_FORCE_CPU = os.getenv("LLM_FORCE_CPU", "0") == "1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Model configuration
# GPU: Larger model with 4-bit quantization
GPU_MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"  # Good balance of quality/speed
GPU_MODEL_DIR = Path("./models/Qwen2.5-1.5B-Instruct")

# CPU: Very small model for limited memory environments (Docker)
CPU_MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"  # ~1GB, works in 4GB RAM
CPU_MODEL_DIR = Path("./models/Qwen2.5-0.5B-Instruct")

OFFLOAD_DIR = Path("./offload")
OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer.json",
]

# Module-level variables
tokenizer = None
model = None
openai_client = None
device_type = "cpu"  # Track which device we're using


def is_model_dir_exists(model_dir: Path) -> bool:
    """Check if model directory exists with required files."""
    if not os.path.exists(model_dir):
        return False
    missing = [f for f in REQUIRED_FILES if not (model_dir / f).exists()]
    if missing:
        logger.warning(f"Model files missing in folder {model_dir}: {missing}")
        return False
    return True


def detect_device() -> Tuple[str, bool]:
    """
    Detect the best available device.
    Returns: (device_type, has_cuda)
    """
    try:
        import torch
        
        if LLM_FORCE_CPU:
            logger.info("CPU mode forced via LLM_FORCE_CPU=1")
            return "cpu", False
        
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"NVIDIA GPU detected: {gpu_name} ({gpu_memory:.1f}GB)")
            return "cuda", True
        
        # Check for Apple Silicon MPS
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            logger.info("Apple Silicon MPS detected")
            return "mps", False
        
        logger.info("No GPU detected, using CPU")
        return "cpu", False
        
    except ImportError:
        logger.warning("PyTorch not available")
        return "cpu", False


def init_openai():
    """Initialize OpenAI client."""
    global openai_client
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set. OpenAI backend unavailable.")
        return None
    
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info(f"OpenAI client initialized with model: {OPENAI_MODEL}")
        return openai_client
    except ImportError:
        logger.error("OpenAI package not installed. Run: pip install openai")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None


def init_local_model():
    """
    Initialize local model with automatic device detection.
    - NVIDIA GPU: Uses 4-bit quantization for efficiency
    - Apple MPS: Uses float16 for M1/M2/M3 chips
    - CPU: Uses float32 with smaller model
    """
    global tokenizer, model, device_type
    
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        logger.error(f"Required packages not installed: {e}")
        return None, None

    # Set threading for CPU efficiency
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    
    device_type, has_cuda = detect_device()
    
    # Select model based on device
    if has_cuda:
        model_id = GPU_MODEL_ID
        model_dir = GPU_MODEL_DIR
        logger.info(f"Using GPU model: {model_id}")
    else:
        model_id = CPU_MODEL_ID
        model_dir = CPU_MODEL_DIR
        logger.info(f"Using CPU/MPS model: {model_id}")
    
    # Determine model path
    if is_model_dir_exists(model_dir):
        model_path = model_dir
        logger.info(f"Loading from local cache: {model_dir}")
    else:
        model_path = model_id
        logger.info(f"Downloading from HuggingFace: {model_id}")
    
    try:
        # Load tokenizer
        logger.info("Loading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_path, 
            use_fast=True, 
            trust_remote_code=True
        )
        
        # Load model based on device
        logger.info(f"Loading model on {device_type}...")
        
        if has_cuda:
            # NVIDIA GPU with 4-bit quantization
            try:
                from transformers import BitsAndBytesConfig
                
                os.environ.setdefault(
                    "PYTORCH_CUDA_ALLOC_CONF", 
                    "expandable_segments:True,max_split_size_mb:64"
                )
                torch.backends.cuda.matmul.allow_tf32 = True
                
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
                )
                
                model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    quantization_config=quantization_config,
                    device_map="auto",
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                )
                logger.info("Model loaded with 4-bit quantization on GPU")
                
            except ImportError:
                logger.warning("bitsandbytes not available, loading without quantization")
                model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    torch_dtype=torch.float16,
                    device_map="auto",
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                )
                
        elif device_type == "mps":
            # Apple Silicon MPS
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
                trust_remote_code=True,
            )
            model = model.to("mps")
            logger.info("Model loaded on Apple Silicon MPS")
            
        else:
            # CPU fallback
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
                trust_remote_code=True,
            )
            logger.info("Model loaded on CPU (this will be slower)")
        
        model.eval()
        logger.info(f"✅ Local model ready on {device_type}")
        return tokenizer, model
        
    except Exception as e:
        logger.error(f"Failed to load local model: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, None


def ask_llm_openai(messages: list, max_new_tokens: int = 256) -> str:
    """Query OpenAI API."""
    if not openai_client:
        raise RuntimeError("OpenAI client not initialized")
    
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise


def ask_llm_local(messages: list, max_new_tokens: int = 256) -> str:
    """Query local model."""
    import torch
    
    if tokenizer is None or model is None:
        raise RuntimeError("Local model not initialized")
    
    # Build prompt using chat template
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    # Tokenize
    enc = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=2048,
        add_special_tokens=True,
    )
    
    # Move to correct device
    if hasattr(model, 'device'):
        device = model.device
    elif device_type == "mps":
        device = "mps"
    else:
        device = "cpu"
    
    input_ids = enc["input_ids"].to(device)
    attn_mask = enc.get("attention_mask")
    if attn_mask is not None:
        attn_mask = attn_mask.to(device)

    # Generate
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            attention_mask=attn_mask,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    # Decode only new tokens
    seq = out[0]
    gen_only = seq[input_ids.size(1):]
    text = tokenizer.decode(
        gen_only, 
        skip_special_tokens=True, 
        clean_up_tokenization_spaces=False
    ).strip()

    return text


def ask_llm_mock(messages: list, available_agents: list = None) -> str:
    """Return mock response for testing."""
    if available_agents and len(available_agents) > 0:
        first_agent = available_agents[0].get("name", "HorusAgent")
        user_input = messages[-1].get("content", "Hello") if messages else "Hello"
        return json.dumps({
            "next_action": "run_agents",
            "actions": [{"agent": first_agent, "input": user_input}],
            "final_answer": "",
        })
    else:
        return json.dumps({
            "next_action": "respond_to_user",
            "actions": [],
            "final_answer": "I'm running in demo mode. Set LLM_BACKEND=local to enable the AI.",
        })


def ask_llm(messages: list, max_new_tokens: int = 256, available_agents: list = None) -> str:
    """
    Main entry point for LLM queries.
    Routes to appropriate backend based on LLM_BACKEND setting.
    """
    backend = LLM_BACKEND.lower()
    
    # OpenAI backend
    if backend == "openai" and openai_client:
        try:
            return ask_llm_openai(messages, max_new_tokens)
        except Exception as e:
            logger.error(f"OpenAI failed, falling back to mock: {e}")
            return ask_llm_mock(messages, available_agents)
    
    # Local model backend
    if backend == "local" and tokenizer is not None and model is not None:
        try:
            return ask_llm_local(messages, max_new_tokens)
        except Exception as e:
            logger.error(f"Local model failed, falling back to mock: {e}")
            return ask_llm_mock(messages, available_agents)
    
    # Mock backend (default)
    if backend not in ["mock", "openai", "local"]:
        logger.warning(f"Unknown LLM_BACKEND '{backend}', using mock")
    return ask_llm_mock(messages, available_agents)


# Initialize on module load
logger.info(f"LLM Configuration: BACKEND={LLM_BACKEND}, FORCE_CPU={LLM_FORCE_CPU}")

if LLM_BACKEND.lower() == "openai":
    init_openai()
elif LLM_BACKEND.lower() == "local" or settings.llm_autoinit == 1:
    tokenizer, model = init_local_model()
else:
    logger.info("LLM running in mock mode (set LLM_BACKEND=local to enable)")
