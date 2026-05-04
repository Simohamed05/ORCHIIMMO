"""
properties/views.py
Catalogue de biens immobiliers + Scraping temps réel (SSE)
"""
import json
import logging
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import StreamingHttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Min, Max, Count
from django.views.decorators.http import require_POST

from .models import Property

logger = logging.getLogger(__name__)


# ── Villes disponibles (depuis la DB) ────────────────────────────────────────

def _get_villes():
    return (
        Property.objects
        .values_list('city', flat=True)
        .distinct()
        .order_by('city')
    )


# ── Vue : catalogue paginé ────────────────────────────────────────────────────

def property_list(request):
    """Catalogue filtrable et paginé — prix en MAD."""
    qs = Property.objects.all()

    # ─── Filtres GET ──────────────────────────────────────────────────────────
    city     = request.GET.get('city',      '').strip()
    ptype    = request.GET.get('type',      '').strip()
    p_min    = request.GET.get('price_min', '').strip()
    p_max    = request.GET.get('price_max', '').strip()
    a_min    = request.GET.get('area_min',  '').strip()
    a_max    = request.GET.get('area_max',  '').strip()
    opport   = request.GET.get('opportunity','').strip()
    sort_by  = request.GET.get('sort',      'price_mad')

    if city:
        qs = qs.filter(city__iexact=city)
    if ptype:
        qs = qs.filter(property_type=ptype)
    if p_min:
        try:
            qs = qs.filter(price_mad__gte=float(p_min))
        except ValueError:
            pass
    if p_max:
        try:
            qs = qs.filter(price_mad__lte=float(p_max))
        except ValueError:
            pass
    if a_min:
        try:
            qs = qs.filter(area_m2__gte=float(a_min))
        except ValueError:
            pass
    if a_max:
        try:
            qs = qs.filter(area_m2__lte=float(a_max))
        except ValueError:
            pass
    if opport:
        qs = qs.filter(is_opportunity=True)

    # Tri
    sort_map = {
        'price_mad':  'price_mad',
        'price_desc': '-price_mad',
        'area_m2':    '-area_m2',
        'recent':     '-scraped_at',
    }
    qs = qs.order_by(sort_map.get(sort_by, 'price_mad'))

    total = qs.count()

    # Pagination
    paginator = Paginator(qs, 20)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    # Stats rapides (MAD)
    stats = qs.aggregate(
        prix_moyen=Avg('price_mad'),
        prix_min=Min('price_mad'),
        prix_max=Max('price_mad'),
    )

    # Stats globales DB
    db_stats = {
        'total':   Property.objects.count(),
        'villes':  Property.objects.values('city').distinct().count(),
        'sources': Property.objects.values('source').distinct().count(),
    }

    # Liste des sources disponibles pour le panneau scraping
    from .scraper import SCRAPERS
    scrape_sources = [
        ('mubawab',      'Mubawab'),
        ('avito',        'Avito'),
        ('sarouty',      'Sarouty'),
        ('sekna',        'Sekna'),
        ('selectimmo',   'SelectImmo'),
        ('logiqueimmo',  'LogiqueImmo'),
        ('marocannonce', 'MarocAnnonce'),
        ('maisonmaroc',  'MaisonMaroc'),
        ('keurimmo',     'Keurimmo'),
        ('immobilier',   'Immobilier.ma'),
    ]

    return render(request, 'properties/list.html', {
        'page_obj':  page_obj,
        'total':     total,
        'villes':    _get_villes(),
        'stats':     stats,
        'db_stats':  db_stats,
        'scrape_sources': scrape_sources,
        # Filtres actifs
        'f_city':     city,
        'f_type':     ptype,
        'f_pmin':     p_min,
        'f_pmax':     p_max,
        'f_area_min': a_min,
        'f_area_max': a_max,
        'f_opport':   opport,
        'f_sort':     sort_by,
    })


# ── Vue : fiche détail ────────────────────────────────────────────────────────

