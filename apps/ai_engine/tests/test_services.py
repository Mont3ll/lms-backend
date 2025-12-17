"""Tests for AI Engine services."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.ai_engine.models import (
    GeneratedContent,
    GenerationJob,
    ModelConfig,
    ModelProvider,
    PromptTemplate,
)
from apps.ai_engine.services import (
    AIAdapterError,
    AIAdapterFactory,
    ContentGeneratorService,
)
from apps.core.models import Tenant
from apps.users.models import User


class AIAdapterFactoryTests(TestCase):
    """Tests for the AIAdapterFactory."""

    def test_get_adapter_openai(self):
        """Test getting OpenAI adapter (skipped if openai not installed)."""
        try:
            adapter_class = AIAdapterFactory.get_adapter("OPENAI")
            self.assertIsNotNone(adapter_class)
            self.assertEqual(adapter_class.__name__, "OpenaiAdapter")
        except AIAdapterError as e:
            if "No module named 'openai'" in str(e.__cause__):
                self.skipTest("openai module not installed")
            raise

    def test_get_adapter_anthropic(self):
        """Test getting Anthropic adapter (skipped if anthropic not installed)."""
        try:
            adapter_class = AIAdapterFactory.get_adapter("ANTHROPIC")
            self.assertIsNotNone(adapter_class)
            self.assertEqual(adapter_class.__name__, "AnthropicAdapter")
        except AIAdapterError as e:
            if "No module named" in str(e.__cause__):
                self.skipTest("anthropic module not installed")
            raise

    def test_get_adapter_huggingface(self):
        """Test getting HuggingFace adapter (skipped if module not installed)."""
        try:
            adapter_class = AIAdapterFactory.get_adapter("HUGGINGFACE")
            self.assertIsNotNone(adapter_class)
            self.assertEqual(adapter_class.__name__, "HuggingfaceAdapter")
        except AIAdapterError as e:
            if "No module named" in str(e.__cause__):
                self.skipTest("huggingface module not installed")
            raise

    def test_get_adapter_caches_result(self):
        """Test that adapter classes are cached."""
        AIAdapterFactory._adapter_cache.clear()
        try:
            adapter1 = AIAdapterFactory.get_adapter("OPENAI")
            adapter2 = AIAdapterFactory.get_adapter("OPENAI")
            self.assertIs(adapter1, adapter2)
        except AIAdapterError as e:
            if "No module named" in str(e.__cause__):
                self.skipTest("openai module not installed")
            raise

    def test_get_adapter_invalid_provider(self):
        """Test getting adapter for invalid provider raises error."""
        with self.assertRaises(AIAdapterError) as context:
            AIAdapterFactory.get_adapter("INVALID_PROVIDER")
        self.assertIn("not found", str(context.exception))


class ContentGeneratorServiceTests(TestCase):
    """Tests for the ContentGeneratorService."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.model_config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="OpenAI GPT-4",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
            api_key="sk-test-key",
            is_active=True,
            default_params={"temperature": 0.7},
        )
        self.template = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Question Generator",
            template_text="Generate {num_questions} questions about {topic}",
            variables=["num_questions", "topic"],
            default_model_config=self.model_config,
        )

    @patch("apps.ai_engine.services.trigger_ai_generation_task")
    def test_start_generation_job_with_template(self, mock_task):
        """Test starting a generation job with a prompt template."""
        mock_task.delay.return_value = MagicMock(id="celery-task-id")

        job = ContentGeneratorService.start_generation_job(
            tenant=self.tenant,
            user=self.user,
            prompt_template=self.template,
            input_context={"num_questions": "5", "topic": "Python"},
        )

        self.assertEqual(job.status, GenerationJob.JobStatus.PENDING)
        self.assertEqual(job.tenant, self.tenant)
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.prompt_template, self.template)
        self.assertEqual(job.model_config_used, self.model_config)
        self.assertIn("5 questions", job.input_prompt)
        self.assertIn("Python", job.input_prompt)
        self.assertEqual(job.celery_task_id, "celery-task-id")
        mock_task.delay.assert_called_once_with(job.id)

    @patch("apps.ai_engine.services.trigger_ai_generation_task")
    def test_start_generation_job_with_custom_model_config(self, mock_task):
        """Test starting a generation job with a custom model config."""
        mock_task.delay.return_value = MagicMock(id="celery-task-id")

        custom_config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="Claude Custom",
            provider=ModelProvider.ANTHROPIC,
            model_id="claude-2",
            is_active=True,
        )

        job = ContentGeneratorService.start_generation_job(
            tenant=self.tenant,
            user=self.user,
            prompt_template=self.template,
            model_config=custom_config,
            input_context={"num_questions": "3", "topic": "Django"},
        )

        self.assertEqual(job.model_config_used, custom_config)

    @patch("apps.ai_engine.services.trigger_ai_generation_task")
    def test_start_generation_job_with_custom_params(self, mock_task):
        """Test that generation params override model config defaults."""
        mock_task.delay.return_value = MagicMock(id="celery-task-id")

        job = ContentGeneratorService.start_generation_job(
            tenant=self.tenant,
            user=self.user,
            prompt_template=self.template,
            input_context={"num_questions": "5", "topic": "Python"},
            generation_params={"temperature": 0.9, "max_tokens": 2048},
        )

        # Default temp was 0.7, should be overridden to 0.9
        self.assertEqual(job.generation_params["temperature"], 0.9)
        self.assertEqual(job.generation_params["max_tokens"], 2048)

    def test_start_generation_job_missing_tenant(self):
        """Test that missing tenant raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=None,
                user=self.user,
                prompt_template=self.template,
                input_context={},
            )
        self.assertIn("Tenant and User are required", str(context.exception))

    def test_start_generation_job_missing_user(self):
        """Test that missing user raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=None,
                prompt_template=self.template,
                input_context={},
            )
        self.assertIn("Tenant and User are required", str(context.exception))

    def test_start_generation_job_no_template_or_custom_prompt(self):
        """Test that missing both template and custom prompt raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=self.user,
                prompt_template=None,
                custom_prompt=None,
                input_context={},
            )
        self.assertIn(
            "Either prompt_template or custom_prompt must be provided",
            str(context.exception),
        )

    def test_start_generation_job_both_template_and_custom_prompt(self):
        """Test that providing both template and custom prompt raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=self.user,
                prompt_template=self.template,
                custom_prompt="Custom prompt text",
                input_context={},
            )
        self.assertIn(
            "Provide either prompt_template or custom_prompt, not both",
            str(context.exception),
        )

    def test_start_generation_job_inactive_model_config(self):
        """Test that inactive model config raises ValueError."""
        self.model_config.is_active = False
        self.model_config.save()

        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=self.user,
                prompt_template=self.template,
                input_context={"num_questions": "5", "topic": "Python"},
            )
        self.assertIn("is not active", str(context.exception))

    def test_start_generation_job_missing_template_variable(self):
        """Test that missing template variable raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=self.user,
                prompt_template=self.template,
                input_context={"num_questions": "5"},  # Missing 'topic'
            )
        self.assertIn("Missing variable", str(context.exception))

    def test_start_generation_job_no_model_config(self):
        """Test that no model config available raises ValueError."""
        template_no_config = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Template Without Config",
            template_text="Test {text}",
            default_model_config=None,
        )

        with self.assertRaises(ValueError) as context:
            ContentGeneratorService.start_generation_job(
                tenant=self.tenant,
                user=self.user,
                prompt_template=template_no_config,
                model_config=None,
                input_context={"text": "hello"},
            )
        self.assertIn(
            "AI Model Configuration must be specified", str(context.exception)
        )


class ExecuteGenerationTests(TestCase):
    """Tests for the execute_generation method."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.model_config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="OpenAI GPT-4",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
            api_key="sk-test-key",
            is_active=True,
        )

    def test_execute_generation_job_not_found(self):
        """Test execution with non-existent job ID."""
        import uuid

        # Should not raise, just log warning
        ContentGeneratorService.execute_generation(uuid.uuid4())
        # No exception means success

    def test_execute_generation_not_pending(self):
        """Test that non-pending jobs are skipped."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            model_config_used=self.model_config,
            status=GenerationJob.JobStatus.COMPLETED,
            input_prompt="Test prompt",
        )

        ContentGeneratorService.execute_generation(job.id)
        job.refresh_from_db()
        # Status should remain COMPLETED (not changed)
        self.assertEqual(job.status, GenerationJob.JobStatus.COMPLETED)

    def test_execute_generation_missing_model_config(self):
        """Test execution fails when model config is missing."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            model_config_used=None,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt="Test prompt",
        )

        ContentGeneratorService.execute_generation(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, GenerationJob.JobStatus.FAILED)
        self.assertIn("Model configuration missing", job.error_message)

    @patch("apps.ai_engine.services.AIAdapterFactory.get_adapter")
    def test_execute_generation_success(self, mock_get_adapter):
        """Test successful execution creates GeneratedContent."""
        mock_adapter_class = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.generate.return_value = (
            "Generated text response",
            {"tokens_used": 100},
        )
        mock_adapter_class.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_class

        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            model_config_used=self.model_config,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt="Generate quiz questions",
            generation_params={"temperature": 0.7},
        )

        ContentGeneratorService.execute_generation(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, GenerationJob.JobStatus.COMPLETED)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)

        # Check generated content was created
        content = GeneratedContent.objects.get(job=job)
        self.assertEqual(content.generated_text, "Generated text response")
        self.assertEqual(content.metadata["tokens_used"], 100)
        self.assertEqual(content.tenant, self.tenant)
        self.assertEqual(content.user, self.user)

    @patch("apps.ai_engine.services.AIAdapterFactory.get_adapter")
    def test_execute_generation_api_error(self, mock_get_adapter):
        """Test execution handles API errors gracefully."""
        mock_adapter_class = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.generate.side_effect = Exception("API Error: Rate limit")
        mock_adapter_class.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_class

        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            model_config_used=self.model_config,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt="Generate content",
        )

        ContentGeneratorService.execute_generation(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, GenerationJob.JobStatus.FAILED)
        self.assertIn("Rate limit", job.error_message)
        self.assertIsNotNone(job.completed_at)


class CustomPromptTests(TestCase):
    """Tests for custom prompt functionality."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.model_config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="OpenAI GPT-4",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
            api_key="sk-test-key",
            is_active=True,
        )

    @patch("apps.ai_engine.services.trigger_ai_generation_task")
    def test_start_generation_job_with_custom_prompt(self, mock_task):
        """Test starting a generation job with a custom prompt."""
        mock_task.delay.return_value = MagicMock(id="celery-task-id")

        job = ContentGeneratorService.start_generation_job(
            tenant=self.tenant,
            user=self.user,
            prompt_template=None,
            model_config=self.model_config,
            custom_prompt="Write a haiku about programming",
            input_context={},
        )

        self.assertEqual(job.status, GenerationJob.JobStatus.PENDING)
        self.assertEqual(job.input_prompt, "Write a haiku about programming")
        self.assertIsNone(job.prompt_template)
