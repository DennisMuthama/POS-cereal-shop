from django import forms

from .models import Employee
from .validators import validate_passcode


class LoginForm(forms.Form):
    employee_id = forms.CharField(
        label="Employee ID",
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control form-control-lg", "autofocus": True, "autocomplete": "off"}),
    )
    passcode = forms.CharField(
        label="Passcode",
        widget=forms.PasswordInput(
            attrs={"class": "form-control form-control-lg", "autocomplete": "off", "inputmode": "numeric"}
        ),
    )


class ChangePasscodeForm(forms.Form):
    new_passcode = forms.CharField(
        label="New passcode",
        validators=[validate_passcode],
        help_text="5 to 8 digits. No repeated digits or straight sequences.",
        widget=forms.PasswordInput(
            attrs={"class": "form-control form-control-lg", "autocomplete": "new-password", "inputmode": "numeric"}
        ),
    )
    confirm_passcode = forms.CharField(
        label="Confirm new passcode",
        widget=forms.PasswordInput(
            attrs={"class": "form-control form-control-lg", "autocomplete": "new-password", "inputmode": "numeric"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get("new_passcode")
        confirm = cleaned.get("confirm_passcode")
        if new and confirm and new != confirm:
            self.add_error("confirm_passcode", "The two passcodes do not match.")
        return cleaned


class EmployeeAdminForm(forms.ModelForm):
    """Used in the admin site to add employees and reset passcodes."""

    temp_passcode = forms.CharField(
        required=False,
        label="Temporary passcode",
        validators=[validate_passcode],
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text=(
            "Required for a new employee. On an existing employee, fill it in only to reset "
            "their passcode (this also unlocks the account). The employee must choose their "
            "own passcode at next login. Leave blank to keep the current passcode."
        ),
    )

    class Meta:
        model = Employee
        fields = ["employee_id", "full_name", "role", "is_active", "is_locked"]

    def clean_employee_id(self):
        return self.cleaned_data["employee_id"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("temp_passcode"):
            self.add_error("temp_passcode", "Required when adding a new employee.")
        return cleaned

    def save(self, commit=True):
        employee = super().save(commit=False)
        temp = self.cleaned_data.get("temp_passcode")
        if temp:
            employee.set_password(temp)
            employee.must_change_passcode = True
            employee.is_locked = False
        if not employee.is_locked:
            employee.failed_attempts = 0
        if commit:
            employee.save()
        return employee