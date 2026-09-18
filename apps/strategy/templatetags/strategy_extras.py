"""One filter: read a key out of an answer's `value` object in a template."""

from django import template

register = template.Library()


@register.filter
def get(mapping, key):
    if isinstance(mapping, dict):
        return mapping.get(key, "")
    return ""
