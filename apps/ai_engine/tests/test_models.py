"""Tests for AI Engine models."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.ai_engine.models import (
    GeneratedContent,
    GenerationJob,
    ModelConfig,
    ModelProvider,
    PromptTemplate,
)
from apps.core.models import Tenant
from apps.users.models import User


class ModelConfigTests(TestCase):
    """Tests for the ModelConfig model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_create_model_config(self):
        """Test creating a model config."""
        config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="OpenAI GPT-4",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
            api_key="sk-test-key",
            is_active=True,
        )
        self.assertEqual(config.name, "OpenAI GPT-4")
        self.assertEqual(config.provider, ModelProvider.OPENAI)
        self.assertEqual(config.model_id, "gpt-4")
        self.assertTrue(config.is_active)

    def test_model_config_str(self):
        """Test string representation of ModelConfig."""
        config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="Claude Config",
            provider=ModelProvider.ANTHROPIC,
            model_id="claude-2",
        )
        expected_str = f"Claude Config (ANTHROPIC - claude-2) [{self.tenant.name}]"
        self.assertEqual(str(config), expected_str)

    def test_model_config_unique_name_per_tenant(self):
        """Test that model config names are unique per tenant."""
        ModelConfig.objects.create(
            tenant=self.tenant,
            name="My Config",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
        )
        with self.assertRaises(IntegrityError):
            ModelConfig.objects.create(
                tenant=self.tenant,
                name="My Config",  # Same name, same tenant
                provider=ModelProvider.ANTHROPIC,
                model_id="claude-2",
            )

    def test_model_config_same_name_different_tenants(self):
        """Test that model configs can have same name in different tenants."""
        tenant2 = Tenant.objects.create(name="Tenant 2", slug="tenant-2")
        ModelConfig.objects.create(
            tenant=self.tenant,
            name="My Config",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
        )
        # Should not raise
        config2 = ModelConfig.objects.create(
            tenant=tenant2,
            name="My Config",
            provider=ModelProvider.ANTHROPIC,
            model_id="claude-2",
        )
        self.assertEqual(config2.name, "My Config")

    def test_model_config_default_params(self):
        """Test default_params field defaults to empty dict."""
        config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="Test Config",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
        )
        self.assertEqual(config.default_params, {})

    def test_model_config_with_custom_params(self):
        """Test creating config with custom default params."""
        params = {"temperature": 0.7, "max_tokens": 2048}
        config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="Custom Config",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
            default_params=params,
        )
        self.assertEqual(config.default_params["temperature"], 0.7)
        self.assertEqual(config.default_params["max_tokens"], 2048)