def property_detail(request, pk):
    """Fiche détail d'un bien avec carte et biens similaires."""
    prop = get_object_or_404(Property, pk=pk)

    # Biens similaires : même ville, même type, ±30% surface
    similars = Property.objects.filter(
        city=prop.city,
        property_type=prop.property_type,
    ).exclude(pk=pk)
    if prop.area_m2:
        similars = similars.filter(
            area_m2__gte=prop.area_m2 * 0.70,
            area_m2__lte=prop.area_m2 * 1.30,
        )
    similars = similars[:5]

    # Données carte Leaflet
    map_data = []
    if prop.has_geo():
        map_data.append({
            'lat':   prop.latitude,
            'lng':   prop.longitude,
            'prix':  prop.price_mad,
            'label': prop.city,
            'main':  True,
        })
    for s in similars:
        if s.has_geo():
            map_data.append({
                'lat':   s.latitude,
                'lng':   s.longitude,
                'prix':  s.price_mad,
                'label': s.city,
                'main':  False,
            })

    return render(request, 'properties/detail.html', {
        'prop':          prop,
        'similars':      similars,
        'map_data_json': json.dumps(map_data),
    })


# ── Vue : Scraping temps réel (SSE) ──────────────────────────────────────────

@login_required
def scrape_stream(request):
    """
    Server-Sent Events — scrape les sites en temps réel et stream les résultats.
    GET params :
      sources   = mubawab,sarouty,avito   (défaut : tous)
      pages     = nombre de pages/site    (défaut : 3, max : 10)
      city      = filtre ville optionnel
    """
    sources_param = request.GET.get('sources',
        'mubawab,avito,sarouty,sekna,selectimmo,logiqueimmo,marocannonce,maisonmaroc,keurimmo,immobilier'
    )
    sources = [s.strip() for s in sources_param.split(',') if s.strip()]

    try:
        max_pages = min(int(request.GET.get('pages', 3)), 10)
    except (ValueError, TypeError):
        max_pages = 3

    city_filter = request.GET.get('city', '').strip()

    def event_stream():
        """Générateur SSE : yield chaque annonce au format data: {...}\n\n"""
        from .scraper import scrape_all

        yield _sse('status', {
            'msg': f'Scraping démarré : {", ".join(sources)} — {max_pages} pages/site',
            'sources': sources,
        })

        try:
            for listing in scrape_all(
                sources=sources,
                max_pages=max_pages,
                city_filter=city_filter,
            ):
                if 'error' in listing:
                    yield _sse('error', listing)
                else:
                    # Envoyer uniquement les données utiles au frontend
                    payload = {
                        'source':        listing.get('source', ''),
                        'city':          listing.get('city', ''),
                        'district':      listing.get('district', ''),
                        'property_type': listing.get('property_type', ''),
                        'title':         listing.get('title', ''),
                        'price_mad':     listing.get('price_mad', 0),
                        'price_per_m2_mad': listing.get('price_per_m2_mad'),
                        'area_m2':       listing.get('area_m2'),
                        'bedrooms':      listing.get('bedrooms'),
                        'url':           listing.get('url', ''),
                        'is_opportunity': listing.get('is_opportunity', False),
                        'is_new':        listing.get('is_new', False),
                        'id':            listing.get('id'),
                        'total_new':     listing.get('total_new', 0),
                        'total_dup':     listing.get('total_dup', 0),
                    }
                    yield _sse('listing', payload)

        except Exception as e:
            yield _sse('error', {'msg': str(e)})

        yield _sse('done', {'msg': 'Scraping terminé !'})

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream; charset=utf-8'
    )
    response['Cache-Control']   = 'no-cache'
    response['X-Accel-Buffering'] = 'no'   # nginx : désactiver le buffering
    return response


def _sse(event: str, data: dict) -> str:
    """Formate un événement SSE."""
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


# ── Vue : stats scraping (AJAX) ───────────────────────────────────────────────

def scrape_stats(request):
    """Retourne les stats actuelles de la DB en JSON."""
    stats = Property.objects.aggregate(
        total=Count('id'),
        nb_villes=Count('city', distinct=True),
        nb_sources=Count('source', distinct=True),
        prix_moyen=Avg('price_mad'),
        prix_min=Min('price_mad'),
        prix_max=Max('price_mad'),
    )
    # Répartition par source
    par_source = list(
        Property.objects
        .values('source')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    stats['par_source'] = par_source
    return JsonResponse(stats)
