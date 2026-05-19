from django.shortcuts import render

# ──────────────────────────────────────────────────────────────────────────────
# Remplacez VOTRE_REPORT_ID et VOTRE_TENANT_ID par vos valeurs Power BI Service
# Publiez le rapport via : Power BI Desktop → Accueil → Publier
# Puis : Fichier → Incorporer le rapport → Site web ou portail → copier l'URL
# ──────────────────────────────────────────────────────────────────────────────
# ── Option A : URL directe du rapport (visible si le visiteur est connecté à PBI)
POWERBI_DIRECT_URL = (
    "https://app.powerbi.com/groups/me/reports/"
    "ceb70f97-0f79-4c7f-99d8-1ef97d980817"
)

# ── Option B : Embed public (désactivé sur ce tenant — nécessite admin PBI Pro)
POWERBI_EMBED_URL = ""   # laisser vide → affiche le carousel de screenshots

# ── Pages du rapport (pour le carousel)
POWERBI_PAGES = [
    {
        'name_fr': 'Accueil',
        'name_ar': 'الرئيسية',
        'img':     'img/pbi_accueil.png',    # mettre dans static/img/
        'desc_fr': 'Vue d\'ensemble — KPIs globaux du marché immobilier marocain',
        'desc_ar': 'نظرة عامة — المؤشرات الرئيسية للسوق العقاري المغربي',
    },
    {
        'name_fr': 'Overview',
        'name_ar': 'ملخص',
        'img':     'img/pbi_overview.png',
        'desc_fr': 'Distribution des prix et types de biens par région',
        'desc_ar': 'توزيع الأسعار وأنواع العقارات حسب المنطقة',
    },
    {
        'name_fr': 'Price Drivers',
        'name_ar': 'محركات الأسعار',
        'img':     'img/pbi_price_drivers.png',
        'desc_fr': 'Facteurs qui influencent le prix au m² (surface, ville, type)',
        'desc_ar': 'العوامل المؤثرة في السعر/م² (المساحة، المدينة، النوع)',
    },
    {
        'name_fr': 'Explore',
        'name_ar': 'استكشاف',
        'img':     'img/pbi_explore.png',
        'desc_fr': 'Analyse interactive par ville et type de bien',
        'desc_ar': 'تحليل تفاعلي حسب المدينة ونوع العقار',
    },
]

# KPIs statiques issus du dataset Phase 1 (Maroc uniquement)
MAROC_KPI = {
    'total_annonces':   7_805,
    'nb_villes':        331,
    'prix_median_mad':  1_350_000,
    'surface_mediane':  85,
    'pct_opportunites': 12,
    'top_villes': [
        {'ville': 'Casablanca',  'annonces': 2_134, 'prix_median': 1_800_000},
        {'ville': 'Marrakech',   'annonces': 1_456, 'prix_median': 1_500_000},
        {'ville': 'Rabat',       'annonces':   987, 'prix_median': 1_350_000},
        {'ville': 'Tanger',      'annonces':   743, 'prix_median': 1_100_000},
        {'ville': 'Agadir',      'annonces':   612, 'prix_median':   950_000},
    ],
}


def dashboards_view(request):
    """Page principale des tableaux de bord Power BI."""
    return render(request, 'dashboards/index.html', {
        'embed_url':      POWERBI_EMBED_URL,
        'direct_url':     POWERBI_DIRECT_URL,
        'pages':          POWERBI_PAGES,
        'kpi':            MAROC_KPI,
    })
