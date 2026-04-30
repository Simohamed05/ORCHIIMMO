"""
ml/train.py — Pipeline ML Orchiimmo (from scratch)
====================================================
Cible   : Appartements en vente au MAROC uniquement
Devise   : MAD (Dirham marocain — colonne price_local)
Modèles  : RandomForest, LightGBM, XGBoost, CatBoost (comparés)
Sortie   : ml/models/best_model.pkl + model_metrics.json + feature_importance.csv

Usage :
    python ml/train.py
    python ml/train.py --data /chemin/vers/fichier.csv
    python ml/train.py --model rf          (forcer RandomForest)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder

# ── Imports optionnels des boosters ──────────────────────────────────────────
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    print("[INFO] LightGBM non installé — ignoré.")

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("[INFO] XGBoost non installé — ignoré.")

try:
    from catboost import CatBoostRegressor
    HAS_CAT = True
except ImportError:
    HAS_CAT = False
    print("[INFO] CatBoost non installé — ignoré.")

# ── Chemins ──────────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = Path(__file__).resolve().parent / 'data'
OUTPUT_DIR = Path(__file__).resolve().parent / 'models'
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CSV = ROOT_DIR.parent / 'Phase1_BI' / 'orchiimmo_master_enriched_FR.csv'

# ── Constantes ───────────────────────────────────────────────────────────────
EUR_TO_MAD  = 10.80
PRIX_MIN    = 100_000    # MAD
PRIX_MAX    = 50_000_000 # MAD


# ─────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT & FILTRAGE
# ─────────────────────────────────────────────────────────────────────────────
def load_and_filter(csv_path: Path) -> pd.DataFrame:
    print(f"\n[1/5] Lecture : {csv_path}")
    try:
        df = pd.read_csv(csv_path, sep=';', decimal=',', low_memory=False)
    except FileNotFoundError:
        print(f"ERREUR : fichier introuvable — {csv_path}")
        sys.exit(1)

    print(f"      Dataset complet : {len(df):,} lignes")

    # Filtre Maroc uniquement
    df = df[df['country'] == 'MA'].copy()
    print(f"      Après filtre Maroc (MA) : {len(df):,} lignes")

    # Construire la colonne price_mad
    def to_float(series):
        return pd.to_numeric(series, errors='coerce')

    df['price_local'] = to_float(df.get('price_local'))
    df['price_eur']   = to_float(df.get('price_eur'))

    # price_local d'abord, sinon price_eur * taux
    df['price_mad'] = df['price_local'].where(
        df['price_local'].notna() & (df['price_local'] > 0),
        df['price_eur'] * EUR_TO_MAD
    )

    # Normaliser property_type et transaction_type
    df['property_type'] = df['property_type'].fillna('').str.lower().str.strip()
    df['transaction_type'] = (
        df['transaction_type'].str.lower().str.strip()
        if 'transaction_type' in df.columns
        else pd.Series(['sale'] * len(df), index=df.index)
    )

    # Valeurs réelles dans le CSV : 'apartment' (EN) et 'sale' (EN)
    TYPES_APPART = {'apartment', 'appartement', 'appart', 'flat'}
    TYPES_VENTE  = {'sale', 'vente', 'sell', ''}

    df['area_m2'] = pd.to_numeric(df['area_m2'], errors='coerce')

    # Nettoyer les villes : exclure les valeurs numériques / codes invalides
    df['city'] = df['city'].fillna('').astype(str).str.strip()
    city_valid = df['city'].str.replace(r'[^a-zA-ZÀ-ÿ\s\-]', '', regex=True).str.strip()
    df = df[city_valid.str.len() >= 2].copy()

    mask = (
        (df['property_type'].isin(TYPES_APPART)) &
        (df['transaction_type'].isin(TYPES_VENTE)) &
        (df['price_mad'].notna()) &
        (df['price_mad'] >= PRIX_MIN) &
        (df['price_mad'] <= PRIX_MAX) &
        (df['area_m2'].notna()) &
        (df['area_m2'] > 0)
    )
    df = df[mask].copy()
    print(f"      Après filtre apparts vente Maroc + prix valide : {len(df):,} lignes")

    if len(df) < 100:
        print("AVERTISSEMENT : moins de 100 lignes — vérifiez le CSV et les colonnes.")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2. PRÉPARATION DES FEATURES
# ─────────────────────────────────────────────────────────────────────────────
CATEGORICAL = ['city', 'district', 'property_type']

# Features enrichies Phase 1 BI (médiane prix par ville/quartier, etc.)
NUMERIC_ENRICHED = [
    'area_m2', 'bedrooms', 'bathrooms',
    'city_price_median',       # Prix médian de la ville (converti en MAD)
    'city_ppm2_median',        # Prix/m² médian de la ville (en MAD)
    'city_area_median',        # Surface médiane de la ville
    'district_ppm2_median',    # Prix/m² médian du quartier (en MAD)
    'city_count',              # Nombre d'annonces dans la ville
    'ratio_surface_chambres',  # Surface / Chambres
    'price_per_m2_city',       # Prix médian / surface médiane par ville
]
TARGET = 'price_mad'


def prepare_features(df: pd.DataFrame):
    print("\n[2/5] Préparation des features…")

    # Nettoyage numérique
    all_numeric = NUMERIC_ENRICHED + [TARGET]
    for col in all_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Convertir les features EUR → MAD (city_price_median, ppm2 sont en EUR dans le CSV)
    EUR_COLS = ['city_price_median', 'city_price_mean', 'city_ppm2_median',
                'city_ppm2_mean', 'city_ppm2_std', 'district_ppm2_median']
    for col in EUR_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce') * EUR_TO_MAD

    # Feature engineering
    df['price_per_m2_city'] = df['city_price_median'] / df['city_area_median'].replace(0, np.nan)
    df['ratio_surface_chambres'] = df['area_m2'] / df['bedrooms'].replace(0, np.nan)

    # Imputation numérique par médiane
    for col in NUMERIC_ENRICHED:
        if col not in df.columns:
            df[col] = np.nan
        median = df[col].median()
        if pd.isna(median):
            median = 0
        df[col] = df[col].fillna(median)
        print(f"      {col} : médiane = {median:,.1f}")

    # Nettoyage texte catégoriel
    for col in CATEGORICAL:
        if col not in df.columns:
            df[col] = 'inconnu'
        df[col] = df[col].fillna('inconnu').astype(str).str.strip().str.lower()

    # Encodage LabelEncoder
    encoders = {}
    for col in CATEGORICAL:
        le = LabelEncoder()
        df[col + '_enc'] = le.fit_transform(df[col])
        encoders[col] = le
        print(f"      {col} : {len(le.classes_)} modalités encodées")

    FEATURES = [c + '_enc' for c in CATEGORICAL] + NUMERIC_ENRICHED
    X = df[FEATURES].copy()
    y = np.log1p(df[TARGET])   # log-transformation → réduit asymétrie

    print(f"\n      Features ({len(FEATURES)}) : {FEATURES}")
    print(f"      Target   : log1p(price_mad) — {len(y):,} observations")
    print(f"      price_mad médiane : {df[TARGET].median():,.0f} DH")

    # Sauvegarder le dataset ML filtré
    ml_csv = DATA_DIR / 'apparts_maroc_ml.csv'
    save_cols = FEATURES + [TARGET, 'city', 'district', 'area_m2',
                            'bedrooms', 'bathrooms', 'price_mad', 'latitude', 'longitude', 'url']
    save_cols = [c for c in save_cols if c in df.columns]
    df[save_cols].to_csv(ml_csv, index=False)
    print(f"      Dataset ML sauvegardé : {ml_csv}")

    return X, y, encoders, FEATURES


# ─────────────────────────────────────────────────────────────────────────────
# 3. DÉFINITION DES MODÈLES
# ─────────────────────────────────────────────────────────────────────────────
def build_models(force_model: str = None) -> dict:
    models = {}

    if force_model is None or force_model == 'rf':
        models['RandomForest'] = RandomForestRegressor(
            n_estimators=300,
            max_depth=None,
            min_samples_leaf=2,
            n_jobs=-1,
            random_state=42,
        )

    if HAS_LGB and (force_model is None or force_model == 'lgb'):
        models['LightGBM'] = lgb.LGBMRegressor(
            n_estimators=500,
            learning_rate=0.05,
            num_leaves=31,
            n_jobs=-1,
            random_state=42,
            verbose=-1,
        )

    if HAS_XGB and (force_model is None or force_model == 'xgb'):
        models['XGBoost'] = xgb.XGBRegressor(
            n_estimators=500,
            learning_rate=0.05,
            max_depth=6,
            n_jobs=-1,
            random_state=42,
            verbosity=0,
        )

    if HAS_CAT and (force_model is None or force_model == 'cat'):
        models['CatBoost'] = CatBoostRegressor(
            iterations=500,
            learning_rate=0.05,
            depth=6,
            random_state=42,
            verbose=0,
        )

    if not models:
        print("ERREUR : aucun modèle disponible. Installez au moins scikit-learn.")
        sys.exit(1)

    return models


# ─────────────────────────────────────────────────────────────────────────────
# 4. ENTRAÎNEMENT & ÉVALUATION
# ─────────────────────────────────────────────────────────────────────────────
def train_and_evaluate(models: dict, X_train, X_test, y_train, y_test) -> dict:
    print("\n[3/5] Entraînement et évaluation des modèles…")
    results = {}

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
            'R2':   round(r2,   4),
            'MAE':  round(mae,  0),
            'RMSE': round(rmse, 0),
            'MAPE': round(mape, 2),
        }
        print(f"  R² = {r2:.4f}  |  MAE = {mae:,.0f} DH  |"
              f"  RMSE = {rmse:,.0f} DH  |  MAPE = {mape:.1f}%")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. SAUVEGARDE
# ─────────────────────────────────────────────────────────────────────────────
def save_artifacts(best_name: str, best_model, encoders, features: list,
                   results: dict, n_train: int, n_test: int):
    print(f"\n[4/5] Sauvegarde du modèle : {best_name}")

    bundle = {
        'pipeline':      best_model,   # modèle sklearn entraîné
        'encoders':      encoders,     # dict LabelEncoder par colonne
        'metadata': {
            'version':    'v1.0',
            'date':       datetime.now().strftime('%Y-%m-%d'),
            'model_name': best_name,
            'devise':     'MAD',
            'pays':       'Maroc (MA)',
            'scope':      'Appartements vente Maroc',
            **results[best_name],
            'n_train':    n_train,
            'n_test':     n_test,
            'features':   features,
            'target':     TARGET,
        },
        'known_cities':  encoders['city'].classes_.tolist(),
        'known_types':   encoders['property_type'].classes_.tolist(),
        'known_districts': encoders['district'].classes_.tolist(),
    }

    model_path = OUTPUT_DIR / 'best_model.pkl'
    joblib.dump(bundle, model_path)
    print(f"      Modèle sauvegardé : {model_path}")

    # Métriques JSON
    metrics_path = OUTPUT_DIR / 'model_metrics.json'
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"      Métriques sauvegardées : {metrics_path}")

    # Feature importance
    if hasattr(best_model, 'feature_importances_'):
        fi = pd.DataFrame({
            'feature':    features,
            'importance': best_model.feature_importances_,
        }).sort_values('importance', ascending=False)
        fi_path = OUTPUT_DIR / 'feature_importance.csv'
        fi.to_csv(fi_path, index=False)
        print(f"      Feature importance sauvegardée : {fi_path}")
        print("\n  Top 6 features :")
        for _, row in fi.head(6).iterrows():
            bar = '█' * int(row['importance'] * 40)
            print(f"    {row['feature']:<20} {bar} {row['importance']:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Orchiimmo ML Training — Maroc MAD')
    parser.add_argument('--data', type=str, default=str(DEFAULT_CSV),
                        help='Chemin vers le CSV maître (default: Phase1_BI/orchiimmo_master_enriched_FR.csv)')
    parser.add_argument('--model', type=str, choices=['rf', 'lgb', 'xgb', 'cat'],
                        default=None, help='Forcer un modèle spécifique')
    args = parser.parse_args()

    print("=" * 60)
    print("  ORCHIIMMO — Entraînement ML (Appartements Maroc, MAD)")
    print("=" * 60)

    # 1. Chargement
    df = load_and_filter(Path(args.data))

    # 2. Features
    X, y, encoders, features = prepare_features(df)

    # 3. Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )
    print(f"\n  Train : {len(X_train):,} | Test : {len(X_test):,}")

    # 4. Modèles
    models = build_models(args.model)

    # 5. Entraîner & évaluer
    results = train_and_evaluate(models, X_train, X_test, y_train, y_test)

    # 6. Sélectionner le meilleur (R² max)
    print("\n[4/5] Sélection du meilleur modèle…")
    best_name  = max(results, key=lambda n: results[n]['R2'])
    best_model = models[best_name]
    print(f"  → {best_name} sélectionné (R² = {results[best_name]['R2']:.4f})")

    # 7. Vérification seuil qualité
    if results[best_name]['R2'] < 0.60:
        print(f"\n  AVERTISSEMENT : R² = {results[best_name]['R2']:.4f} < 0.60")
        print("  Le modèle risque de donner des prédictions peu fiables.")
        print("  Vérifiez le dataset ou ajoutez des features.")

    # 8. Sauvegarder
    save_artifacts(best_name, best_model, encoders, features,
                   results, len(X_train), len(X_test))

    print("\n[5/5] Résumé des modèles :")
    print(f"  {'Modèle':<15} {'R²':>8} {'MAE (DH)':>14} {'MAPE':>8}")
    print("  " + "-" * 48)
    for name, m in results.items():
        star = " ★" if name == best_name else ""
        print(f"  {name:<15} {m['R2']:>8.4f} {m['MAE']:>14,.0f} {m['MAPE']:>7.1f}%{star}")

    print("\n  Entraînement terminé avec succès !")
    print(f"  Prochain step : python manage.py import_csv && python manage.py runserver")
    print("=" * 60)


if __name__ == '__main__':
    main()
