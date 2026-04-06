"""
decision_making_agent.py
-------------------------
This module defines the DecisionMakingAgent class, which processes retrieved data and generates insights using an AI model.
It uses a transformer-based model (e.g., T5) via Hugging Face's pipeline or a placeholder function if no model is provided.
Supports GPU acceleration with automatic CPU fallback.
"""

from typing import Dict, Any, Optional
import re
import logging

logger = logging.getLogger(__name__)

# Uncomment the following lines if you have transformers installed.
# pip install transformers
try:
    from transformers import pipeline
    _TRANSFORMERS_AVAILABLE = True
except Exception:
    pipeline = None  # type: ignore
    _TRANSFORMERS_AVAILABLE = False

# Try to import torch for GPU detection
try:
    import torch
    _TORCH_AVAILABLE = True
except Exception:
    torch = None  # type: ignore
    _TORCH_AVAILABLE = False


def detect_device(device_preference: str = "auto") -> str:
    """
    Detect and return the appropriate device for model execution.
    
    Args:
        device_preference: Device preference ("auto", "cpu", "cuda", "cuda:0", etc.)
    
    Returns:
        Device string (e.g., "cpu", "cuda", "cuda:0")
    """
    if device_preference.lower() == "auto":
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            device = "cuda"
            logger.info(f"GPU detected: {torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})")
            return device
        else:
            device = "cpu"
            if not _TORCH_AVAILABLE:
                logger.info("PyTorch not available, using CPU")
            else:
                logger.info("No GPU available, using CPU")
            return device
    else:
        # Use specified device
        if device_preference.startswith("cuda") and _TORCH_AVAILABLE:
            if not torch.cuda.is_available():
                logger.warning(f"CUDA requested but not available, falling back to CPU")
                return "cpu"
        return device_preference


