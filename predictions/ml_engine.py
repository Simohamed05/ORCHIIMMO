"""
Orchiimmo — Moteur ML de prédiction de prix immobilier
Scope  : Appartements au Maroc | Prix en MAD
Modèle : Entraîné from scratch via ml/train.py
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path


class OrchiimmoMLEngine:
    """
    Singleton — charge best_model.pkl une seule fois.
    Prédit le prix en MAD avec les features exactes du training.
    """
    _instance = None

    def __init__(self, model_path: Path, data_path: Path):
        bundle = joblib.load(model_path)
        self.model         = bundle['pipeline']           # modèle sklearn
        self.encoders      = bundle['encoders']           # dict LabelEncoders
        self.metadata      = bundle['metadata']           # version, R², MAE…
        self.known_cities  = bundle.get('known_cities', [])
        self.features      = bundle['metadata'].get('features', [])  # liste ordonnée
        self.data_path     = data_path
        self._df_cache     = None
        # Pré-calculer les stats par ville/quartier depuis le dataset
        self._city_stats   = None
        self._dist_stats   = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            from django.conf import settings
            cls._instance = cls(
                model_path=settings.ML_MODEL_PATH,
                data_path=settings.ML_DATA_PATH,
            )
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Force le rechargement du modèle (utile après re-training)."""
        cls._instance = None

    # ── Encodage ─────────────────────────────────────────────────────────────

    def _encode(self, col: str, value: str) -> int:
        """Encode une valeur avec le LabelEncoder correspondant. Retourne 0 si inconnue."""
        enc = self.encoders.get(col)
        if enc is None:
            return 0
        try:
            return int(enc.transform([str(value).strip().lower()])[0])
        except Exception:
            return 0

    # ── Stats géographiques (cache) ───────────────────────────────────────────

    def _get_df(self) -> pd.DataFrame:
        if self._df_cache is None:
            try:
                self._df_cache = pd.read_csv(self.data_path)
            except Exception:
                self._df_cache = pd.DataFrame()
        return self._df_cache

    def _get_city_stats(self) -> pd.DataFrame:
        """Retourne un DataFrame avec les stats (médiane) par ville."""
        if self._city_stats is None:
            df = self._get_df()
            if df.empty:
                self._city_stats = pd.DataFrame()
            else:
                stat_cols = ['city_price_median', 'city_ppm2_median',
                             'city_area_median', 'city_count']
                existing  = [c for c in stat_cols if c in df.columns]
                if 'city' in df.columns and existing:
                    self._city_stats = (
                        df.groupby('city')[existing].median().reset_index()
                    )
                else:
                    self._city_stats = pd.DataFrame()
        return self._city_stats

    def _get_dist_stats(self) -> pd.DataFrame:
        """Retourne un DataFrame avec les stats (médiane) par quartier."""
        if self._dist_stats is None:
            df = self._get_df()
            if df.empty or 'district' not in df.columns:
                self._dist_stats = pd.DataFrame()
            elif 'district_ppm2_median' in df.columns:
                self._dist_stats = (
                    df.groupby('district')['district_ppm2_median']
                    .median().reset_index()
                )
            else:
                self._dist_stats = pd.DataFrame()
        return self._dist_stats

    def _lookup_city_stat(self, city: str, col: str, fallback=None):
        """Recherche la valeur d'une stat pour une ville donnée."""
        cs = self._get_city_stats()
        if cs.empty or col not in cs.columns:
            return fallback
        row = cs[cs['city'] == city.lower().strip()]
        if row.empty:
            # Essayer sans normalisation
            row = cs[cs['city'] == city]
        if row.empty:
            return fallback
        val = row.iloc[0][col]
        return float(val) if not pd.isna(val) else fallback

    def _lookup_dist_stat(self, district: str, fallback=None):
        """Recherche district_ppm2_median pour un quartier donné."""
        ds = self._get_dist_stats()
        if ds.empty or 'district_ppm2_median' not in ds.columns:
            return fallback
        row = ds[ds['district'] == district.lower().strip()]
        if row.empty:
            return fallback
        val = row.iloc[0]['district_ppm2_median']
        return float(val) if not pd.isna(val) else fallback

    # ── Prédiction ────────────────────────────────────────────────────────────

    def predict(self, city: str, area_m2: float, bedrooms: int,
                bathrooms: int, property_type: str = 'apartment',
                district: str = '') -> dict:
        """
        Prédit le prix MAD d'un appartement marocain.
        Construit exactement les mêmes features que ml/train.py.
        """
        city_low = city.strip().lower()
        dist_low = district.strip().lower() if district else ''
        type_low = property_type.strip().lower()

        # ── Valeurs par défaut (médiane globale du dataset) ──────────────────
        df = self._get_df()
        global_city_price   = float(df['city_price_median'].median())  if not df.empty and 'city_price_median'  in df.columns else 1_285_000.0
        global_city_ppm2    = float(df['city_ppm2_median'].median())   if not df.empty and 'city_ppm2_median'   in df.columns else 12_153.0
        global_city_area    = float(df['city_area_median'].median())   if not df.empty and 'city_area_median'   in df.columns else 89.0
        global_dist_ppm2    = float(df['district_ppm2_median'].median()) if not df.empty and 'district_ppm2_median' in df.columns else 12_144.0
        global_city_count   = float(df['city_count'].median())         if not df.empty and 'city_count'         in df.columns else 352.0

        # ── Lookup stats ville ────────────────────────────────────────────────
        city_price_median    = self._lookup_city_stat(city_low, 'city_price_median',    global_city_price)
        city_ppm2_median     = self._lookup_city_stat(city_low, 'city_ppm2_median',     global_city_ppm2)
        city_area_median     = self._lookup_city_stat(city_low, 'city_area_median',     global_city_area)
        city_count           = self._lookup_city_stat(city_low, 'city_count',           global_city_count)

        # ── Lookup stats quartier ─────────────────────────────────────────────
        district_ppm2_median = (
            self._lookup_dist_stat(dist_low, None)
            if dist_low else None
        )
        if district_ppm2_median is None:
            district_ppm2_median = city_ppm2_median  # fallback = ville

        # ── Features dérivées ─────────────────────────────────────────────────
        bedrooms_safe          = max(1, bedrooms)
        ratio_surface_chambres = area_m2 / bedrooms_safe
        price_per_m2_city      = city_price_median / max(1, city_area_median)

        # ── Vecteur de features (ordre exact = training) ──────────────────────
        feat = pd.DataFrame([{
            'city_enc':             self._encode('city',          city_low),
            'district_enc':         self._encode('district',      dist_low),
            'property_type_enc':    self._encode('property_type', type_low),
            'area_m2':              float(area_m2),
            'bedrooms':             int(bedrooms),
            'bathrooms':            int(bathrooms),
            'city_price_median':    city_price_median,
            'city_ppm2_median':     city_ppm2_median,
            'city_area_median':     city_area_median,
            'district_ppm2_median': district_ppm2_median,
            'city_count':           city_count,
            'ratio_surface_chambres': ratio_surface_chambres,
            'price_per_m2_city':    price_per_m2_city,
        }])

        # ── Prédiction en log-space ────────────────────────────────────────────
        log_pred  = self.model.predict(feat)[0]
        price_mad = float(np.expm1(log_pred))

        # ── Intervalle de confiance ────────────────────────────────────────────
        try:
            # RandomForest : std sur les arbres individuels → CI 90% (z=1.645)
            est    = self.model.estimators_
            preds  = np.array([np.expm1(t.predict(feat)[0]) for t in est])
            std    = preds.std()
            low    = max(0.0, price_mad - 1.645 * std)
            high   = price_mad + 1.645 * std
        except AttributeError:
            # LightGBM / XGBoost : fallback ±20%
            low  = price_mad * 0.80
            high = price_mad * 1.20

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

    # ── Comparables ───────────────────────────────────────────────────────────

    def _find_comparables(self, city: str, property_type: str,
                          area_m2: float, n: int = 5) -> list:
        df = self._get_df()
        if df.empty:
            return []
        try:
            # Colonnes prix acceptées
            price_col = next(
                (c for c in ('price_mad', 'price_local', 'price_eur') if c in df.columns),
                None
            )
            if price_col is None:
                return []

            city_col = city.strip().lower()
            mask = (
                (df['city'].str.lower().str.strip() == city_col) &
                (df['area_m2'].between(area_m2 * 0.70, area_m2 * 1.30)) &
                (df[price_col].notna())
            )
            comps = df[mask].nsmallest(n, price_col)
            result = []
            for _, row in comps.iterrows():
                result.append({
                    'city':      row.get('city', ''),
                    'district':  row.get('district', ''),
                    'area_m2':   row.get('area_m2', ''),
                    'bedrooms':  row.get('bedrooms', ''),
                    'price_mad': row.get(price_col, 0),
                    'latitude':  row.get('latitude', None),
                    'longitude': row.get('longitude', None),
                    'url':       row.get('url', ''),
                })
            return result
        except Exception:
            return []

    # ── Helpers publics ───────────────────────────────────────────────────────

    def get_cities(self) -> list:
        """Liste triée des villes disponibles (noms valides uniquement)."""
        import re
        df = self._get_df()
        if not df.empty and 'city' in df.columns:
            cities = df['city'].dropna().unique().tolist()
            # Exclure les valeurs numériques / codes invalides
            valid = sorted([
                c for c in cities
                if c and len(re.sub(r'[^a-zA-ZÀ-ÿ\s\-]', '', str(c)).strip()) >= 2
            ])
            return [c.title() for c in valid]
        return list(self.known_cities)

    def get_districts(self, city: str = '') -> list:
        df = self._get_df()
        if df.empty or 'district' not in df.columns:
            return []
        sub = df[df['city'].str.lower() == city.lower()] if city else df
        districts = sorted(sub['district'].dropna().unique().tolist())
        return [d.title() for d in districts if d and len(d) > 1]
