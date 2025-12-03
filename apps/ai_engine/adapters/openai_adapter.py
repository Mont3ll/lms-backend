import logging

import openai  # Use the official library

from ..models import ModelConfig
from .base import AIAdapterError, BaseAdapter

logger = logging.getLogger(__name__)


class OpenaiAdapter(BaseAdapter):  # Class name should match provider for factory
    """Adapter for interacting with OpenAI models."""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._setup_client()

    def _setup_client(self):
        api_key = self._get_api_key()
        if not api_key:
            raise AIAdapterError("OpenAI API key is missing in configuration.")
        # Use openai library's configuration mechanism
        openai.api_key = api_key
        # Handle base_url if needed for proxies or Azure OpenAI
        if self._get_base_url():
            openai.api_base = self._get_base_url()
            logger.info(f"Using custom OpenAI API base URL: {openai.api_base}")
        # Set organization etc. if needed from config

    def generate(self, prompt: str, params: dict) -> tuple[str, dict]:
        model_id = self.config.model_id
        logger.info(f"Sending request to OpenAI model: {model_id}")

        # Prepare parameters for OpenAI API
        # Common params: temperature, max_tokens, top_p, frequency_penalty, presence_penalty
        api_params = {
            "model": model_id,
            "temperature": params.get(
                "temperature", 0.7
            ),  # Default from config or global default
            "max_tokens": params.get("max_tokens", 1024),
            # Add other params as needed based on 'params' dict and OpenAI capabilities
        }
        # Add specific params if available
        if "top_p" in params:
            api_params["top_p"] = params["top_p"]
        if "frequency_penalty" in params:
            api_params["frequency_penalty"] = params["frequency_penalty"]
        if "presence_penalty" in params:
            api_params["presence_penalty"] = params["presence_penalty"]
        # Add stop sequences etc.

        try:
            # Determine if using Chat Completion or older Completion endpoint based on model?
            # Assuming Chat Completion for modern models (gpt-3.5-turbo, gpt-4)
            if "gpt-3.5" in model_id or "gpt-4" in model_id:
                response = openai.ChatCompletion.create(
                    messages=[{"role": "user", "content": prompt}], **api_params
                )
                generated_text = response.choices[0].message.content.strip()
                usage = response.usage
                finish_reason = response.choices[0].finish_reason
                metadata = {
                    "model_used": response.model,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "finish_reason": finish_reason,
                }
            else:
                # Use older Completion endpoint (e.g., text-davinci-003)
                response = openai.Completion.create(prompt=prompt, **api_params)
                generated_text = response.choices[0].text.strip()
                usage = response.usage
                finish_reason = response.choices[0].finish_reason
                metadata = {
                    "model_used": response.model,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "finish_reason": finish_reason,
                }

            logger.info(
                f"Received response from OpenAI model {model_id}. Finish reason: {finish_reason}"
            )
            return generated_text, metadata

        except openai.error.OpenAIError as e:
            logger.error(f"OpenAI API error: {e}", exc_info=True)
            raise AIAdapterError(f"OpenAI API error: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during OpenAI call: {e}", exc_info=True)
            raise AIAdapterError(f"Unexpected error: {e}") from e
