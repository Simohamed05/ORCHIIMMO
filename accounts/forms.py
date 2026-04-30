from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
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
        self.fields['password1'].widget.attrs.update({'class':'form-control'})
        self.fields['password2'].widget.attrs.update({'class':'form-control'})

class ProfileForm(forms.ModelForm):
    class Meta:
        model  = UserProfile
        fields = ['phone','ville','bio']
        widgets = {
            'phone': forms.TextInput(attrs={'class':'form-control','placeholder':'+212 6XX XXX XXX'}),
            'ville': forms.TextInput(attrs={'class':'form-control','placeholder':'Ex: Casablanca'}),
            'bio':   forms.Textarea(attrs={'class':'form-control','rows':3}),
        }
