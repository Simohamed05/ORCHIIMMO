import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .forms import PredictionForm
from .models import Prediction
from .ml_engine import OrchiimmoMLEngine

@login_required
def predict_form(request):
    """Affiche le formulaire et traite la soumission."""
    # Vérifier rate limiting manuel (20 prédictions par heure)
    from django.utils import timezone
    from datetime import timedelta
    recent = request.user.predictions.filter(
        created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= 20:
        messages.error(request,
            'Limite atteinte : 20 estimations par heure. Réessayez dans un moment.')
        return redirect('predictions:history')

    if request.method == 'POST':
        form = PredictionForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                engine = OrchiimmoMLEngine.get_instance()
                result = engine.predict(
                    city          = data['city'],
                    area_m2       = data['area_m2'],
                    bedrooms      = data['bedrooms'],
                    bathrooms     = data['bathrooms'],
                    property_type = data['property_type'],
                    district      = data.get('district', ''),
                )
                pred = Prediction.objects.create(
                    user                = request.user,
                    city                = data['city'],
                    district            = data.get('district', ''),
                    property_type       = data['property_type'],
                    area_m2             = data['area_m2'],
                    bedrooms            = data['bedrooms'],
                    bathrooms           = data['bathrooms'],
                    predicted_price_mad = result['price_mad'],
                    confidence_low_mad  = result['confidence_low'],
                    confidence_high_mad = result['confidence_high'],
                    price_per_m2_mad    = result['price_per_m2'],
                    model_version       = result['model_version'],
                )
                return redirect('predictions:result', pk=pred.pk)
            except FileNotFoundError:
                messages.error(request,
                    'Le modèle ML n\'est pas encore entraîné. '
                    'Lancez d\'abord : python ml/train.py')
            except Exception as e:
                messages.error(request, f'Erreur de prédiction : {e}')
    else:
        form = PredictionForm()

    # Stats pour la page
    try:
        engine = OrchiimmoMLEngine.get_instance()
        meta   = engine.metadata
    except Exception:
        meta   = {'R2': 0, 'MAE': 0, 'version': '—'}

    # Dernières estimations pour la sidebar
    recent_predictions = request.user.predictions.order_by('-created_at')[:5]

    return render(request, 'predictions/form.html', {
        'form':               form,
        'model_r2':           round(meta.get('R2', 0), 3),
        'model_mae':          round(meta.get('MAE', 0) / 1000, 1),  # en milliers MAD
        'rate_limit_remaining': max(0, 20 - recent),
        'recent_predictions': recent_predictions,
    })


@login_required
def predict_result(request, pk):
    """Affiche le résultat d'une prédiction."""
    pred = get_object_or_404(Prediction, pk=pk, user=request.user)

    # Recharger les comparables depuis le moteur
    try:
        engine = OrchiimmoMLEngine.get_instance()
        comparables = engine._find_comparables(
            pred.city, pred.property_type, pred.area_m2
        )
    except Exception:
        comparables = []

    # Préparation pour la carte Leaflet (JSON)
    map_points = [
        {
            'lat': c.get('latitude', ''),
            'lng': c.get('longitude', ''),
            'prix': c.get('price_local', 0),
            'city': c.get('city', ''),
            'area': c.get('area_m2', 0),
        }
        for c in comparables
        if c.get('latitude') and c.get('longitude')
    ]

    return render(request, 'predictions/result.html', {
        'pred':             pred,
        'comparables':      comparables,
        'comparables_json': json.dumps(map_points),
    })


@login_required
def predict_history(request):
    """Historique des prédictions de l'utilisateur."""
    predictions = request.user.predictions.order_by('-created_at')
    return render(request, 'predictions/history.html', {
        'predictions': predictions,
    })


def get_districts_ajax(request):
    """API AJAX : retourne les quartiers d'une ville."""
    city = request.GET.get('city', '')
    try:
        engine = OrchiimmoMLEngine.get_instance()
        districts = engine.get_districts(city)
    except Exception:
        districts = []
    return JsonResponse({'districts': districts})
