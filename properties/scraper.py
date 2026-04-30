"""
Orchiimmo — Scraper temps réel
Sites : Mubawab.ma · Avito.ma · Sarouty.ma (fallback)
Langue : Fr  |  Prix : MAD uniquement
Testé le : 2026-04-30
"""
import re
import time
import random
import json
import logging
from datetime import date
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

EUR_TO_MAD = 10.80

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'fr-FR,fr;q=0.9,ar;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Connection': 'keep-alive',
}


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _parse_price_mad(raw: str) -> Optional[float]:
    """
    Extrait un montant en MAD depuis un texte brut.
    Supporte : '600 000 DH', '1,500,000 MAD', '130 K€', '1.5M DH'
    """
    if not raw:
        return None
    raw = raw.replace('\xa0', ' ').replace(' ', ' ').strip()

    # EUR → MAD
    is_eur = bool(re.search(r'[€]|eur|euro', raw, re.I))

    # Millions
    m_match = re.search(r'([\d.,]+)\s*[Mm]', raw)
    if m_match:
        try:
            val = float(m_match.group(1).replace(',', '.')) * 1_000_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

    # Milliers (K)
    k_match = re.search(r'([\d.,]+)\s*[Kk]', raw)
    if k_match:
        try:
            val = float(k_match.group(1).replace(',', '.')) * 1_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

    # Nombre brut (supprimer espaces, points de milliers, garder virgule décimale)
    cleaned = re.sub(r'[\s ]', '', raw)
    cleaned = re.sub(r'[^\d,.]', '', cleaned)
    # Si plusieurs '.' ou ',' → c'est séparateur de milliers
    cleaned = cleaned.replace(',', '').replace('.', '')
    if cleaned.isdigit():
        val = float(cleaned)
        if is_eur:
            val *= EUR_TO_MAD
        # Santé : entre 50 000 et 500 000 000 MAD
        if 50_000 <= val <= 500_000_000:
            return round(val)
    return None


def _parse_area(raw: str) -> Optional[float]:
    m = re.search(r'([\d,. ]+)\s*m', str(raw), re.I)
    if m:
        try:
            return float(m.group(1).replace(',', '.').replace(' ', ''))
        except ValueError:
            pass
    return None


def _parse_int(raw: str) -> Optional[int]:
    m = re.search(r'\d+', str(raw))
    return int(m.group()) if m else None


# Villes marocaines connues pour validation
VILLES_MAROC = {
    'casablanca', 'marrakech', 'rabat', 'fès', 'fes', 'tanger', 'agadir',
    'meknès', 'meknes', 'oujda', 'kénitra', 'kenitra', 'tétouan', 'tetouan',
    'salé', 'sale', 'mohammédia', 'mohammedia', 'temara', 'béni mellal', 'beni mellal',
    'el jadida', 'nador', 'settat', 'berrechid', 'khouribga', 'taroudant',
    'laâyoune', 'dakhla', 'safi', 'bouskoura', 'dar bouazza', 'ait melloul',
    'inezgane', 'essaouira', 'ouarzazate', 'errachidia', 'tiznit',
}


def _split_location(raw: str, avito_format: bool = False):
    """
    Mubawab  : 'Zone Industrielle Mghogha, Tanger' → ('Tanger', 'Zone Industrielle Mghogha')
    Avito    : 'Marrakech, Guéliz'                  → ('Marrakech', 'Guéliz')
    """
    parts = [p.strip() for p in re.split(r'[,]', raw) if p.strip()]
    if len(parts) >= 2:
        if avito_format:
            # Avito : "Ville, Quartier"
            city = parts[0].title()
            dist = parts[1].title()
        else:
            # Mubawab : "Quartier, Ville" — la ville est à la fin
            city = parts[-1].title()
            dist = parts[0].title()
        if city == dist:
            dist = ''
        return _clean_city(city), dist
    return _clean_city(raw.strip().title()), ''


def _clean_city(city: str) -> str:
    """Valide et nettoie le nom de ville. Retourne 'Maroc' si invalide."""
    city = city.strip()
    # Rejeter si trop court, contient chiffres, ou commence par %
    if (len(city) < 3
            or re.search(r'\d', city)
            or city.startswith('%')
            or city.lower() in ('une', 'le', 'la', 'les', 'des', 'de')):
        return 'Maroc'
    return city


