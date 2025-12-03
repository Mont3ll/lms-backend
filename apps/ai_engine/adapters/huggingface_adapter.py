import logging

import requests

from ..models import ModelConfig
from .base import AIAdapterError, BaseAdapter

logger = logging.getLogger(__name__)


class HuggingfaceAdapter(BaseAdapter):
    """Adapter for interacting with Hugging Face Inference API or local models."""

    def _get_api_url(self):
        base_url = self._get_base_url()
        if base_url:  # For self-hosted Inference Endpoint
            return base_url
        else:  # Use public Inference API
            model_id = self.config.model_id
            return f"https://api-inference.huggingface.co/models/{model_id}"

    def generate(self, prompt: str, params: dict) -> tuple[str, dict]:
        api_url = self._get_api_url()
        api_key = self._get_api_key()  # HF Token
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        logger.info(f"Sending request to Hugging Face endpoint: {api_url}")

        # Prepare payload based on HF task (text-generation typically)
        payload = {
            "inputs": prompt,
            "parameters": {
                "return_full_text": False,  # Usually want only generated part
                "max_new_tokens": params.get(
                    "max_tokens", params.get("max_new_tokens", 512)
                ),
                "temperature": params.get("temperature", 0.7),
                # Add other HF specific params: top_k, top_p, do_sample, repetition_penalty
                "top_k": params.get("top_k"),
                "top_p": params.get("top_p"),
                "do_sample": params.get(
                    "do_sample", True if params.get("temperature", 0.7) > 0 else False
                ),
            },
            "options": {
                "use_cache": False,  # Don't reuse cache for dynamic prompts
                "wait_for_model": True,  # Wait if model is loading
            },
        }
        # Remove None values from parameters
        payload["parameters"] = {
            k: v for k, v in payload["parameters"].items() if v is not None
        }

        try:
            response = requests.post(
                api_url, headers=headers, json=payload, timeout=120
            )  # Add timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            result = response.json()
            # HF response format can vary, typically a list with a dict inside
            if isinstance(result, list) and len(result) > 0:
                generated_text = result[0].get("generated_text", "").strip()
            elif isinstance(result, dict):  # Sometimes it's just a dict
                generated_text = result.get("generated_text", "").strip()
            else:
                generated_text = str(result)  # Fallback

            # Metadata from HF is limited via basic API
            metadata = {
                "model_used": self.config.model_id,
                # Token usage not typically returned via standard inference API
            }
            logger.info(f"Received response from Hugging Face endpoint {api_url}")
            return generated_text, metadata

        except requests.exceptions.RequestException as e:
            logger.error(f"Hugging Face API request error: {e}", exc_info=True)
            # Check response content for more details if available
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_detail = f"{e.response.status_code} - {e.response.text}"
                except Exception:
                    pass
            raise AIAdapterError(
                f"Hugging Face API request error: {error_detail}"
            ) from e
        except Exception as e:
            logger.error(
                f"Unexpected error during Hugging Face call: {e}", exc_info=True
            )
            raise AIAdapterError(f"Unexpected error: {e}") from e