class DecisionMakingAgent:
    """
    Processes retrieved data and generates insights using an AI model.
    Supports GPU acceleration with automatic CPU fallback.
    """

    def __init__(
        self, 
        decision_model=None, 
        model_name: str = "t5-small",
        device: Optional[str] = None
    ):
        """
        Args:
            decision_model: Optional pre-configured AI model. If None, a transformer-based model is used.
            model_name: Name of the transformer model (default "t5-small").
            device: Device to use ("auto", "cpu", "cuda", "cuda:0", etc.). Defaults to "auto" which auto-detects.
        """
        self.model_name = model_name
        self.device = detect_device(device) if device else detect_device("auto")
        
        if decision_model is not None:
            self.decision_model = decision_model
            logger.info(f"DecisionMakingAgent initialized with provided model on device: {self.device}")
        else:
            # Use the transformer-based model from Hugging Face if available; otherwise fallback.
            if _TRANSFORMERS_AVAILABLE:
                try:
                    self.decision_model = pipeline(
                        "text2text-generation", 
                        model=model_name,
                        device=0 if self.device.startswith("cuda") else -1  # 0 for GPU, -1 for CPU
                    )
                    logger.info(
                        f"DecisionMakingAgent initialized with model '{model_name}' "
                        f"on device: {self.device}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to initialize model on {self.device}, falling back to CPU: {e}"
                    )
                    try:
                        self.device = "cpu"
                        self.decision_model = pipeline(
                            "text2text-generation", 
                            model=model_name,
                            device=-1  # CPU
                        )
                        logger.info(f"Model initialized on CPU fallback")
                    except Exception as e2:
                        logger.error(f"Failed to initialize model even on CPU: {e2}")
                        self.decision_model = self.mock_decision_model
                        logger.warning("Using mock decision model")
            else:
                self.decision_model = self.mock_decision_model
                logger.warning("Transformers not available, using mock decision model")

    def mock_decision_model(self, input_text: str):
        """
        Lightweight heuristic QA for local/dev without transformers.
        Extracts answer from the provided Context and Question in the prompt.
        """
        # Try to parse our QA-style prompt
        context_match = re.search(r"Context:\n([\s\S]*?)\n\nQuestion:", input_text)
        question_match = re.search(r"Question:\s*(.*)\nAnswer:\s*$", input_text)

        context_text = context_match.group(1).strip() if context_match else ""
        question_text = question_match.group(1).strip() if question_match else ""

        answer = None

        # Simple, targeted heuristics for common patterns in the mock context
        if context_text:
            # Key regions extraction
            m = re.search(r"Key regions such as\s+([^\.;]+)", context_text, flags=re.IGNORECASE)
            if m and re.search(r"region|area|market", question_text, flags=re.IGNORECASE):
                answer = m.group(1).strip()

            # Growth percentage
            if answer is None and re.search(r"growth|increase|revenue", question_text, flags=re.IGNORECASE):
                m2 = re.search(r"revenue growth of\s+(\d+%)[^\.]*", context_text, flags=re.IGNORECASE)
                if m2:
                    answer = f"Revenue growth was {m2.group(1)} in Q1 2025."

            # Leading region increase
            if answer is None and re.search(r"north america|which region|leading", question_text, flags=re.IGNORECASE):
                m3 = re.search(r"North America leading a\s+(\d+%) increase", context_text, flags=re.IGNORECASE)
                if m3:
                    answer = f"North America led with a {m3.group(1)} increase in sales volume."

            # New customers increase
            if answer is None and re.search(r"new customer|acquisition", question_text, flags=re.IGNORECASE):
                m4 = re.search(r"contributed to a\s+(\d+%) rise in new customer acquisition", context_text, flags=re.IGNORECASE)
                if m4:
                    answer = f"New customer acquisition rose by {m4.group(1)}."

        if not answer:
            # Fallback: first sentence that most overlaps with the question keywords
            sentences = re.split(r"(?<=[.!?])\s+", context_text)
            keywords = [w.lower() for w in re.findall(r"\w+", question_text)]
            best = ""
            best_score = 0
            for s in sentences:
                score = sum(1 for k in keywords if k and k in s.lower())
                if score > best_score:
                    best, best_score = s.strip(), score
            answer = best or "I don't have that information yet."

        return [{"generated_text": answer}]

    async def decide(self, query: str, context: str) -> str:
        """
        Answer the user's query using the provided context.

        Args:
            query: The user's question.
            context: Retrieved context text.

        Returns:
            A concise answer string.
        """
        import time
        
        # Import metrics if available
        try:
            from core.metrics import (
                model_inference_total,
                model_inference_duration,
            )
            _METRICS_AVAILABLE = True
        except ImportError:
            _METRICS_AVAILABLE = False
        
        prompt = (
            "You are a helpful assistant. Answer the user's question as directly and concisely as possible "
            "in 1-3 sentences using ONLY the provided context. If the answer is not present in the context, "
            "say: 'I don't have that information yet.'\n\n"
            f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
        )
        
        logger.debug(f"Processing decision with model '{self.model_name}' on device '{self.device}'")
        start_time = time.time()
        
        try:
            result = self.decision_model(prompt)
            inference_duration = time.time() - start_time
            
            # Record metrics
            if _METRICS_AVAILABLE:
                model_inference_duration.labels(
                    model_name=self.model_name,
                    device=self.device
                ).observe(inference_duration)
                model_inference_total.labels(
                    model_name=self.model_name,
                    device=self.device,
                    status="success"
                ).inc()
            
            logger.debug(
                f"Model inference completed: duration={inference_duration:.3f}s, "
                f"device={self.device}, model={self.model_name}"
            )
            
            if isinstance(result, list) and result and isinstance(result[0], dict) and 'generated_text' in result[0]:
                return result[0]['generated_text'].strip()
            return str(result).strip()
        except Exception as e:
            inference_duration = time.time() - start_time
            if _METRICS_AVAILABLE:
                model_inference_duration.labels(
                    model_name=self.model_name,
                    device=self.device
                ).observe(inference_duration)
                model_inference_total.labels(
                    model_name=self.model_name,
                    device=self.device,
                    status="error"
                ).inc()
            logger.error(
                f"Model inference failed: error={str(e)}, duration={inference_duration:.3f}s, "
                f"device={self.device}, model={self.model_name}",
                exc_info=True
            )
            raise