def _guess_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ('villa', 'maison', 'duplex', 'triplex')): return 'villa'
    if 'riad' in t:   return 'riad'
    if any(k in t for k in ('terrain', 'lot ', 'hectare')):           return 'land'
    if any(k in t for k in ('bureau', 'local comm', 'magasin', 'commerce')): return 'office'
    if any(k in t for k in ('hôtel', 'hotel', 'résidence')):          return 'hotel'
    return 'apartment'


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _delay(lo=1.2, hi=2.5):
    time.sleep(random.uniform(lo, hi))


# ── Scraper Mubawab ───────────────────────────────────────────────────────────

class MubawabScraper:
    """
    Scrape Mubawab.ma — vente immobilier Maroc.
    URL pattern : https://www.mubawab.ma/fr/sc/appartements-a-vendre:p:{page}
    Aussi : villas, terrains, bureaux, riads
    """
    SOURCE = 'mubawab'
    # Catégories valides (vérifiées le 2026-04-30)
    CATEGORIES = [
        'appartements-a-vendre',
        'maisons-a-vendre',
        'terrains-a-vendre',
        'locaux-a-vendre',
        'riads-a-vendre',
    ]
    BASE = 'https://www.mubawab.ma/fr/sc/{cat}:p:{page}'

    def scrape(self, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
        session = _new_session()

        for cat in self.CATEGORIES:
            for page in range(1, max_pages + 1):
                url = self.BASE.format(cat=cat, page=page)
                try:
                    resp = session.get(url, timeout=25, allow_redirects=True)
                    if resp.status_code != 200:
                        logger.warning(f'[Mubawab] {url} → {resp.status_code}')
                        break
                except Exception as e:
                    logger.warning(f'[Mubawab] {url} erreur: {e}')
                    break

                soup = BeautifulSoup(resp.text, 'lxml')
                cards = soup.select('div.listingBox')
                if not cards:
                    break

                for card in cards:
                    listing = self._parse_card(card, cat)
                    if listing:
                        if city_filter and city_filter.lower() not in listing['city'].lower():
                            continue
                        yield listing

                if page < max_pages:
                    _delay()

    def _parse_card(self, card, cat: str) -> Optional[dict]:
        # ── Prix ──────────────────────────────────────────────────────────────
        price_el = card.select_one('.priceTag')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else None
        if not price_mad:
            return None

        # ── Titre & lien ──────────────────────────────────────────────────────
        link_el = card.select_one('a[href*="mubawab.ma"]')
        if not link_el:
            link_el = card.select_one('a')
        href  = (link_el.get('href', '') if link_el else '').strip()
        title = (link_el.get_text(strip=True) if link_el else '')[:300]

        # ── Localisation ──────────────────────────────────────────────────────
        # Full text split : "600 000 DH|Titre|Zone, Ville|77 m²|..."
        texts = [t.strip() for t in card.get_text(separator='|').split('|')
                 if t.strip() and t.strip() not in ('Contacter','Appelez','WhatsApp','')]
        # La localisation est souvent le 3e élément (après prix et titre)
        location_raw = ''
        for t in texts:
            if ',' in t and not any(k in t for k in ('DH','MAD','m²','Pièce','Chambre','Salle')):
                location_raw = t
                break
        city, dist = _split_location(location_raw) if location_raw else ('', '')

        # ── Surface ───────────────────────────────────────────────────────────
        area_m2 = None
        for t in texts:
            if 'm²' in t:
                area_m2 = _parse_area(t)
                if area_m2:
                    break

        # ── Chambres / Pièces ─────────────────────────────────────────────────
        bedrooms  = None
        bathrooms = None
        for t in texts:
            tl = t.lower()
            if 'chambre' in tl and bedrooms is None:
                bedrooms = _parse_int(t)
            elif 'salle' in tl and 'bain' in tl and bathrooms is None:
                bathrooms = _parse_int(t)

        # ── Type ──────────────────────────────────────────────────────────────
        prop_type = _guess_type(cat + ' ' + title)

        return {
            'source':           self.SOURCE,
            'city':             city[:100] or 'Maroc',
            'district':         dist[:100],
            'property_type':    prop_type,
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        bathrooms,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
        }


# ── Scraper Avito ─────────────────────────────────────────────────────────────

class AvitoScraper:
    """
    Scrape Avito.ma via __NEXT_DATA__ JSON — très fiable.
    URL : https://www.avito.ma/fr/maroc/immobilier-%C3%A0_vendre?o={page}
    """
    SOURCE = 'avito'
    BASE   = 'https://www.avito.ma/fr/maroc/immobilier-%C3%A0_vendre?o={page}'

    def scrape(self, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
        session = _new_session()

        for page in range(1, max_pages + 1):
            url = self.BASE.format(page=page)
            try:
                resp = session.get(url, timeout=25)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f'[Avito] page {page} erreur: {e}')
                break

            ads = self._extract_ads(resp.text)
            if not ads:
                logger.info(f'[Avito] page {page} — aucune annonce.')
                break

            for ad in ads:
                listing = self._parse_ad(ad)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing

            if page < max_pages:
                _delay()

    @staticmethod
    def _extract_ads(html: str) -> list:
        """Extrait les annonces depuis __NEXT_DATA__ JSON."""
        try:
            m = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            if not m:
                return []
            data     = json.loads(m.group(1))
            comp     = data['props']['pageProps']['componentProps']
            ads_data = comp.get('ads', {})
            if isinstance(ads_data, dict):
                ads = ads_data.get('ads', [])
            elif isinstance(ads_data, list):
                ads = ads_data
            else:
                ads = []
            return ads if isinstance(ads, list) else []
        except Exception as e:
            logger.debug(f'[Avito] JSON parse error: {e}')
            return []

    def _parse_ad(self, ad: dict) -> Optional[dict]:
        # Prix (déjà en DH / MAD)
        price_data = ad.get('price', {})
        if isinstance(price_data, dict):
            price_val = price_data.get('value')
            currency  = price_data.get('currency', 'DH')
        else:
            raw = str(price_data)
            price_val = _parse_price_mad(raw)
            currency  = 'DH'

        if not price_val:
            return None

        price_mad = float(price_val)
        if 'eur' in str(currency).lower() or '€' in str(currency):
            price_mad *= EUR_TO_MAD

        if not (50_000 <= price_mad <= 500_000_000):
            return None

        price_mad = round(price_mad)

        # Titre
        title = str(ad.get('subject', ''))[:300]

        # URL
        href = ad.get('href', '') or ''
        if href and not href.startswith('http'):
            href = 'https://www.avito.ma' + href

        # Localisation : Avito donne "Ville, Quartier" (avito_format=True)
        location_raw = str(ad.get('location', ''))
        city, dist   = _split_location(location_raw, avito_format=True) if location_raw else ('', '')

        # Paramètres (surface, chambres)
        area_m2   = None
        bedrooms  = None
        bathrooms = None

        params = ad.get('params', {})
        param_list = []
        if isinstance(params, dict):
            param_list = params.get('secondary', []) or params.get('primary', []) or []
        elif isinstance(params, list):
            param_list = params

        for p in param_list:
            if not isinstance(p, dict):
                continue
            key = str(p.get('key', '')).lower()
            val = str(p.get('value', '') or p.get('fullValue', ''))
            if 'room' in key or 'chambre' in key or 'pièce' in key:
                bedrooms = _parse_int(val)
            elif 'area' in key or 'surface' in key or 'size' in key:
                area_m2 = _parse_area(val)
            elif 'bath' in key or 'salle' in key:
                bathrooms = _parse_int(val)

        # Fallback : extraire surface du titre
        if area_m2 is None:
            area_m2 = _parse_area(title)

        prop_type = _guess_type(title)

        return {
            'source':           self.SOURCE,
            'city':             city[:100] or 'Maroc',
            'district':         dist[:100],
            'property_type':    prop_type,
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        bathrooms,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
        }


# ── Scraper Sarouty (fallback) ────────────────────────────────────────────────

class SaroutyScraper:
    """
    Scrape Sarouty.ma via l'API JSON interne.
    Endpoint : GET /api/listings?page=N&type=sale
    """
    SOURCE   = 'sarouty'
    API_BASE = 'https://www.sarouty.ma/api/listings?for_sale=1&page={page}&per_page=24'

    def scrape(self, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
        session = _new_session()
        # Sarouty a besoin de cookies du site principal d'abord
        try:
            session.get('https://www.sarouty.ma/', timeout=15)
        except Exception:
            pass

        for page in range(1, max_pages + 1):
            url = self.API_BASE.format(page=page)
            try:
                resp = session.get(url, timeout=20,
                                   headers={**HEADERS, 'Accept': 'application/json',
                                            'X-Requested-With': 'XMLHttpRequest'})
                if resp.status_code != 200:
                    logger.warning(f'[Sarouty] API page {page} → {resp.status_code}')
                    break

                data = resp.json()
                listings = data.get('listings') or data.get('data') or []
                if not listings:
                    break

                for item in listings:
                    listing = self._parse_item(item)
                    if listing:
                        if city_filter and city_filter.lower() not in listing['city'].lower():
                            continue
                        yield listing

            except Exception as e:
                logger.warning(f'[Sarouty] page {page} erreur: {e}')
                break

            if page < max_pages:
                _delay()

    def _parse_item(self, item: dict) -> Optional[dict]:
        price_raw = item.get('price') or item.get('price_mad') or item.get('prix')
        price_mad = _parse_price_mad(str(price_raw)) if price_raw else None
        if not price_mad:
            return None

        title    = str(item.get('title') or item.get('titre') or '')[:300]
        city     = str(item.get('city') or item.get('ville') or 'Maroc')[:100]
        district = str(item.get('district') or item.get('quartier') or '')[:100]
        href     = str(item.get('url') or item.get('link') or '')[:500]
        area_m2  = _parse_area(str(item.get('area') or item.get('surface') or ''))
        bedrooms = _parse_int(str(item.get('bedrooms') or item.get('chambres') or ''))
        prop_type = _guess_type(title + ' ' + city)

        return {
            'source':           self.SOURCE,
            'city':             city.title(),
            'district':         district.title(),
            'property_type':    prop_type,
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        None,
            'url':              href,
            'scraped_at':       date.today().isoformat(),
        }


# ── Orchestrateur ─────────────────────────────────────────────────────────────

SCRAPERS = {
    'mubawab': MubawabScraper,
    'avito':   AvitoScraper,
    'sarouty': SaroutyScraper,
}


def _is_opportunity(listing: dict) -> bool:
    """Heuristique : opportunité si prix/m² < 9 000 DH (75% de la médiane nationale)."""
    ppm2 = listing.get('price_per_m2_mad')
    return bool(ppm2 and ppm2 < 9_000)


def scrape_all(sources: list = None, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
    """
    Scrape toutes les sources et yield chaque annonce au format dict.
    Sauvegarde automatiquement les nouvelles annonces en DB.
    """
    from properties.models import Property

    if sources is None:
        sources = list(SCRAPERS.keys())

    total_new = 0
    total_dup = 0

    for source_name in sources:
        cls = SCRAPERS.get(source_name)
        if not cls:
            continue

        logger.info(f'[Scraper] Démarrage {source_name}…')
        try:
            for listing in cls().scrape(max_pages=max_pages,
                                        city_filter=city_filter):
                # Dédoublonnage par URL
                url = listing.get('url', '')
                is_dup = bool(url and Property.objects.filter(url=url).exists())

                if not is_dup:
                    listing['is_opportunity'] = _is_opportunity(listing)
                    try:
                        prop = Property.objects.create(
                            source            = listing['source'],
                            city              = listing['city'],
                            district          = listing.get('district', ''),
                            property_type     = listing.get('property_type', 'apartment'),
                            title             = listing.get('title', ''),
                            price_mad         = listing['price_mad'],
                            price_per_m2_mad  = listing.get('price_per_m2_mad'),
                            area_m2           = listing.get('area_m2'),
                            bedrooms          = listing.get('bedrooms'),
                            bathrooms         = listing.get('bathrooms'),
                            url               = url,
                            scraped_at        = date.today(),
                            is_opportunity    = listing.get('is_opportunity', False),
                        )
                        listing['id']    = prop.pk
                        listing['is_new'] = True
                        total_new += 1
                    except Exception as e:
                        logger.error(f'[DB] Erreur création: {e}')
                        listing['is_new'] = False
                else:
                    listing['is_new'] = False
                    total_dup += 1

                listing['total_new'] = total_new
                listing['total_dup'] = total_dup
                yield listing

        except Exception as e:
            logger.error(f'[{source_name}] Crash: {e}')
            yield {
                'error':     str(e),
                'source':    source_name,
                'is_new':    False,
                'total_new': total_new,
                'total_dup': total_dup,
            }

    logger.info(
        f'[Scraper] Terminé — {total_new} nouvelles · {total_dup} doublons'
    )
