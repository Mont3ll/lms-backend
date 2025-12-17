import logging
from typing import Any

import requests

from ..models import ModelConfig
from .base import AIAdapterError, BaseAdapter

logger = logging.getLogger(__name__)


class CustomAdapter(BaseAdapter):
    """
    Adapter for interacting with custom/self-hosted AI models.
    
    Supports flexible API configurations for various self-hosted solutions:
    - OpenAI-compatible APIs (e.g., vLLM, LocalAI, Ollama with OpenAI API)
    - Custom REST endpoints
    - Generic chat/completion endpoints
    
    Configuration via ModelConfig:
        - base_url: The base URL of the API (required)
        - api_key: API key if required by the endpoint (optional)
        - model_id: Model identifier to use
        - default_params: Default parameters including:
            - api_format: 'openai', 'ollama', 'generic' (default: 'openai')
            - endpoint_path: Custom endpoint path (default: '/v1/chat/completions')
            - request_format: Custom request body format template
            - response_path: JSON path to extract generated text from response
            - headers: Additional headers to send
    """

    # Supported API formats
    FORMAT_OPENAI = 'openai'  # OpenAI-compatible APIs
    FORMAT_OLLAMA = 'ollama'  # Ollama native API
    FORMAT_GENERIC = 'generic'  # Generic REST API

    # Default timeouts
    DEFAULT_TIMEOUT = 120  # seconds
    DEFAULT_CONNECT_TIMEOUT = 10  # seconds

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._validate_config()

    def _validate_config(self):
        """Validate the configuration has required fields."""
        if not self._get_base_url():
            raise AIAdapterError(
                "Custom adapter requires 'base_url' to be configured."
            )

    def _get_api_format(self) -> str:
        """Get the API format from config, defaulting to OpenAI-compatible."""
        params = self.config.default_params or {}
        return params.get('api_format', self.FORMAT_OPENAI)

    def _get_endpoint_path(self) -> str:
        """Get the endpoint path based on API format or custom override."""
        params = self.config.default_params or {}
        
        # Allow custom endpoint path override
        if 'endpoint_path' in params:
            return params['endpoint_path']
        
        # Default paths based on format
        api_format = self._get_api_format()
        if api_format == self.FORMAT_OLLAMA:
            return '/api/generate'
        elif api_format == self.FORMAT_OPENAI:
            return '/v1/chat/completions'
        else:  # generic
            return '/generate'

    def _get_headers(self) -> dict:
        """Build headers for the API request."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        
        api_key = self._get_api_key()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        
        # Add any custom headers from config
        params = self.config.default_params or {}
        custom_headers = params.get('headers', {})
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)
        
        return headers

    def _build_request_body(self, prompt: str, params: dict) -> dict:
        """Build the request body based on API format."""
        api_format = self._get_api_format()
        model_id = self.config.model_id
        
        # Common parameters
        temperature = params.get('temperature', 0.7)
        max_tokens = params.get('max_tokens', 1024)
        
        if api_format == self.FORMAT_OPENAI:
            # OpenAI-compatible format
            body = {
                'model': model_id,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': temperature,
                'max_tokens': max_tokens,
            }
            
            # Add optional parameters
            if 'top_p' in params:
                body['top_p'] = params['top_p']
            if 'frequency_penalty' in params:
                body['frequency_penalty'] = params['frequency_penalty']
            if 'presence_penalty' in params:
                body['presence_penalty'] = params['presence_penalty']
            if 'stop' in params:
                body['stop'] = params['stop']
            if 'stream' in params:
                body['stream'] = params['stream']
            
            # Support system prompt
            system_prompt = params.get('system', params.get('system_prompt'))
            if system_prompt:
                body['messages'].insert(0, {'role': 'system', 'content': system_prompt})
                
        elif api_format == self.FORMAT_OLLAMA:
            # Ollama native API format
            body = {
                'model': model_id,
                'prompt': prompt,
                'stream': False,  # Disable streaming for simpler handling
                'options': {
                    'temperature': temperature,
                    'num_predict': max_tokens,
                }
            }
            
            # Add optional Ollama-specific parameters
            if 'top_p' in params:
                body['options']['top_p'] = params['top_p']
            if 'top_k' in params:
                body['options']['top_k'] = params['top_k']
            if 'repeat_penalty' in params:
                body['options']['repeat_penalty'] = params['repeat_penalty']
            
            # System prompt for Ollama
            system_prompt = params.get('system', params.get('system_prompt'))
            if system_prompt:
                body['system'] = system_prompt
                
        else:  # generic format
            # Generic format - allow full customization via request_format
            config_params = self.config.default_params or {}
            request_format = config_params.get('request_format')
            
            if request_format and isinstance(request_format, dict):
                # Use custom request format as template
                body = self._apply_template(request_format, {
                    'model': model_id,
                    'prompt': prompt,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    **params
                })
            else:
                # Fallback generic format
                body = {
                    'model': model_id,
                    'input': prompt,
                    'parameters': {
                        'temperature': temperature,
                        'max_tokens': max_tokens,
                        **{k: v for k, v in params.items() if k not in ['temperature', 'max_tokens']}
                    }
                }
        
        return body

    def _apply_template(self, template: dict, values: dict) -> dict:
        """Apply values to a template dict, replacing {key} placeholders."""
        import json
        import re
        
        # Convert to JSON string, replace placeholders, convert back
        template_str = json.dumps(template)
        
        for key, value in values.items():
            placeholder = '{' + key + '}'
            if placeholder in template_str:
                if isinstance(value, str):
                    # Escape for JSON string context
                    value = json.dumps(value)[1:-1]  # Remove surrounding quotes
                else:
                    value = json.dumps(value)
                    # If it's being inserted into a string context, we need to handle differently
                    if f'"{placeholder}"' in template_str:
                        template_str = template_str.replace(f'"{placeholder}"', value)
                        continue
                template_str = template_str.replace(placeholder, str(value) if not isinstance(value, str) else value)
        
        return json.loads(template_str)

    def _extract_response_text(self, response_data: dict) -> tuple[str, dict]:
        """
        Extract generated text and metadata from API response.
        
        Returns:
            Tuple of (generated_text, metadata)
        """
        api_format = self._get_api_format()
        config_params = self.config.default_params or {}
        
        generated_text = ""
        metadata = {
            'model_used': self.config.model_id,
        }
        
        if api_format == self.FORMAT_OPENAI:
            # OpenAI-compatible response format
            try:
                choices = response_data.get('choices', [])
                if choices:
                    message = choices[0].get('message', {})
                    generated_text = message.get('content', '').strip()
                    metadata['finish_reason'] = choices[0].get('finish_reason')
                
                # Extract usage info if available
                usage = response_data.get('usage', {})
                if usage:
                    metadata['prompt_tokens'] = usage.get('prompt_tokens')
                    metadata['completion_tokens'] = usage.get('completion_tokens')
                    metadata['total_tokens'] = usage.get('total_tokens')
                
                if response_data.get('model'):
                    metadata['model_used'] = response_data['model']
                    
            except (KeyError, IndexError, TypeError) as e:
                logger.warning(f"Error parsing OpenAI-format response: {e}")
                # Try to extract any text we can find
                generated_text = str(response_data)
                
        elif api_format == self.FORMAT_OLLAMA:
            # Ollama native response format
            try:
                generated_text = response_data.get('response', '').strip()
                
                # Ollama metadata
                if 'total_duration' in response_data:
                    metadata['total_duration_ns'] = response_data['total_duration']
                if 'eval_count' in response_data:
                    metadata['eval_count'] = response_data['eval_count']
                if 'prompt_eval_count' in response_data:
                    metadata['prompt_eval_count'] = response_data['prompt_eval_count']
                if response_data.get('done_reason'):
                    metadata['finish_reason'] = response_data['done_reason']
                if response_data.get('model'):
                    metadata['model_used'] = response_data['model']
                    
            except (KeyError, TypeError) as e:
                logger.warning(f"Error parsing Ollama response: {e}")
                generated_text = str(response_data)
                
        else:  # generic
            # Try custom response_path or common patterns
            response_path = config_params.get('response_path')
            
            if response_path:
                # Navigate to specified path (e.g., "data.generated_text")
                generated_text = self._extract_by_path(response_data, response_path)
            else:
                # Try common response field names
                for field in ['text', 'generated_text', 'output', 'content', 'response', 'result']:
                    if field in response_data:
                        value = response_data[field]
                        if isinstance(value, str):
                            generated_text = value.strip()
                            break
                        elif isinstance(value, list) and value:
                            generated_text = str(value[0]).strip()
                            break
                
                if not generated_text:
                    # Last resort: stringify the whole response
                    generated_text = str(response_data)
        
        return generated_text, metadata

    def _extract_by_path(self, data: dict, path: str) -> str:
        """Extract a value from nested dict using dot notation path."""
        try:
            parts = path.split('.')
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, '')
                elif isinstance(value, list) and part.isdigit():
                    value = value[int(part)]
                else:
                    return ''
            return str(value).strip() if value else ''
        except (KeyError, IndexError, TypeError):
            return ''

    def generate(self, prompt: str, params: dict) -> tuple[str, dict]:
        """
        Send a generation request to the custom API endpoint.
        
        Args:
            prompt: The input prompt text
            params: Parameters for generation (temperature, max_tokens, etc.)
            
        Returns:
            Tuple of (generated_text, metadata)
            
        Raises:
            AIAdapterError: If the API call fails
        """
        base_url = self._get_base_url().rstrip('/')
        endpoint_path = self._get_endpoint_path()
        full_url = f"{base_url}{endpoint_path}"
        
        logger.info(
            f"Sending request to custom endpoint: {full_url} "
            f"(model: {self.config.model_id}, format: {self._get_api_format()})"
        )
        
        headers = self._get_headers()
        body = self._build_request_body(prompt, params)
        
        # Get timeout settings
        config_params = self.config.default_params or {}
        timeout = (
            config_params.get('connect_timeout', self.DEFAULT_CONNECT_TIMEOUT),
            config_params.get('timeout', self.DEFAULT_TIMEOUT)
        )
        
        try:
            response = requests.post(
                full_url,
                headers=headers,
                json=body,
                timeout=timeout
            )
            
            # Log response status
            logger.debug(f"Custom API response status: {response.status_code}")
            
            # Check for HTTP errors
            if response.status_code >= 400:
                error_detail = response.text[:500] if response.text else "No error details"
                logger.error(
                    f"Custom API error: {response.status_code} - {error_detail}"
                )
                raise AIAdapterError(
                    f"Custom API returned error {response.status_code}: {error_detail}"
                )
            
            # Parse response
            try:
                response_data = response.json()
            except ValueError as e:
                # Response is not JSON
                logger.warning(f"Custom API response is not JSON: {response.text[:200]}")
                return response.text.strip(), {'model_used': self.config.model_id, 'raw_response': True}
            
            # Extract text and metadata
            generated_text, metadata = self._extract_response_text(response_data)
            
            if not generated_text:
                logger.warning(
                    f"Custom API returned empty response. Raw: {str(response_data)[:200]}"
                )
            
            logger.info(
                f"Received response from custom endpoint {full_url}. "
                f"Text length: {len(generated_text)}"
            )
            
            return generated_text, metadata
            
        except requests.exceptions.Timeout as e:
            logger.error(f"Custom API timeout: {e}")
            raise AIAdapterError(f"Custom API request timed out after {timeout[1]}s") from e
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Custom API connection error: {e}")
            raise AIAdapterError(f"Failed to connect to custom API at {full_url}") from e
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API request error: {e}", exc_info=True)
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = f"{e.response.status_code} - {e.response.text[:500]}"
                except Exception:
                    pass
            raise AIAdapterError(f"Custom API request error: {error_detail}") from e
            
        except Exception as e:
            logger.error(f"Unexpected error during custom API call: {e}", exc_info=True)
            raise AIAdapterError(f"Unexpected error: {e}") from e

    def health_check(self) -> dict:
        """
        Perform a health check on the custom API endpoint.
        
        Returns:
            Dict with 'status' ('healthy' or 'unhealthy'), 'latency_ms', 'details'
        """
        import time
        
        base_url = self._get_base_url().rstrip('/')
        
        # Try common health check endpoints
        health_endpoints = ['/health', '/v1/models', '/api/tags', '/']
        
        config_params = self.config.default_params or {}
        custom_health_endpoint = config_params.get('health_endpoint')
        if custom_health_endpoint:
            health_endpoints.insert(0, custom_health_endpoint)
        
        for endpoint in health_endpoints:
            url = f"{base_url}{endpoint}"
            try:
                start_time = time.time()
                response = requests.get(
                    url,
                    headers=self._get_headers(),
                    timeout=(5, 10)
                )
                latency_ms = (time.time() - start_time) * 1000
                
                if response.status_code < 400:
                    return {
                        'status': 'healthy',
                        'latency_ms': round(latency_ms, 2),
                        'endpoint': endpoint,
                        'details': {
                            'status_code': response.status_code,
                            'base_url': base_url
                        }
                    }
            except Exception as e:
                logger.debug(f"Health check failed for {url}: {e}")
                continue
        
        return {
            'status': 'unhealthy',
            'latency_ms': None,
            'details': {
                'error': 'All health check endpoints failed',
                'base_url': base_url
            }
        }
