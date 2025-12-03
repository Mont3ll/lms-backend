import logging

import anthropic

from ..models import ModelConfig
from .base import AIAdapterError, BaseAdapter

logger = logging.getLogger(__name__)


class AnthropicAdapter(BaseAdapter):
    """Adapter for interacting with Anthropic models (Claude)."""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._setup_client()

    def _setup_client(self):
        """Initialize the Anthropic client."""
        api_key = self._get_api_key()
        if not api_key:
            raise AIAdapterError("Anthropic API key is missing in configuration.")
        
        base_url = self._get_base_url()
        if base_url:
            self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
            logger.info(f"Using custom Anthropic API base URL: {base_url}")
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str, params: dict) -> tuple[str, dict]:
        """
        Generate text using Anthropic's Messages API.
        
        :param prompt: The input prompt text.
        :param params: Dictionary of parameters (temperature, max_tokens, etc.)
        :return: Tuple of (generated_text, metadata)
        """
        model_id = self.config.model_id
        logger.info(f"Sending request to Anthropic model: {model_id}")

        # Prepare parameters for Anthropic API
        # Common params: max_tokens (required), temperature, top_p, top_k
        max_tokens = params.get("max_tokens", 1024)
        temperature = params.get("temperature", 0.7)
        
        # Build API parameters
        api_params = {
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # Add optional parameters if provided
        if "top_p" in params:
            api_params["top_p"] = params["top_p"]
        if "top_k" in params:
            api_params["top_k"] = params["top_k"]
        if "stop_sequences" in params:
            api_params["stop_sequences"] = params["stop_sequences"]
        
        # Handle system prompt if provided
        system_prompt = params.get("system", params.get("system_prompt"))
        if system_prompt:
            api_params["system"] = system_prompt

        try:
            # Use the Messages API (modern Anthropic API)
            message = self.client.messages.create(
                messages=[{"role": "user", "content": prompt}],
                **api_params
            )
            
            # Extract the generated text from the response
            generated_text = ""
            for content_block in message.content:
                if content_block.type == "text":
                    generated_text += content_block.text
            
            generated_text = generated_text.strip()
            
            # Build metadata from response
            metadata = {
                "model_used": message.model,
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
                "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
                "stop_reason": message.stop_reason,
            }
            
            logger.info(
                f"Received response from Anthropic model {model_id}. "
                f"Stop reason: {message.stop_reason}, "
                f"Tokens: {metadata['total_tokens']}"
            )
            return generated_text, metadata

        except anthropic.AuthenticationError as e:
            logger.error(f"Anthropic authentication error: {e}", exc_info=True)
            raise AIAdapterError(f"Anthropic authentication failed: {e}") from e
        except anthropic.RateLimitError as e:
            logger.error(f"Anthropic rate limit error: {e}", exc_info=True)
            raise AIAdapterError(f"Anthropic rate limit exceeded: {e}") from e
        except anthropic.BadRequestError as e:
            logger.error(f"Anthropic bad request error: {e}", exc_info=True)
            raise AIAdapterError(f"Anthropic bad request: {e}") from e
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}", exc_info=True)
            raise AIAdapterError(f"Anthropic API error: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during Anthropic call: {e}", exc_info=True)
            raise AIAdapterError(f"Unexpected error: {e}") from e
