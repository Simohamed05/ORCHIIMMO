from django import forms

# Villes Maroc (top 50 — chargées dynamiquement depuis le dataset si possible)
VILLES_MAROC = [
    ('Marrakech','Marrakech'), ('Casablanca','Casablanca'),
    ('Tanger','Tanger'), ('Kénitra','Kénitra'), ('Rabat','Rabat'),
    ('Agadir','Agadir'), ('Fes','Fes'), ('Meknès','Meknès'),
    ('Salé','Salé'), ('El Jadida','El Jadida'), ('Tétouan','Tétouan'),
    ('Mohammedia','Mohammedia'), ('Oujda','Oujda'), ('Nador','Nador'),
    ('Béni Mellal','Béni Mellal'), ('Dar Bouazza','Dar Bouazza'),
    ('Bouskoura','Bouskoura'), ('Hay Riad','Hay Riad'),
    ('Temara','Temara'), ('Safi','Safi'),
    ('Martil','Martil'), ('Chefchaouen','Chefchaouen'),
    ('Essaouira','Essaouira'), ('Ifrane','Ifrane'),
    ('Ain Diab','Ain Diab'), ('Racine','Racine'),
    ('Maarif','Maarif'), ('Hivernage','Hivernage'),
    ('Guéliz','Guéliz'), ('Palmeraie','Palmeraie'),
]

TYPE_CHOICES = [
    ('apartment', 'Appartement'),
    ('villa',     'Villa / Maison'),
    ('riad',      'Riad'),
    ('land',      'Terrain'),
    ('office',    'Bureau / Local'),
]

def _get_cities_choices():
    """Charge les villes depuis le dataset ML si disponible, filtrées et capitalisées."""
    try:
        import re, pandas as pd
        from django.conf import settings
        df = pd.read_csv(settings.ML_DATA_PATH)
        if 'city' in df.columns:
            cities = df['city'].dropna().unique().tolist()
            # Exclure les codes numériques et les valeurs trop courtes
            valid = sorted([
                c for c in cities
                if c and len(re.sub(r'[^a-zA-ZÀ-ÿ\s\-]', '', str(c)).strip()) >= 2
            ])
            return [(c, c.title()) for c in valid]
        return VILLES_MAROC
    except Exception:
        return VILLES_MAROC

class PredictionForm(forms.Form):
    city = forms.ChoiceField(
        label='Ville',
        choices=_get_cities_choices,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_city'})
    )
    district = forms.CharField(
        label='Quartier (optionnel)',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Guéliz, Maarif, Agdal…',
            'list': 'district-suggestions',
            'id': 'id_district',
        })
    )
    property_type = forms.ChoiceField(
        label='Type de bien',
        choices=TYPE_CHOICES,
        initial='apartment',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    area_m2 = forms.FloatField(
        label='Surface (m²)',
        min_value=15.0,
        max_value=2000.0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 85',
            'step': '5',
        })
    )
    bedrooms = forms.IntegerField(
        label='Chambres',
        min_value=0, max_value=20, initial=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '20'})
    )
    bathrooms = forms.IntegerField(
        label='Salles de bain',
        min_value=0, max_value=10, initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '10'})
    )

    def clean_area_m2(self):
        area = self.cleaned_data.get('area_m2')
        if area and area < 15:
            raise forms.ValidationError('La surface minimum est de 15 m².')
        return area
