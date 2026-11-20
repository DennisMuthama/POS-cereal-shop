from django.core.exceptions import ValidationError


def validate_passcode(value):
    """Passcode rules: 5-8 digits, not all the same digit, not a straight sequence."""
    if not value.isdigit():
        raise ValidationError("Passcode must contain digits only.")

    if not 5 <= len(value) <= 8:
        raise ValidationError("Passcode must be between 5 and 8 digits long.")

    if len(set(value)) == 1:
        raise ValidationError("Passcode cannot be the same digit repeated (e.g. 11111).")

    digits = [int(c) for c in value]
    steps = {digits[i + 1] - digits[i] for i in range(len(digits) - 1)}
    if steps == {1} or steps == {-1}:
        raise ValidationError("Passcode cannot be a straight sequence (e.g. 12345 or 54321).")