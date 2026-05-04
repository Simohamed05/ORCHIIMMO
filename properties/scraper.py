"""
Orchiimmo — Scraper temps réel v2.0
Sources : Mubawab · Avito · Sarouty · Sekna · SelectImmo · LogiqueImmo
          MarocAnnonce · MaisonMaroc · Keurimmo · Immobilier.ma
Langue : Fr  |  Prix : MAD
Contact : téléphone, email, agence collectés quand disponibles
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
    'Referer': 'https://www.google.com/',
}

# Regex téléphones marocains : 06X, 07X, 05X + international +212
_PHONE_RE = re.compile(
    r'(?<!\d)'
    r'(?:\+212\s?|00212\s?)?'
    r'(?:0)?'
    r'[567]\d{1}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}'
    r'(?!\d)'
)
_EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)


# ── Utilitaires prix / surface ────────────────────────────────────────────────

def _parse_price_mad(raw: str) -> Optional[float]:
    if not raw:
        return None
    raw = raw.replace('\xa0', ' ').replace(' ', ' ').strip()
    is_eur = bool(re.search(r'[€]|eur|euro', raw, re.I))

    # Millions
    m = re.search(r'([\d.,]+)\s*[Mm](?:illion)?', raw)
    if m:
        try:
            val = float(m.group(1).replace(',', '.')) * 1_000_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

    # Milliers (K)
    k = re.search(r'([\d.,]+)\s*[Kk]', raw)
    if k:
        try:
            val = float(k.group(1).replace(',', '.')) * 1_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

    # Nombre brut
    cleaned = re.sub(r'[\s ]', '', raw)
    cleaned = re.sub(r'[^\d,.]', '', cleaned)
    cleaned = cleaned.replace(',', '').replace('.', '')
    if cleaned.isdigit():
        val = float(cleaned)
        if is_eur:
            val *= EUR_TO_MAD
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


# ── Utilitaires contact ───────────────────────────────────────────────────────

def _extract_phones(text: str) -> list:
    """Extrait les numéros de téléphone marocains depuis un texte brut."""
    raw_phones = _PHONE_RE.findall(text)
    phones = []
    for p in raw_phones:
        # Normaliser : supprimer espaces/tirets/points
        cleaned = re.sub(r'[\s.\-]', '', p)
        # Toujours commencer par 0
        if cleaned.startswith('+212'):
            cleaned = '0' + cleaned[4:]
        elif cleaned.startswith('00212'):
            cleaned = '0' + cleaned[5:]
        elif cleaned.startswith('212'):
            cleaned = '0' + cleaned[3:]
        # Valider longueur : 10 chiffres
        if re.match(r'^0[5-7]\d{8}$', cleaned) and cleaned not in phones:
            phones.append(cleaned)
    return phones[:2]  # Max 2 numéros


def _extract_email(text: str) -> str:
    """Extrait la première adresse email valide."""
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else ''


def _detect_contact_type(text: str) -> str:
    """Détecte si c'est une agence ou un particulier."""
    t = text.lower()
    if any(k in t for k in ('agence', 'immobilière', 'agency', 'promoteur',
                             'groupe', 'sarl', 'sas', 'sa ', 'cabinet')):
        return 'agence'
    if any(k in t for k in ('particulier', 'propriétaire', 'owner')):
        return 'particulier'
    return ''


# ── Utilitaires localisation ──────────────────────────────────────────────────

VILLES_MAROC = {
    'casablanca', 'marrakech', 'rabat', 'fès', 'fes', 'tanger', 'agadir',
    'meknès', 'meknes', 'oujda', 'kénitra', 'kenitra', 'tétouan', 'tetouan',
    'salé', 'sale', 'mohammédia', 'mohammedia', 'temara', 'beni mellal',
    'el jadida', 'nador', 'settat', 'berrechid', 'khouribga', 'taroudant',
    'laâyoune', 'dakhla', 'safi', 'bouskoura', 'dar bouazza', 'ait melloul',
    'inezgane', 'essaouira', 'ouarzazate', 'errachidia', 'tiznit', 'ifrane',
}


