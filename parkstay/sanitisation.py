import nh3
from django.core.exceptions import ValidationError


# Input policy for plain text fields entered by customers (task 19165).
# Keep the policy in this one function, so it can be changed later
# (e.g. strip instead of reject) without touching the callers.
def check_plain_text(value):
    if isinstance(value, str) and nh3.is_html(value):
        raise ValidationError('HTML tags are not allowed.')
    return value
