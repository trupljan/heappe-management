from django import forms
from .models import InstanceCredentials


class InstanceCredentialsForm(forms.ModelForm):
    class Meta:
        model = InstanceCredentials
        fields = [
            'instance_name', 'heappe_host', 'heappe_login', 'heappe_password', 'heappe_port',
            'log_db_host', 'log_db_port', 'log_db_user', 'log_db_password', 'log_db_database', 'is_deployed'
        ]
        widgets = {
            'heappe_password': forms.PasswordInput(render_value=True),
            'log_db_password': forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        optional_fields = [
            'log_db_host',
            'log_db_port',
            'log_db_user',
            'log_db_password',
            'log_db_database'
        ]

        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
            if field_name in optional_fields:
                field.required = False

        self.fields['heappe_password'].required = False