def _split_location(raw: str, avito_format: bool = False):
    parts = [p.strip() for p in re.split(r'[,]', raw) if p.strip()]
    if len(parts) >= 2:
        if avito_format:
            city = parts[0].title()
            dist = parts[1].title()
        else:
            city = parts[-1].title()
            dist = parts[0].title()
        if city == dist:
            dist = ''
        return _clean_city(city), dist
    return _clean_city(raw.strip().title()), ''


def _clean_city(city: str) -> str:
    city = city.strip()
    if (len(city) < 3
            or re.search(r'\d', city)
            or city.startswith('%')
            or city.lower() in ('une', 'le', 'la', 'les', 'des', 'de', 'du')):
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


def _delay(lo=1.5, hi=3.0):
    time.sleep(random.uniform(lo, hi))


def _get(session, url, timeout=25) -> Optional[BeautifulSoup]:
    """GET avec gestion d'erreurs — retourne soup ou None."""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return BeautifulSoup(r.text, 'lxml')
        logger.warning(f'[GET] {url} → {r.status_code}')
    except Exception as e:
        logger.warning(f'[GET] {url} erreur: {e}')
    return None


def _empty_contact() -> dict:
    return {
        'contact_name':   '',
        'contact_phone':  '',
        'contact_phone2': '',
        'contact_email':  '',
        'contact_agency': '',
        'contact_type':   '',
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. Mubawab ────────────────────────────────────────────────────────────────

class MubawabScraper:
    SOURCE = 'mubawab'
    CATEGORIES = [
        'appartements-a-vendre',
        'maisons-a-vendre',
        'terrains-a-vendre',
        'locaux-a-vendre',
        'riads-a-vendre',
    ]
    BASE = 'https://www.mubawab.ma/fr/sc/{cat}:p:{page}'
    DETAIL_BASE = 'https://www.mubawab.ma'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for cat in self.CATEGORIES:
            for page in range(1, max_pages + 1):
                soup = _get(session, self.BASE.format(cat=cat, page=page))
                if not soup:
                    break
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
        price_el  = card.select_one('.priceTag')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else None
        if not price_mad:
            return None

        link_el = card.select_one('a[href*="mubawab.ma"]') or card.select_one('a')
        href    = (link_el.get('href', '') if link_el else '').strip()
        title   = (link_el.get_text(strip=True) if link_el else '')[:300]

        texts = [t.strip() for t in card.get_text(separator='|').split('|')
                 if t.strip() and t.strip() not in ('Contacter', 'Appelez', 'WhatsApp', '')]

        location_raw = ''
        for t in texts:
            if ',' in t and not any(k in t for k in ('DH', 'MAD', 'm²', 'Pièce', 'Chambre', 'Salle')):
                location_raw = t
                break
        city, dist = _split_location(location_raw) if location_raw else ('', '')

        area_m2 = next((_parse_area(t) for t in texts if 'm²' in t and _parse_area(t)), None)

        bedrooms = bathrooms = None
        for t in texts:
            tl = t.lower()
            if 'chambre' in tl and bedrooms is None:
                bedrooms = _parse_int(t)
            elif 'salle' in tl and 'bain' in tl and bathrooms is None:
                bathrooms = _parse_int(t)

        # Contact visible sur la carte
        full_text = card.get_text(' ')
        phones    = _extract_phones(full_text)
        email     = _extract_email(full_text)

        # Nom agence : souvent dans .agencyName ou .userName
        agency_el = card.select_one('.agencyName, .agency-name, .userName, .user-name')
        agency    = agency_el.get_text(strip=True) if agency_el else ''

        contact = {
            'contact_phone':  phones[0] if phones else '',
            'contact_phone2': phones[1] if len(phones) > 1 else '',
            'contact_email':  email,
            'contact_agency': agency[:200],
            'contact_name':   agency[:200],
            'contact_type':   _detect_contact_type(agency + full_text),
        }

        result = {
            'source':           self.SOURCE,
            'city':             city[:100] or 'Maroc',
            'district':         dist[:100],
            'property_type':    _guess_type(cat + ' ' + title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        bathrooms,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
        }
        result.update(contact)
        return result


# ── 2. Avito ─────────────────────────────────────────────────────────────────

class AvitoScraper:
    SOURCE = 'avito'
    BASE   = 'https://www.avito.ma/fr/maroc/immobilier-%C3%A0_vendre?o={page}'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for page in range(1, max_pages + 1):
            soup = _get(session, self.BASE.format(page=page))
            if not soup:
                break
            ads = self._extract_ads_from_soup(soup)
            if not ads:
                # Fallback JSON
                try:
                    r = session.get(self.BASE.format(page=page), timeout=25)
                    ads = self._extract_ads(r.text)
                except Exception:
                    ads = []
            if not ads:
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
        try:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group(1))
            comp = data['props']['pageProps']['componentProps']
            ads_data = comp.get('ads', {})
            if isinstance(ads_data, dict):
                return ads_data.get('ads', [])
            return ads_data if isinstance(ads_data, list) else []
        except Exception:
            return []

    @staticmethod
    def _extract_ads_from_soup(soup: BeautifulSoup) -> list:
        """Fallback HTML parsing si JSON indisponible."""
        cards = soup.select('article.sc-1nre5ec-1, [data-testid="adListItem"], .sc-b483e5e1-2')
        return [{'_soup_card': c} for c in cards] if cards else []

    def _parse_ad(self, ad: dict) -> Optional[dict]:
        # Cas soup card (fallback HTML)
        if '_soup_card' in ad:
            return self._parse_soup_card(ad['_soup_card'])

        # Cas JSON normal
        price_data = ad.get('price', {})
        if isinstance(price_data, dict):
            price_val = price_data.get('value')
            currency  = price_data.get('currency', 'DH')
        else:
            price_val = _parse_price_mad(str(price_data))
            currency  = 'DH'

        if not price_val:
            return None

        price_mad = float(price_val)
        if 'eur' in str(currency).lower() or '€' in str(currency):
            price_mad *= EUR_TO_MAD
        if not (50_000 <= price_mad <= 500_000_000):
            return None
        price_mad = round(price_mad)

        title = str(ad.get('subject', ''))[:300]
        href  = ad.get('href', '') or ''
        if href and not href.startswith('http'):
            href = 'https://www.avito.ma' + href

        location_raw = str(ad.get('location', ''))
        city, dist = _split_location(location_raw, avito_format=True)

        area_m2 = bedrooms = bathrooms = None
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
            if any(k in key for k in ('room', 'chambre', 'pièce')):
                bedrooms = _parse_int(val)
            elif any(k in key for k in ('area', 'surface', 'size')):
                area_m2 = _parse_area(val)
            elif any(k in key for k in ('bath', 'salle')):
                bathrooms = _parse_int(val)

        if area_m2 is None:
            area_m2 = _parse_area(title)

        # Contact dans le JSON Avito
        seller = ad.get('seller', {}) or {}
        contact_name   = str(seller.get('name', '') or seller.get('store', '') or '')[:200]
        contact_agency = str(seller.get('store', '') or '')[:200]
        contact_type   = 'agence' if seller.get('type') == 'store' else 'particulier' if seller.get('type') == 'private' else ''

        result = {
            'source':           self.SOURCE,
            'city':             city[:100] or 'Maroc',
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        bathrooms,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_name':     contact_name,
            'contact_agency':   contact_agency,
            'contact_type':     contact_type,
            'contact_phone':    '',
            'contact_phone2':   '',
            'contact_email':    '',
        }
        return result

    def _parse_soup_card(self, card) -> Optional[dict]:
        """Parse une carte Avito en HTML brut."""
        text = card.get_text(' ')
        price_mad = None
        for el in card.select('[class*="price"], [data-testid*="price"]'):
            price_mad = _parse_price_mad(el.get_text(strip=True))
            if price_mad:
                break
        if not price_mad:
            return None

        link = card.select_one('a')
        href  = ('https://www.avito.ma' + link['href']) if link and link.get('href') else ''
        title = (link.get_text(strip=True) if link else '')[:300]
        area_m2 = _parse_area(text)
        phones  = _extract_phones(text)

        result = {
            'source':           self.SOURCE,
            'city':             'Maroc',
            'district':         '',
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    '',
            'contact_name':     '',
            'contact_agency':   '',
            'contact_type':     '',
        }
        return result


# ── 3. Sarouty ────────────────────────────────────────────────────────────────

class SaroutyScraper:
    SOURCE   = 'sarouty'
    API_BASE = 'https://www.sarouty.ma/api/listings?for_sale=1&page={page}&per_page=24'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
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
                    break
                data     = resp.json()
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
                logger.warning(f'[Sarouty] page {page}: {e}')
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

        # Contact
        agent = item.get('agent') or item.get('contact') or {}
        phones = _extract_phones(str(item.get('phone') or agent.get('phone') or ''))

        result = {
            'source':           self.SOURCE,
            'city':             city.title(),
            'district':         district.title(),
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 and area_m2 > 0 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        None,
            'url':              href,
            'scraped_at':       date.today().isoformat(),
            'contact_name':     str(agent.get('name', '') or '')[:200],
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    _extract_email(str(agent.get('email', '') or '')),
            'contact_agency':   str(item.get('agency', '') or agent.get('agency', '') or '')[:200],
            'contact_type':     '',
        }
        return result


# ── 4. Sekna.ma ───────────────────────────────────────────────────────────────

class SeknaScraper:
    """Scrape Sekna.ma — plateforme immobilière marocaine."""
    SOURCE = 'sekna'
    URLS = [
        'https://sekna.ma/fr/properties?transaction_type=sale&page={page}',
        'https://www.sekna.ma/fr/annonces/vente?page={page}',
        'https://sekna.ma/vente?page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None

        # Trouver l'URL qui fonctionne
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and (soup.select('[class*="property"], [class*="listing"], [class*="annonce"]')
                         or soup.select('article')):
                working_url = url_template
                break

        if not working_url:
            logger.warning('[Sekna] Aucune URL valide trouvée')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break

            cards = (soup.select('[class*="property-card"], [class*="listing-card"]')
                     or soup.select('article')
                     or soup.select('[class*="annonce"]'))
            if not cards:
                break

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing

            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')

        # Prix
        price_el = (card.select_one('[class*="price"], [class*="prix"]')
                    or card.select_one('strong'))
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        # Titre & lien
        link = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://sekna.ma' + href
        title = (link.get_text(strip=True) if link else card.select_one('h2, h3, h4, [class*="title"]'))
        if hasattr(title, 'get_text'):
            title = title.get_text(strip=True)
        title = str(title or '')[:300]

        # Localisation
        loc_el = card.select_one('[class*="location"], [class*="city"], [class*="ville"], [class*="address"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2   = _parse_area(text)
        bedrooms  = None
        bathrooms = None
        for el in card.select('[class*="room"], [class*="chambre"], [class*="bed"]'):
            bedrooms = _parse_int(el.get_text(strip=True))
            break

        phones = _extract_phones(text)
        email  = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="agent"]')
        agency = agency_el.get_text(strip=True) if agency_el else ''

        result = {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        bathrooms,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }
        return result


# ── 5. SelectImmo.ma ─────────────────────────────────────────────────────────

class SelectImmoScraper:
    SOURCE = 'selectimmo'
    URLS = [
        'https://www.selectimmo.ma/vente-immobilier-maroc?page={page}',
        'https://www.selectimmo.ma/annonces/vente?page={page}',
        'https://www.selectimmo.ma/fr/annonces?transaction=vente&page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and soup.select('article, [class*="property"], [class*="listing"]'):
                working_url = url_template
                break
        if not working_url:
            logger.warning('[SelectImmo] Site inaccessible')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break
            cards = (soup.select('[class*="property"], [class*="listing"], [class*="annonce"]')
                     or soup.select('article'))
            if not cards:
                break
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing
            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        price_el = card.select_one('[class*="price"], [class*="prix"], strong, b')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.selectimmo.ma' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"], [class*="addr"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2   = _parse_area(text)
        phones    = _extract_phones(text)
        email     = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="agent"], [class*="contact"]')
        agency    = agency_el.get_text(strip=True) if agency_el else ''

        result = {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         _parse_int(re.search(r'(\d+)\s*ch', text, re.I).group(1)) if re.search(r'(\d+)\s*ch', text, re.I) else None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }
        return result


# ── 6. LogiqueImmo.ma ────────────────────────────────────────────────────────

class LogiqueImmoScraper:
    SOURCE = 'logiqueimmo'
    URLS = [
        'https://www.logiqueimmo.ma/liste/vente?page={page}',
        'https://www.logiqueimmo.ma/annonces/vente?page={page}',
        'https://www.logiqueimmo.ma/fr/vente?page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and soup.select('article, [class*="property"], [class*="bien"], [class*="annonce"]'):
                working_url = url_template
                break
        if not working_url:
            logger.warning('[LogiqueImmo] Site inaccessible')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break
            cards = (soup.select('[class*="property"], [class*="bien"], [class*="annonce"]')
                     or soup.select('article'))
            if not cards:
                break
            for card in cards:
                listing = self._parse_generic_card(card, 'https://www.logiqueimmo.ma')
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing
            if page < max_pages:
                _delay()

    def _parse_generic_card(self, card, base_url: str) -> Optional[dict]:
        text = card.get_text(' ')
        price_el = card.select_one('[class*="price"], [class*="prix"], strong')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = base_url + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"], [class*="quartier"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="contact"]')
        agency   = agency_el.get_text(strip=True) if agency_el else ''

        return {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }


# ── 7. MarocAnnonce.ma ───────────────────────────────────────────────────────

class MarocAnnonceScraper:
    SOURCE = 'marocannonce'
    BASE   = 'https://www.marocannonce.com/maroc/annonces-immobilier-b258.html?page={page}'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for page in range(1, max_pages + 1):
            soup = _get(session, self.BASE.format(page=page))
            if not soup:
                break

            cards = (soup.select('.holder, .listing, [class*="annonce"], li.mrgnB10')
                     or soup.select('li'))
            if not cards:
                break

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing

            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        if not any(k in text.lower() for k in ('dh', 'mad', 'appartement', 'villa',
                                                  'terrain', 'bureau', 'maison', 'immo')):
            return None

        price_el = card.select_one('[class*="price"], strong, b, [class*="prix"]')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.marocannonce.com' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="city"], [class*="ville"], [class*="lieu"], [class*="location"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)

        return {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title + ' ' + text),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     '',
            'contact_agency':   '',
            'contact_type':     _detect_contact_type(text),
        }


# ── 8. MaisonMaroc.ma ────────────────────────────────────────────────────────

class MaisonMarocScraper:
    SOURCE = 'maisonmaroc'
    URLS = [
        'https://www.maisonmaroc.com/vente/?page={page}',
        'https://www.maisonmaroc.com/annonces/vente?page={page}',
        'https://www.maisonmaroc.com/fr/immobilier-vente?page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and soup.select('article, [class*="property"], [class*="listing"]'):
                working_url = url_template
                break
        if not working_url:
            logger.warning('[MaisonMaroc] Site inaccessible')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break
            cards = (soup.select('[class*="property"], [class*="listing"], [class*="bien"]')
                     or soup.select('article'))
            if not cards:
                break
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing
            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        price_el = card.select_one('[class*="price"], [class*="prix"], strong')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.maisonmaroc.com' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="agent"]')
        agency   = agency_el.get_text(strip=True) if agency_el else ''

        return {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }


# ── 9. Keurimmo.ma ───────────────────────────────────────────────────────────

class KeurimmoScraper:
    SOURCE = 'keurimmo'
    URLS = [
        'https://www.keurimmo.ma/vente?page={page}',
        'https://www.keurimmo.ma/annonces/vente?page={page}',
        'https://keurimmo.ma/fr/properties?page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and soup.select('article, [class*="property"], [class*="listing"], [class*="annonce"]'):
                working_url = url_template
                break
        if not working_url:
            logger.warning('[Keurimmo] Site inaccessible')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break
            cards = (soup.select('[class*="property"], [class*="listing"], [class*="annonce"]')
                     or soup.select('article'))
            if not cards:
                break
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing
            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        price_el = card.select_one('[class*="price"], [class*="prix"], strong, .price')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.keurimmo.ma' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="agent"]')
        agency   = agency_el.get_text(strip=True) if agency_el else ''

        return {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         None,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }


# ── 10. Immobilier.ma ────────────────────────────────────────────────────────

class ImmobilierMaScraper:
    SOURCE = 'immobilier'
    URLS = [
        'https://www.immobilier.ma/annonces/vente/?page={page}',
        'https://www.immobilier.ma/fr/annonces?transaction=vente&page={page}',
        'https://www.immobilier.ma/vente?p={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None
        for url_template in self.URLS:
            soup = _get(session, url_template.format(page=1))
            if soup and soup.select('article, [class*="property"], [class*="listing"], [class*="annonce"]'):
                working_url = url_template
                break
        if not working_url:
            logger.warning('[Immobilier.ma] Site inaccessible')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break
            cards = (soup.select('[class*="property"], [class*="listing"], [class*="annonce"], [class*="bien"]')
                     or soup.select('article'))
            if not cards:
                break
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield listing
            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        price_el = card.select_one('[class*="price"], [class*="prix"], strong, .price')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.immobilier.ma' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"], [class*="region"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        bedrooms = None
        bd_match = re.search(r'(\d+)\s*(?:ch|chambre|pièce|room)', text, re.I)
        if bd_match:
            bedrooms = int(bd_match.group(1))

        phones   = _extract_phones(text)
        email    = _extract_email(text)
        agency_el = card.select_one('[class*="agency"], [class*="agence"], [class*="agent"], [class*="promoteur"]')
        agency   = agency_el.get_text(strip=True) if agency_el else ''

        return {
            'source':           self.SOURCE,
            'city':             city[:100],
            'district':         dist[:100],
            'property_type':    _guess_type(title),
            'title':            title,
            'price_mad':        price_mad,
            'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
            'area_m2':          area_m2,
            'bedrooms':         bedrooms,
            'bathrooms':        None,
            'url':              href[:500],
            'scraped_at':       date.today().isoformat(),
            'contact_phone':    phones[0] if phones else '',
            'contact_phone2':   phones[1] if len(phones) > 1 else '',
            'contact_email':    email,
            'contact_name':     agency[:200],
            'contact_agency':   agency[:200],
            'contact_type':     _detect_contact_type(agency + text),
        }


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ══════════════════════════════════════════════════════════════════════════════

SCRAPERS = {
    'mubawab':      MubawabScraper,
    'avito':        AvitoScraper,
    'sarouty':      SaroutyScraper,
    'sekna':        SeknaScraper,
    'selectimmo':   SelectImmoScraper,
    'logiqueimmo':  LogiqueImmoScraper,
    'marocannonce': MarocAnnonceScraper,
    'maisonmaroc':  MaisonMarocScraper,
    'keurimmo':     KeurimmoScraper,
    'immobilier':   ImmobilierMaScraper,
}


def _is_opportunity(listing: dict) -> bool:
    """Opportunité si prix/m² < 9 000 DH (≈ 75% médiane nationale)."""
    ppm2 = listing.get('price_per_m2_mad')
    return bool(ppm2 and ppm2 < 9_000)


def scrape_all(sources: list = None, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
    """
    Scrape toutes les sources et yield chaque annonce.
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
            logger.warning(f'[Scraper] Source inconnue : {source_name}')
            continue

        logger.info(f'[Scraper] Démarrage {source_name}…')
        try:
            for listing in cls().scrape(max_pages=max_pages, city_filter=city_filter):
                url    = listing.get('url', '')
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
                            # ── Contact ──────────────────────────────────────
                            contact_name      = listing.get('contact_name', ''),
                            contact_phone     = listing.get('contact_phone', ''),
                            contact_phone2    = listing.get('contact_phone2', ''),
                            contact_email     = listing.get('contact_email', ''),
                            contact_agency    = listing.get('contact_agency', ''),
                            contact_type      = listing.get('contact_type', ''),
                        )
                        listing['id']     = prop.pk
                        listing['is_new'] = True
                        total_new += 1
                    except Exception as e:
                        logger.error(f'[DB] Erreur création ({source_name}): {e}')
                        listing['is_new'] = False
                else:
                    listing['is_new'] = False
                    total_dup += 1

                listing['total_new'] = total_new
                listing['total_dup'] = total_dup
                yield listing

        except Exception as e:
            logger.error(f'[{source_name}] Crash: {e}', exc_info=True)
            yield {
                'error':     str(e),
                'source':    source_name,
                'is_new':    False,
                'total_new': total_new,
                'total_dup': total_dup,
            }

    logger.info(f'[Scraper] Terminé — {total_new} nouvelles · {total_dup} doublons')
