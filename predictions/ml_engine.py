"""
Orchiimmo — Moteur ML de prédiction de prix immobilier
Scope  : Tous types de biens au Maroc | Prix en MAD
Modèle : Entraîné depuis la DB Django via ml/train_from_db.py
"""
import logging
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

logger = logging.getLogger(__name__)


class OrchiimmoMLEngine:
    """
    Singleton — charge best_model.pkl une seule fois.
    Calcule les stats ville/quartier directement depuis la DB Django.
    Respecte l'ordre EXACT des features du modèle entraîné.
    """
    _instance = None

    def __init__(self, model_path: Path, data_path: Path = None):
        bundle = joblib.load(model_path)
        self.model         = bundle['pipeline']
        self.encoders      = bundle['encoders']
        self.metadata      = bundle['metadata']
        self.known_cities  = bundle.get('known_cities', [])
        self.features      = bundle['metadata'].get('features', [])
        # Stats pré-calculées depuis la DB (chargées à la première prédiction)
        self._city_stats   = None
        self._dist_stats   = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            from django.conf import settings
            cls._instance = cls(model_path=settings.ML_MODEL_PATH)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None

    # ── Encodage ─────────────────────────────────────────────────────────────

    def _encode(self, col: str, value: str) -> int:
        enc = self.encoders.get(col)
        if enc is None:
            return 0
        try:
            return int(enc.transform([str(value).strip().lower()])[0])
        except Exception:
            return 0

    # ── Stats géographiques depuis la DB ─────────────────────────────────────

    def _load_stats_from_db(self):
        """Calcule les statistiques ville/quartier depuis Property model."""
        try:
            from properties.models import Property
            qs = Property.objects.filter(
                price_mad__gte=100_000,
                price_mad__lte=50_000_000,
                area_m2__gte=10,
                price_per_m2_mad__isnull=False,
            ).values('city', 'district', 'price_mad', 'price_per_m2_mad', 'area_m2')

            df = pd.DataFrame(list(qs))
            if df.empty:
                return pd.DataFrame(), pd.DataFrame()

            df['city']     = df['city'].fillna('').str.strip().str.lower()
            df['district'] = df['district'].fillna('').str.strip().str.lower()

            # Stats par ville
            city_stats = df.groupby('city').agg(
                city_ppm2_median  = ('price_per_m2_mad', 'median'),
                city_price_median = ('price_mad', 'median'),
                city_area_median  = ('area_m2', 'median'),
                city_count        = ('price_mad', 'count'),
            ).reset_index()

            # Stats par quartier (non-vide seulement)
            df_d = df[df['district'] != '']
            if not df_d.empty:
                dist_stats = df_d.groupby(['city', 'district']).agg(
                    district_ppm2_median = ('price_per_m2_mad', 'median'),
                ).reset_index()
            else:
                dist_stats = pd.DataFrame(
                    columns=['city', 'district', 'district_ppm2_median'])

            return city_stats, dist_stats

        except Exception as e:
            logger.warning(f'[ML] Impossible de charger les stats DB: {e}')
            return pd.DataFrame(), pd.DataFrame()

    def _ensure_stats(self):
        if self._city_stats is None:
            self._city_stats, self._dist_stats = self._load_stats_from_db()

    def _lookup_city(self, city: str, col: str, fallback: float) -> float:
        self._ensure_stats()
        cs = self._city_stats
        if cs is None or cs.empty or col not in cs.columns:
            return fallback
        row = cs[cs['city'] == city.lower().strip()]
        if row.empty:
            return fallback
        val = row.iloc[0][col]
        return float(val) if not pd.isna(val) else fallback

    def _lookup_district(self, city: str, district: str, fallback: float) -> float:
        self._ensure_stats()
        ds = self._dist_stats
        if ds is None or ds.empty:
            return fallback
        row = ds[(ds['city'] == city.lower().strip()) &
                 (ds['district'] == district.lower().strip())]
        if row.empty:
            return fallback
        val = row.iloc[0].get('district_ppm2_median', np.nan)
        return float(val) if not pd.isna(val) else fallback

    # ── Prédiction ────────────────────────────────────────────────────────────

    def predict(self, city: str, area_m2: float, bedrooms: int,
                bathrooms: int, property_type: str = 'apartment',
                district: str = '') -> dict:
        """
        Prédit le prix MAD. Respecte l'ordre EXACT des features du modèle v2.0:
        city_enc, district_enc, property_type_enc, area_m2, bedrooms, bathrooms,
        city_ppm2_median, city_price_median, city_area_median,
        district_ppm2_median, city_count, ratio_surface_chambres, price_per_m2_city
        """
        city_low = city.strip().lower()
        dist_low = district.strip().lower() if district else ''
        type_low = property_type.strip().lower()

        # ── Valeurs globales de fallback ──────────────────────────────────────
        self._ensure_stats()
        cs = self._city_stats
        global_ppm2  = float(cs['city_ppm2_median'].median())  if cs is not None and not cs.empty else 12_000.0
        global_price = float(cs['city_price_median'].median()) if cs is not None and not cs.empty else 1_400_000.0
        global_area  = float(cs['city_area_median'].median())  if cs is not None and not cs.empty else 90.0
        global_count = float(cs['city_count'].median())        if cs is not None and not cs.empty else 100.0

        # ── Lookup stats ville ────────────────────────────────────────────────
        city_ppm2_median  = self._lookup_city(city_low, 'city_ppm2_median',  global_ppm2)
        city_price_median = self._lookup_city(city_low, 'city_price_median', global_price)
        city_area_median  = self._lookup_city(city_low, 'city_area_median',  global_area)
        city_count        = self._lookup_city(city_low, 'city_count',        global_count)

        # ── Lookup stats quartier ─────────────────────────────────────────────
        district_ppm2_median = (
            self._lookup_district(city_low, dist_low, None)
            if dist_low else None
        )
        if district_ppm2_median is None:
            district_ppm2_median = city_ppm2_median

        # ── Features dérivées ─────────────────────────────────────────────────
        bedrooms_safe          = max(1, bedrooms or 1)
        ratio_surface_chambres = area_m2 / bedrooms_safe
        price_per_m2_city      = city_price_median / max(1.0, city_area_median)

        # ── Vecteur de features — ORDRE EXACT du modèle v2.0 ─────────────────
        feat = pd.DataFrame([{
            'city_enc':               self._encode('city',          city_low),
            'district_enc':           self._encode('district',      dist_low),
            'property_type_enc':      self._encode('property_type', type_low),
            'area_m2':                float(area_m2),
            'bedrooms':               int(bedrooms or 0),
            'bathrooms':              int(bathrooms or 0),
            'city_ppm2_median':       city_ppm2_median,       # pos 6 ✅
            'city_price_median':      city_price_median,      # pos 7 ✅
            'city_area_median':       city_area_median,       # pos 8 ✅
            'district_ppm2_median':   district_ppm2_median,   # pos 9 ✅
            'city_count':             city_count,             # pos 10 ✅
            'ratio_surface_chambres': ratio_surface_chambres, # pos 11 ✅
            'price_per_m2_city':      price_per_m2_city,      # pos 12 ✅
        }])

        # Garantir l'ordre exact des colonnes
        if self.features:
            feat = feat[self.features]

        # ── Prédiction en log-space ────────────────────────────────────────────
        log_pred  = self.model.predict(feat)[0]
        price_mad = float(np.expm1(log_pred))

        # ── Intervalle de confiance (basé sur MAE du modèle) ─────────────────
        # La variance des arbres RF individuels est trop élevée (bruit non réduit).
        # On utilise le MAE de test — si price_pred ± 1.645×MAE contient 90%
        # des vraies valeurs sous hypothèse d'erreurs normales.
        mae = self.metadata.get('MAE', None)
        if mae and mae > 0:
            # MAE du training (en MAD) → CI 90% symétrique autour du prix
            margin = 1.645 * float(mae)
        else:
            # Fallback : ±18% (réaliste pour l'immobilier marocain)
            margin = price_mad * 0.18

        # Borne basse : jamais en-dessous de 60% du prix prédit
        low  = max(price_mad * 0.60, price_mad - margin)
        high = price_mad + margin

        comparables = self._find_comparables(city_low, type_low, area_m2)

        return {
            'price_mad':       round(price_mad),
            'confidence_low':  round(low),
            'confidence_high': round(high),
            'price_per_m2':    round(price_mad / area_m2) if area_m2 > 0 else 0,
            'model_version':   self.metadata.get('version', 'v1.0'),
            'model_r2':        self.metadata.get('R2', 0),
            'comparables':     comparables,
        }

    # ── Comparables depuis la DB ──────────────────────────────────────────────

    def _find_comparables(self, city: str, property_type: str,
                          area_m2: float, n: int = 5) -> list:
        try:
            from properties.models import Property
            qs = Property.objects.filter(
                city__iexact=city,
                area_m2__gte=area_m2 * 0.70,
                area_m2__lte=area_m2 * 1.30,
                price_mad__gt=0,
            ).order_by('price_mad')[:n]

            return [{
                'city':      p.city,
                'district':  p.district,
                'area_m2':   p.area_m2,
                'bedrooms':  p.bedrooms,
                'price_mad': p.price_mad,
                'latitude':  p.latitude,
                'longitude': p.longitude,
                'url':       p.url,
            } for p in qs]
        except Exception:
            return []

    # ── Helpers publics ───────────────────────────────────────────────────────

    def get_cities(self) -> list:
        """Liste triée des villes disponibles depuis la DB."""
        import re
        try:
            from properties.models import Property
            cities = (Property.objects
                      .values_list('city', flat=True)
                      .distinct()
                      .order_by('city'))
            valid = sorted([
                c for c in cities
                if c and len(re.sub(r'[^a-zA-ZÀ-ÿ\s\-]', '', str(c)).strip()) >= 2
                and c.lower() not in ('maroc', 'location immobilier', '')
            ])
            return valid
        except Exception:
            return [c.title() for c in self.known_cities]

    def get_districts(self, city: str = '') -> list:
        try:
            from properties.models import Property
            qs = Property.objects.values_list('district', flat=True).distinct()
            if city:
                qs = qs.filter(city__iexact=city)
            return sorted([d for d in qs if d and len(d) > 1])
        except Exception:
            return []
