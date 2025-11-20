# core/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Allows dictionary lookup with a variable key in a template.
    Usage: {{ my_dictionary|get_item:my_variable }}
    """
    return dictionary.get(key)


# --- ADD THIS NEW FILTER TO YOUR EXISTING FILE ---
@register.filter
def add_attr(field, attr_string):
    key, value = attr_string.split(':', 1)
    return field.as_widget(attrs={key: value})