class PromptTemplateTests(TestCase):
    """Tests for the PromptTemplate model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.model_config = ModelConfig.objects.create(
            tenant=self.tenant,
            name="OpenAI GPT-4",
            provider=ModelProvider.OPENAI,
            model_id="gpt-4",
        )

    def test_create_prompt_template(self):
        """Test creating a prompt template."""
        template = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Question Generator",
            description="Generate quiz questions from content",
            template_text="Generate {num_questions} questions about {topic}",
            variables=["num_questions", "topic"],
        )
        self.assertEqual(template.name, "Question Generator")
        self.assertIn("num_questions", template.variables)

    def test_prompt_template_str(self):
        """Test string representation of PromptTemplate."""
        template = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Summary Generator",
            template_text="Summarize: {text}",
        )
        expected_str = f"Summary Generator ({self.tenant.name})"
        self.assertEqual(str(template), expected_str)

    def test_prompt_template_with_default_model_config(self):
        """Test prompt template with default model config."""
        template = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Quiz Generator",
            template_text="Generate questions about {topic}",
            default_model_config=self.model_config,
        )
        self.assertEqual(template.default_model_config, self.model_config)

    def test_prompt_template_unique_name_per_tenant(self):
        """Test that template names are unique per tenant."""
        PromptTemplate.objects.create(
            tenant=self.tenant,
            name="My Template",
            template_text="Test template",
        )
        with self.assertRaises(IntegrityError):
            PromptTemplate.objects.create(
                tenant=self.tenant,
                name="My Template",  # Same name, same tenant
                template_text="Another template",
            )


class GenerationJobTests(TestCase):
    """Tests for the GenerationJob model."""

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
        )
        self.template = PromptTemplate.objects.create(
            tenant=self.tenant,
            name="Test Template",
            template_text="Generate {content}",
            default_model_config=self.model_config,
        )

    def test_create_generation_job(self):
        """Test creating a generation job."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            prompt_template=self.template,
            model_config_used=self.model_config,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt="Generate quiz questions",
            input_context={"content": "quiz questions"},
        )
        self.assertEqual(job.status, GenerationJob.JobStatus.PENDING)
        self.assertEqual(job.user, self.user)

    def test_generation_job_default_status(self):
        """Test that default status is PENDING."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            input_prompt="Test prompt",
        )
        self.assertEqual(job.status, GenerationJob.JobStatus.PENDING)

    def test_generation_job_str(self):
        """Test string representation of GenerationJob."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            prompt_template=self.template,
            input_prompt="Test prompt",
        )
        expected_str = f"Job {job.id} ({self.template.name}) - {job.status}"
        self.assertEqual(str(job), expected_str)

    def test_generation_job_str_custom_prompt(self):
        """Test string representation without template."""
        job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            input_prompt="Custom prompt",
        )
        self.assertIn("Custom Prompt", str(job))

    def test_generation_job_status_choices(self):
        """Test all job status choices."""
        statuses = [
            GenerationJob.JobStatus.PENDING,
            GenerationJob.JobStatus.IN_PROGRESS,
            GenerationJob.JobStatus.COMPLETED,
            GenerationJob.JobStatus.FAILED,
            GenerationJob.JobStatus.CANCELLED,
        ]
        for status in statuses:
            job = GenerationJob.objects.create(
                tenant=self.tenant,
                user=self.user,
                status=status,
                input_prompt="Test",
            )
            self.assertEqual(job.status, status)


class GeneratedContentTests(TestCase):
    """Tests for the GeneratedContent model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.job = GenerationJob.objects.create(
            tenant=self.tenant,
            user=self.user,
            input_prompt="Generate content",
        )

    def test_create_generated_content(self):
        """Test creating generated content."""
        content = GeneratedContent.objects.create(
            job=self.job,
            tenant=self.tenant,
            user=self.user,
            generated_text="This is the generated text.",
            metadata={"tokens_used": 150},
        )
        self.assertEqual(content.generated_text, "This is the generated text.")
        self.assertEqual(content.metadata["tokens_used"], 150)

    def test_generated_content_str(self):
        """Test string representation of GeneratedContent."""
        content = GeneratedContent.objects.create(
            job=self.job,
            tenant=self.tenant,
            user=self.user,
            generated_text="Test content",
        )
        expected_str = f"Generated Content {content.id} (Job: {self.job.id})"
        self.assertEqual(str(content), expected_str)

    def test_generated_content_rating_validation(self):
        """Test rating validators (1-5)."""
        content = GeneratedContent.objects.create(
            job=self.job,
            tenant=self.tenant,
            user=self.user,
            generated_text="Test content",
            rating=5,
        )
        self.assertEqual(content.rating, 5)

    def test_generated_content_evaluation_fields(self):
        """Test evaluation fields on generated content."""
        content = GeneratedContent.objects.create(
            job=self.job,
            tenant=self.tenant,
            user=self.user,
            generated_text="Test content",
            is_accepted=True,
            rating=4,
            evaluation_feedback="Good quality content.",
        )
        self.assertTrue(content.is_accepted)
        self.assertEqual(content.rating, 4)
        self.assertEqual(content.evaluation_feedback, "Good quality content.")

    def test_generated_content_without_job(self):
        """Test creating generated content without a job."""
        content = GeneratedContent.objects.create(
            tenant=self.tenant,
            user=self.user,
            generated_text="Standalone content",
        )
        self.assertIsNone(content.job)
