import re
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import UserProfile

class RegisterForm(UserCreationForm):
    email      = forms.EmailField(required=True,
                    widget=forms.EmailInput(attrs={'class':'form-control','placeholder':'email@exemple.com'}))
    first_name = forms.CharField(max_length=50, required=True,
                    widget=forms.TextInput(attrs={'class':'form-control','placeholder':'Prénom'}))
    last_name  = forms.CharField(max_length=50, required=True,
                    widget=forms.TextInput(attrs={'class':'form-control','placeholder':'Nom'}))

    class Meta:
        model  = User
        fields = ['username','first_name','last_name','email','password1','password2']
        widgets = {
            'username': forms.TextInput(attrs={'class':'form-control','placeholder':'Nom d\'utilisateur'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'form-control', 'id': 'id_password1'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control', 'id': 'id_password2'})

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')

        errors = []

        if password1 and password2 and password1 != password2:
            errors.append("Les deux mots de passe ne correspondent pas.")

        if password2:
            if len(password2) < 8:
                errors.append("Au moins 8 caractères.")
            if not re.search(r'[A-Z]', password2):
                errors.append("Au moins 1 lettre majuscule (A-Z).")
            if not re.search(r'[a-z]', password2):
                errors.append("Au moins 1 lettre minuscule (a-z).")
            if not re.search(r'\d', password2):
                errors.append("Au moins 1 chiffre (0-9).")
            if not re.search(r'[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]', password2):
                errors.append("Au moins 1 caractère spécial (!@#$%...).")

        if errors:
            raise ValidationError(errors)

        return password2

class ProfileForm(forms.ModelForm):
    class Meta:
        model  = UserProfile
        fields = ['phone','ville','bio']
        widgets = {
            'phone': forms.TextInput(attrs={'class':'form-control','placeholder':'+212 6XX XXX XXX'}),
            'ville': forms.TextInput(attrs={'class':'form-control','placeholder':'Ex: Casablanca'}),
            'bio':   forms.Textarea(attrs={'class':'form-control','rows':3}),
        }
