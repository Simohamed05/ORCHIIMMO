import json
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.conf import settings
from .forms import PredictionForm
from .models import Prediction
from .ml_engine import OrchiimmoMLEngine

@login_required
def predict_form(request):
    """Affiche le formulaire et traite la soumission."""
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
                    "Le modèle ML n'est pas encore entraîné. "
                    "Lancez d'abord : python ml/train.py")
            except Exception as e:
                messages.error(request, f'Erreur de prédiction : {e}')
    else:
        form = PredictionForm()

    try:
        engine = OrchiimmoMLEngine.get_instance()
        meta   = engine.metadata
    except Exception:
        meta   = {'R2': 0, 'MAE': 0, 'version': '—'}

    recent_predictions = request.user.predictions.order_by('-created_at')[:5]

    return render(request, 'predictions/form.html', {
        'form':               form,
        'model_r2':           round(meta.get('R2', 0), 3),
        'model_mae':          round(meta.get('MAE', 0) / 1000, 1),
        'rate_limit_remaining': max(0, 20 - recent),
        'recent_predictions': recent_predictions,
    })


@login_required
def predict_result(request, pk):
    """Affiche le résultat d'une prédiction."""
    pred = get_object_or_404(Prediction, pk=pk, user=request.user)

    try:
        engine = OrchiimmoMLEngine.get_instance()
        comparables = engine._find_comparables(
            pred.city, pred.property_type, pred.area_m2
        )
    except Exception:
        comparables = []

    map_points = [
        {
            'lat':      c.get('latitude', ''),
            'lng':      c.get('longitude', ''),
            'prix':     c.get('price_local', 0),
            'city':     c.get('city', ''),
            'area':     c.get('area_m2', 0),
            'price_mad': c.get('price_mad', 0),
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


@login_required
def ml_metrics_view(request):
    """Page des métriques du modèle ML — comparaison des 4 modèles."""
    import json as json_lib
    metrics_path = settings.BASE_DIR / 'ml' / 'models' / 'model_metrics.json'
    fi_path      = settings.BASE_DIR / 'ml' / 'models' / 'feature_importance.csv'

    metrics = {}
    if metrics_path.exists():
        with open(metrics_path, 'r', encoding='utf-8') as f:
            metrics = json_lib.load(f)

    # Trouver le meilleur modèle par R²
    best_model = max(metrics, key=lambda m: metrics[m].get('R2', 0)) if metrics else '—'

    # Feature importance
    fi_data = []
    if fi_path.exists():
        import csv
        with open(fi_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fi_data = list(reader)[:10]  # Top 10

    # Métadonnées du modèle chargé
    try:
        engine = OrchiimmoMLEngine.get_instance()
        meta = engine.metadata
    except Exception:
        meta = {}

    return render(request, 'predictions/metrics.html', {
        'metrics':    metrics,
        'best_model': best_model,
        'fi_data':    fi_data,
        'meta':       meta,
    })
