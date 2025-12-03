from abc import ABC, abstractmethod

from ..models import ModelConfig


class AIAdapterError(Exception):
    """Exception raised when an AI adapter encounters an error."""
    pass


class BaseAdapter(ABC):
    """Abstract base class for AI model adapters."""

    def __init__(self, config: ModelConfig):
        self.config = config

    @abstractmethod
    def generate(self, prompt: str, params: dict) -> tuple[str, dict]:
        """
        Sends the prompt to the AI model and returns the generated text and metadata.
        Must be implemented by subclasses.

        :param prompt: The input prompt text.
        :param params: Dictionary of parameters for the generation call (e.g., temperature, max_tokens).
        :return: A tuple containing (generated_text: str, metadata: dict).
                 Metadata might include token usage, cost, finish reason, etc.
        :raises AIAdapterError: If the API call fails.
        """
        pass

    def _get_api_key(self) -> str | None:
        """Helper to safely get the API key from config."""
        # In production, use a secure way to retrieve keys (e.g., Vault, KMS)
        return self.config.api_key

    def _get_base_url(self) -> str | None:
        """Helper to get the base URL if specified."""
        return self.config.base_url
