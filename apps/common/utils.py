import logging
import re

logger = logging.getLogger(__name__)


def generate_unique_slug(instance, source_field="name", slug_field="slug"):
    """
    Generates a unique slug for a model instance.
    If a slug already exists, it appends a number.
    Assumes the model has a 'slug' field.
    """
    from django.utils.text import slugify

    if getattr(instance, slug_field):  # If slug is already set, assume it's intended
        return getattr(instance, slug_field)

    source_value = getattr(instance, source_field)
    if not source_value:
        # Handle cases where the source field might be empty
        # You might want to use the instance's pk or a random string
        import uuid

        base_slug = slugify(str(uuid.uuid4())[:8])
    else:
        base_slug = slugify(source_value)

    if not base_slug:  # Handle cases where slugify returns empty string
        import uuid

        base_slug = slugify(str(uuid.uuid4())[:8])

    ModelClass = instance.__class__
    slug = base_slug
    counter = 1
    while (
        ModelClass.objects.filter(**{slug_field: slug}).exclude(pk=instance.pk).exists()
    ):
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def clean_html(raw_html):
    """
    Basic HTML cleaning. For production, use a robust library like Bleach.
    """
    if not raw_html:
        return ""
    # Very basic example: remove script tags
    clean_text = re.sub(
        r"<script.*?</script>", "", raw_html, flags=re.IGNORECASE | re.DOTALL
    )
    # Add more cleaning rules as needed or use Bleach:
    # import bleach
    # allowed_tags = ['p', 'strong', 'em', 'ul', 'ol', 'li', 'a', 'br']
    # allowed_attributes = {'a': ['href', 'title']}
    # cleaned = bleach.clean(raw_html, tags=allowed_tags, attributes=allowed_attributes, strip=True)
    # return cleaned
    return clean_text


# Add other utility functions relevant across apps
