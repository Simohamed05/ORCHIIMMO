"""
ml/train_from_db.py — Réentraînement ML depuis les données scrapées (Django DB)
=================================================================================
Source  : PostgreSQL via Django ORM (Property model)
Cible   : Tous types de biens au Maroc (price_mad en DH)
Modèles : RandomForest + LightGBM (si installé)
Sortie  : ml/models/best_model.pkl  +  model_metrics.json  +  feature_importance.csv

Usage :
    cd Phase2_Django
    python ml/train_from_db.py
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# ── Setup Django ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

# ── Imports ML ────────────────────────────────────────────────────────────────
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

try:
    import lightgbm as lgb
    HAS_LGB = True
    print("[INFO] LightGBM disponible ✅")
except ImportError:
    HAS_LGB = False
    print("[INFO] LightGBM non installé — RandomForest seulement")

OUTPUT_DIR = Path(__file__).resolve().parent / 'models'
OUTPUT_DIR.mkdir(exist_ok=True)

PRIX_MIN = 100_000     # MAD
PRIX_MAX = 50_000_000  # MAD
AREA_MIN = 10          # m²
AREA_MAX = 2_000       # m²

VILLES_EXCLURE = {'maroc', 'location immobilier', ''}


# ─────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT DEPUIS LA DB
# ─────────────────────────────────────────────────────────────────────────────
def load_from_db() -> pd.DataFrame:
    from properties.models import Property

    print("\n[1/5] Chargement depuis la base de données Django…")
    qs = Property.objects.filter(
        price_mad__gte=PRIX_MIN,
        price_mad__lte=PRIX_MAX,
        area_m2__gte=AREA_MIN,
        area_m2__lte=AREA_MAX,
    ).exclude(
        city__iexact='Maroc'
    ).exclude(
        city__icontains='Location'
    ).values(
        'city', 'district', 'property_type',
        'price_mad', 'price_per_m2_mad',
        'area_m2', 'bedrooms', 'bathrooms',
    )

    df = pd.DataFrame(list(qs))
    print(f"      Annonces chargées : {len(df):,}")

    if len(df) < 200:
        print("ERREUR : pas assez de données (< 200). Lancez d'abord le scraping.")
        sys.exit(1)

    # Nettoyage de base
    for col in ['price_mad', 'area_m2', 'bedrooms', 'bathrooms', 'price_per_m2_mad']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['city']          = df['city'].fillna('inconnu').astype(str).str.strip().str.lower()
    df['district']      = df['district'].fillna('').astype(str).str.strip().str.lower()
    df['property_type'] = df['property_type'].fillna('apartment').astype(str).str.strip().str.lower()

    # Calculer price_per_m2_mad si absent
    mask = df['price_per_m2_mad'].isna() & df['area_m2'].gt(0)
    df.loc[mask, 'price_per_m2_mad'] = df.loc[mask, 'price_mad'] / df.loc[mask, 'area_m2']

    print(f"      Types de biens : {df['property_type'].value_counts().to_dict()}")
    print(f"      Top 5 villes   : {df['city'].value_counts().head(5).to_dict()}")
    print(f"      Prix médian    : {df['price_mad'].median():,.0f} DH")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2. NETTOYAGE OUTLIERS (IQR par type)
# ─────────────────────────────────────────────────────────────────────────────
def remove_outliers(df: pd.DataFrame) -> pd.DataFrame:
    print("\n[2/5] Suppression des outliers (IQR par type de bien)…")
    before = len(df)
    cleaned = []

    for ptype, group in df.groupby('property_type'):
        q1 = group['price_mad'].quantile(0.05)
        q3 = group['price_mad'].quantile(0.95)
        mask = (group['price_mad'] >= q1) & (group['price_mad'] <= q3)
        cleaned.append(group[mask])
        removed = (~mask).sum()
        if removed > 0:
            print(f"      [{ptype}] {removed} outliers supprimés (Q5={q1:,.0f} — Q95={q3:,.0f} DH)")

    df = pd.concat(cleaned, ignore_index=True)
    print(f"      {before:,} → {len(df):,} annonces ({before - len(df)} supprimées)")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3. FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────────────────────
def prepare_features(df: pd.DataFrame):
    print("\n[3/5] Feature engineering…")

    # ── Statistiques par ville ─────────────────────────────────────────────
    city_stats = df.groupby('city').agg(
        city_ppm2_median   = ('price_per_m2_mad', 'median'),
        city_price_median  = ('price_mad', 'median'),
        city_area_median   = ('area_m2', 'median'),
        city_count         = ('price_mad', 'count'),
    ).reset_index()

    # ── Statistiques par quartier ──────────────────────────────────────────
    district_stats = df[df['district'] != ''].groupby(['city', 'district']).agg(
        district_ppm2_median = ('price_per_m2_mad', 'median'),
    ).reset_index()

    # ── Merge ──────────────────────────────────────────────────────────────
    df = df.merge(city_stats, on='city', how='left')
    df = df.merge(district_stats, on=['city', 'district'], how='left')

    # Remplir district_ppm2_median par la médiane de la ville si inconnu
    df['district_ppm2_median'] = df['district_ppm2_median'].fillna(df['city_ppm2_median'])

    # ── Features dérivées ─────────────────────────────────────────────────
    df['ratio_surface_chambres'] = df['area_m2'] / df['bedrooms'].clip(lower=1).fillna(1)
    df['price_per_m2_city']      = df['city_ppm2_median']

    # ── Imputation numérique ───────────────────────────────────────────────
    NUM_FEATURES = [
        'area_m2', 'bedrooms', 'bathrooms',
        'city_ppm2_median', 'city_price_median', 'city_area_median',
        'district_ppm2_median', 'city_count',
        'ratio_surface_chambres', 'price_per_m2_city',
    ]
    for col in NUM_FEATURES:
        median = df[col].median()
        df[col] = df[col].fillna(median)

    # ── Encodage catégoriel ────────────────────────────────────────────────
    CATEGORICAL = ['city', 'district', 'property_type']
    encoders = {}
    for col in CATEGORICAL:
        le = LabelEncoder()
        df[col + '_enc'] = le.fit_transform(df[col].fillna('inconnu'))
        encoders[col] = le
        print(f"      {col} : {len(le.classes_)} modalités")

    FEATURES = [c + '_enc' for c in CATEGORICAL] + NUM_FEATURES
    X = df[FEATURES].copy()
    y = np.log1p(df['price_mad'])  # log-transformation

    print(f"\n      Features totales : {len(FEATURES)}")
    print(f"      Observations    : {len(y):,}")
    print(f"      price_mad médiane : {df['price_mad'].median():,.0f} DH")

    return X, y, encoders, FEATURES


# ─────────────────────────────────────────────────────────────────────────────
# 4. ENTRAÎNEMENT & ÉVALUATION
# ─────────────────────────────────────────────────────────────────────────────
def train_and_evaluate(X_train, X_test, y_train, y_test) -> dict:
    print("\n[4/5] Entraînement des modèles…")
    models = {}
    results = {}

    # RandomForest
    models['RandomForest'] = RandomForestRegressor(
        n_estimators=500,
        max_depth=None,
        min_samples_leaf=2,
        max_features='sqrt',
        n_jobs=-1,
        random_state=42,
    )

    # LightGBM
    if HAS_LGB:
        models['LightGBM'] = lgb.LGBMRegressor(
            n_estimators=800,
            learning_rate=0.03,
            num_leaves=63,
            min_child_samples=10,
            n_jobs=-1,
            random_state=42,
            verbose=-1,
        )

    for name, model in models.items():
        print(f"\n  [{name}] Entraînement sur {len(X_train):,} observations…")
        model.fit(X_train, y_train)

        y_pred_log = model.predict(X_test)
        y_pred     = np.expm1(y_pred_log)
        y_true     = np.expm1(y_test)

        r2   = r2_score(y_true, y_pred)
        mae  = mean_absolute_error(y_true, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        mape = float(np.mean(np.abs((y_true - y_pred) / (y_true + 1e-8))) * 100)

        results[name] = {
            'R2':   round(r2, 4),
            'MAE':  round(mae, 0),
            'RMSE': round(rmse, 0),
            'MAPE': round(mape, 2),
        }
        print(f"  R² = {r2:.4f}  |  MAE = {mae:,.0f} DH  |"
              f"  RMSE = {rmse:,.0f} DH  |  MAPE = {mape:.1f}%")

    return models, results


# ─────────────────────────────────────────────────────────────────────────────
# 5. SAUVEGARDE
# ─────────────────────────────────────────────────────────────────────────────
def save_artifacts(best_name, best_model, encoders, features, results, n_train, n_test):
    print(f"\n[5/5] Sauvegarde : {best_name}")

    bundle = {
        'pipeline':    best_model,
        'encoders':    encoders,
        'metadata': {
            'version':    'v2.0',
            'date':       datetime.now().strftime('%Y-%m-%d'),
            'model_name': best_name,
            'devise':     'MAD',
            'source':     'Django DB (scraped data)',
            **results[best_name],
            'n_train':  n_train,
            'n_test':   n_test,
            'features': features,
            'target':   'price_mad',
        },
        'known_cities':    encoders['city'].classes_.tolist(),
        'known_types':     encoders['property_type'].classes_.tolist(),
        'known_districts': encoders['district'].classes_.tolist(),
    }

    model_path = OUTPUT_DIR / 'best_model.pkl'
    joblib.dump(bundle, model_path)
    print(f"      Modèle sauvegardé : {model_path}")

    metrics_path = OUTPUT_DIR / 'model_metrics.json'
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"      Métriques        : {metrics_path}")

    if hasattr(best_model, 'feature_importances_'):
        fi = pd.DataFrame({
            'feature':    features,
            'importance': best_model.feature_importances_,
        }).sort_values('importance', ascending=False)
        fi.to_csv(OUTPUT_DIR / 'feature_importance.csv', index=False)
        print("\n  Top 8 features :")
        for _, row in fi.head(8).iterrows():
            bar = '█' * int(row['importance'] * 50)
            print(f"    {row['feature']:<30} {bar} {row['importance']:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("  ORCHIIMMO — Réentraînement ML depuis la DB (v2.0)")
    print("=" * 62)

    df = load_from_db()
    df = remove_outliers(df)
    X, y, encoders, features = prepare_features(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )
    print(f"\n  Train : {len(X_train):,} | Test : {len(X_test):,}")

    models, results = train_and_evaluate(X_train, X_test, y_train, y_test)

    best_name = max(results, key=lambda n: results[n]['R2'])
    best_model = models[best_name]
    print(f"\n  → Meilleur modèle : {best_name} (R² = {results[best_name]['R2']:.4f})")

    if results[best_name]['R2'] < 0.40:
        print(f"\n  ⚠️  R² = {results[best_name]['R2']:.4f} — "
              f"ajoutez plus de données ou scraping supplémentaire.")

    save_artifacts(best_name, best_model, encoders, features,
                   results, len(X_train), len(X_test))

    print("\n  Résumé :")
    print(f"  {'Modèle':<15} {'R²':>8} {'MAE (DH)':>14} {'MAPE':>8}")
    print("  " + "-" * 48)
    for name, m in results.items():
        star = " ★" if name == best_name else ""
        print(f"  {name:<15} {m['R2']:>8.4f} {m['MAE']:>14,.0f} {m['MAPE']:>7.1f}%{star}")

    print("\n  ✅ Entraînement terminé !")
    print(f"  Relancez Django pour charger le nouveau modèle.")
    print("=" * 62)


if __name__ == '__main__':
    main()
