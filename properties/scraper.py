"""
Orchiimmo — Scraper temps réel v3.0
Sources confirmées :
  1. Mubawab.ma         ✅ HTML classique
  2. Avito.ma           ✅ JSON __NEXT_DATA__
  3. Sarouty.ma         ✅ HTML WordPress
  4. Agenz.ma           ✅ HTML / JSON
  5. MarocAnnonces.com  ✅ HTML classique
  6. Masaken.ma         ✅ HTML (par ville)
  7. LogicImmo.ma       ✅ HTML WordPress agence
  8. Bikhir.ma          ⚠️  HTML best-effort
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

_PHONE_RE = re.compile(
    r'(?<!\d)'
    r'(?:\+212\s?|00212\s?)?'
    r'(?:0)?'
    r'[567]\d{1}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}'
    r'(?!\d)'
)
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


# ── Utilitaires prix / surface ────────────────────────────────────────────────

def _parse_price_mad(raw: str) -> Optional[float]:
    if not raw:
        return None
    raw = raw.replace('\xa0', ' ').replace(' ', '').replace(' ', '').strip()
    is_eur = bool(re.search(r'[€]|eur|euro', raw, re.I))

    # "3.5 Million DH" ou "3.5M DH" — mais PAS "215 m²"
    m = re.search(r'([\d.,]+)\s*(?:Million|Millions|MDH|M\s*DH|M\s*MAD)', raw, re.I)
    if m:
        try:
            val = float(m.group(1).replace(',', '.')) * 1_000_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

    k = re.search(r'([\d.,]+)\s*[Kk]', raw)
    if k:
        try:
            val = float(k.group(1).replace(',', '.')) * 1_000
            return round(val * EUR_TO_MAD if is_eur else val)
        except ValueError:
            pass

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
    raw_phones = _PHONE_RE.findall(text)
    phones = []
    for p in raw_phones:
        cleaned = re.sub(r'[\s.\-]', '', p)
        if cleaned.startswith('+212'):
            cleaned = '0' + cleaned[4:]
        elif cleaned.startswith('00212'):
            cleaned = '0' + cleaned[5:]
        elif cleaned.startswith('212'):
            cleaned = '0' + cleaned[3:]
        if re.match(r'^0[5-7]\d{8}$', cleaned) and cleaned not in phones:
            phones.append(cleaned)
    return phones[:2]


def _extract_email(text: str) -> str:
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else ''


def _detect_contact_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ('agence', 'immobilière', 'agency', 'promoteur',
                             'groupe', 'sarl', 'sas', 'cabinet', 'agenz',
                             'sarouty', 'mubawab', 'avito', 'annonceur')):
        return 'agence'
    if any(k in t for k in ('particulier', 'propriétaire', 'owner', 'privé')):
        return 'particulier'
    return ''


# ── Utilitaires localisation ──────────────────────────────────────────────────

VILLES_MAROC = [
    'casablanca', 'marrakech', 'rabat', 'fès', 'fes', 'tanger', 'agadir',
    'meknès', 'meknes', 'oujda', 'kénitra', 'kenitra', 'tétouan', 'tetouan',
    'salé', 'sale', 'mohammédia', 'mohammedia', 'temara', 'beni mellal',
    'el jadida', 'nador', 'settat', 'berrechid', 'khouribga', 'taroudant',
    'laâyoune', 'dakhla', 'safi', 'bouskoura', 'dar bouazza', 'ait melloul',
    'inezgane', 'essaouira', 'ouarzazate', 'errachidia', 'tiznit', 'ifrane',
    'marrakesh',
]


def _split_location(raw: str, avito_format: bool = False):
    parts = [p.strip() for p in re.split(r'[,\-–]', raw) if p.strip()]
    if len(parts) >= 2:
        if avito_format:
            city, dist = parts[0].title(), parts[1].title()
        else:
            city, dist = parts[-1].title(), parts[0].title()
        if city == dist:
            dist = ''
        return _clean_city(city), dist
    return _clean_city(raw.strip().title()), ''


def _clean_city(city: str) -> str:
    city = city.strip()
    if (len(city) < 3
            or re.search(r'\d', city)
            or city.startswith('%')
            or city.lower() in ('une', 'le', 'la', 'les', 'des', 'de', 'du', 'au', 'maroc')):
        return 'Maroc'
    return city


def _guess_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ('villa', 'maison', 'duplex', 'triplex', 'dar')):
        return 'villa'
    if 'riad' in t:
        return 'riad'
    if any(k in t for k in ('terrain', 'lot ', 'hectare', 'foncier')):
        return 'land'
    if any(k in t for k in ('bureau', 'local comm', 'magasin', 'commerce', 'boutique')):
        return 'office'
    if any(k in t for k in ('hôtel', 'hotel', 'résidence')):
        return 'hotel'
    return 'apartment'


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _delay(lo=1.2, hi=2.8):
    time.sleep(random.uniform(lo, hi))


def _get(session, url, timeout=25) -> Optional[BeautifulSoup]:
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
        'contact_name': '', 'contact_phone': '', 'contact_phone2': '',
        'contact_email': '', 'contact_agency': '', 'contact_type': '',
    }


def _make_listing(source, city, dist, ptype, title, price_mad, area_m2,
                  bedrooms, bathrooms, url, contact=None) -> dict:
    area_m2 = area_m2 if area_m2 and area_m2 > 0 else None
    result = {
        'source':           source,
        'city':             (city or 'Maroc')[:100],
        'district':         (dist or '')[:100],
        'property_type':    ptype,
        'title':            (title or '')[:300],
        'price_mad':        price_mad,
        'price_per_m2_mad': round(price_mad / area_m2) if area_m2 else None,
        'area_m2':          area_m2,
        'bedrooms':         bedrooms,
        'bathrooms':        bathrooms,
        'url':              (url or '')[:500],
        'scraped_at':       date.today().isoformat(),
    }
    result.update(contact or _empty_contact())
    return result


def _enrich_contact(session: requests.Session, listing: dict) -> dict:
    url = listing.get('url')
    if not url or not url.startswith('http'):
        return listing

    try:
        r = session.get(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            full_text = soup.get_text(' ')
            
            if not listing.get('contact_phone'):
                phones = _extract_phones(full_text)
                if phones:
                    listing['contact_phone'] = phones[0]
                    if len(phones) > 1:
                        listing['contact_phone2'] = phones[1]
                        
            if not listing.get('contact_email'):
                email = _extract_email(full_text)
                if email:
                    listing['contact_email'] = email
    except Exception as e:
        logger.debug(f"[Enrich Contact] {url} : {e}")
        
    return listing


# ══════════════════════════════════════════════════════════════════════════════
# 1. MUBAWAB
# ══════════════════════════════════════════════════════════════════════════════

class MubawabScraper:
    SOURCE = 'mubawab'
    CATEGORIES = [
        'appartements-a-vendre',
        'villas-a-vendre',
        'riads-a-vendre',
        'terrains-a-vendre',
        'bureaux-a-vendre',
    ]
    BASE = 'https://www.mubawab.ma/fr/sc/{cat}:p:{page}'

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
                        yield _enrich_contact(session, listing)
                if page < max_pages:
                    _delay()

    def _parse_card(self, card, cat: str) -> Optional[dict]:
        price_el = card.select_one('.priceTag')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else None
        if not price_mad:
            return None

        link_el = card.select_one('a[href*="mubawab.ma"]') or card.select_one('a')
        href = (link_el.get('href', '') if link_el else '').strip()
        title = (link_el.get_text(strip=True) if link_el else '')[:300]

        texts = [t.strip() for t in card.get_text(separator='|').split('|') if t.strip()]

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

        full_text = card.get_text(' ')
        phones = _extract_phones(full_text)
        email = _extract_email(full_text)

        # Agency / contact name visible sur la carte
        agency_el = card.select_one('.agencyName, .agency-name, .userName, .user-name, .agencyInfo')
        agency = agency_el.get_text(strip=True) if agency_el else ''

        contact = {
            'contact_phone':  phones[0] if phones else '',
            'contact_phone2': phones[1] if len(phones) > 1 else '',
            'contact_email':  email,
            'contact_agency': agency[:200],
            'contact_name':   agency[:200],
            'contact_type':   _detect_contact_type(agency + full_text),
        }
        return _make_listing(self.SOURCE, city or 'Maroc', dist,
                             _guess_type(cat + ' ' + title), title,
                             price_mad, area_m2, bedrooms, bathrooms, href, contact)


# ══════════════════════════════════════════════════════════════════════════════
# 2. AVITO
# ══════════════════════════════════════════════════════════════════════════════

class AvitoScraper:
    SOURCE = 'avito'
    BASE   = 'https://www.avito.ma/fr/maroc/immobilier-%C3%A0_vendre?o={page}'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for page in range(1, max_pages + 1):
            try:
                r = session.get(self.BASE.format(page=page), timeout=25)
                ads = self._extract_ads(r.text)
                if not ads:
                    soup = BeautifulSoup(r.text, 'lxml')
                    ads = self._extract_from_soup(soup)
                if not ads:
                    break
                for ad in ads:
                    listing = self._parse_ad(ad)
                    if listing:
                        if city_filter and city_filter.lower() not in listing['city'].lower():
                            continue
                        yield _enrich_contact(session, listing)
            except Exception as e:
                logger.warning(f'[Avito] page {page}: {e}')
                break
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
    def _extract_from_soup(soup: BeautifulSoup) -> list:
        cards = soup.select('article[data-testid], [data-testid="adListItem"]')
        return [{'_soup_card': c} for c in cards] if cards else []

    def _parse_ad(self, ad: dict) -> Optional[dict]:
        if '_soup_card' in ad:
            return self._parse_soup_card(ad['_soup_card'])

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

        seller = ad.get('seller', {}) or {}
        contact_name   = str(seller.get('name', '') or seller.get('store', '') or '')[:200]
        contact_agency = str(seller.get('store', '') or '')[:200]
        contact_type   = ('agence' if seller.get('type') == 'store'
                          else 'particulier' if seller.get('type') == 'private' else '')

        contact = {
            'contact_name':   contact_name,
            'contact_agency': contact_agency,
            'contact_type':   contact_type,
            'contact_phone':  '',
            'contact_phone2': '',
            'contact_email':  '',
        }
        return _make_listing(self.SOURCE, city or 'Maroc', dist,
                             _guess_type(title), title, price_mad,
                             area_m2, bedrooms, bathrooms, href, contact)

    def _parse_soup_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        price_mad = None
        for el in card.select('[class*="price"], [data-testid*="price"]'):
            price_mad = _parse_price_mad(el.get_text(strip=True))
            if price_mad:
                break
        if not price_mad:
            return None

        link  = card.select_one('a')
        href  = ('https://www.avito.ma' + link['href']) if link and link.get('href') else ''
        title = (link.get_text(strip=True) if link else '')[:300]
        area_m2 = _parse_area(text)

        return _make_listing(self.SOURCE, 'Maroc', '', _guess_type(title),
                             title, price_mad, area_m2, None, None, href)


# ══════════════════════════════════════════════════════════════════════════════
# 3. SAROUTY
# ══════════════════════════════════════════════════════════════════════════════

class SaroutyScraper:
    SOURCE = 'sarouty'
    # WordPress SSR pages
    PAGES_URLS = [
        'https://www.sarouty.ma/acheter/appartements-a-vendre/',
        'https://www.sarouty.ma/acheter/villas-a-vendre/',
        'https://www.sarouty.ma/acheter/terrains-a-vendre/',
        'https://www.sarouty.ma/acheter/bureaux-a-vendre/',
    ]

    def scrape(self, max_pages=3, city_filter='') -> Iterator[dict]:
        session = _new_session()
        # First visit homepage to get cookies
        try:
            session.get('https://www.sarouty.ma/', timeout=15)
        except Exception:
            pass

        for base_url in self.PAGES_URLS:
            for page in range(1, max_pages + 1):
                url = base_url if page == 1 else f'{base_url}?paged={page}'
                soup = _get(session, url)
                if not soup:
                    break

                listings = self._extract_listings(soup)
                if not listings:
                    break

                for listing in listings:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield _enrich_contact(session, listing)

                if page < max_pages:
                    _delay()

    def _extract_listings(self, soup: BeautifulSoup) -> list:
        results = []

        # Approach 1: find MUI listing boxes with data-listing-id
        # The page contains "NNN DH" price strings in the text
        text_blocks = soup.find_all(string=re.compile(r'[\d\s]+DH'))
        processed_ids = set()

        for text_node in text_blocks:
            try:
                price_mad = _parse_price_mad(text_node)
                if not price_mad:
                    continue

                # Walk up to find container
                container = text_node.parent
                for _ in range(6):
                    if container is None:
                        break
                    # Get all text from container to extract other fields
                    full_text = container.get_text(' ')
                    if 'm²' in full_text and len(full_text) > 50:
                        break
                    container = container.parent

                if not container:
                    continue

                full_text = container.get_text(' ')
                # Avoid duplicates
                key = full_text[:80]
                if key in processed_ids:
                    continue
                processed_ids.add(key)

                # Extract fields
                area_m2 = _parse_area(full_text)
                bedrooms_m = re.search(r'(\d+)\s*Chambres?', full_text)
                bathrooms_m = re.search(r'(\d+)\s*Salles?\s*de\s*bain', full_text)
                bedrooms  = int(bedrooms_m.group(1)) if bedrooms_m else None
                bathrooms = int(bathrooms_m.group(1)) if bathrooms_m else None

                # Location: look for known cities
                city = 'Maroc'
                district = ''
                for ville in VILLES_MAROC:
                    if ville in full_text.lower():
                        city = ville.title()
                        break

                # Title: longest line that looks like a title
                lines = [l.strip() for l in full_text.split('\n') if len(l.strip()) > 10]
                title = next((l for l in lines if not any(
                    k in l for k in ('DH', 'm²', 'Chambre', 'Salle', 'A acheter', 'Location')
                )), '')[:300]

                # Find link via parent
                link_tag = container.find('a', href=True)
                href = ''
                if link_tag:
                    href = link_tag['href']
                    if not href.startswith('http'):
                        href = 'https://www.sarouty.ma' + href

                # Contact type
                contact_type = _detect_contact_type(full_text)

                listing = _make_listing(
                    self.SOURCE, city, district,
                    _guess_type(title), title, price_mad,
                    area_m2, bedrooms, bathrooms, href,
                    {**_empty_contact(), 'contact_type': contact_type,
                     'contact_agency': 'Sarouty' if contact_type == 'agence' else ''}
                )
                results.append(listing)

            except Exception:
                continue

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 4. AGENZ
# ══════════════════════════════════════════════════════════════════════════════

class AgenzScraper:
    SOURCE = 'agenz'
    BASE   = 'https://agenz.ma/fr/acheter?page={page}'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        session.headers.update({'Referer': 'https://agenz.ma/'})

        for page in range(1, max_pages + 1):
            url = self.BASE.format(page=page)
            try:
                r = session.get(url, timeout=25)
                if r.status_code != 200:
                    break

                # Try JSON (Next.js __NEXT_DATA__)
                listings = self._extract_json(r.text)

                # Fallback: HTML parsing
                if not listings:
                    soup = BeautifulSoup(r.text, 'lxml')
                    listings = self._extract_html(soup)

                if not listings:
                    break

                for listing in listings:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield _enrich_contact(session, listing)

            except Exception as e:
                logger.warning(f'[Agenz] page {page}: {e}')
                break

            if page < max_pages:
                _delay()

    def _extract_json(self, html: str) -> list:
        """Tente d'extraire les annonces depuis __NEXT_DATA__."""
        try:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group(1))
            # Navigate the Agenz data structure
            props = data.get('props', {}).get('pageProps', {})
            items = (props.get('listings') or props.get('ads') or
                     props.get('properties') or props.get('data') or [])
            if not isinstance(items, list):
                return []

            results = []
            for item in items:
                listing = self._parse_json_item(item)
                if listing:
                    results.append(listing)
            return results
        except Exception:
            return []

    def _parse_json_item(self, item: dict) -> Optional[dict]:
        price = item.get('price') or item.get('prix') or item.get('price_mad')
        price_mad = _parse_price_mad(str(price)) if price else None
        if not price_mad:
            return None

        title    = str(item.get('title') or item.get('titre') or '')[:300]
        city     = str(item.get('city') or item.get('ville') or item.get('location', {}).get('city', '') or 'Maroc')
        district = str(item.get('district') or item.get('neighborhood') or item.get('quartier') or '')
        href     = str(item.get('url') or item.get('link') or item.get('slug') or '')
        if href and not href.startswith('http'):
            href = 'https://agenz.ma' + href

        area_m2   = _parse_area(str(item.get('area') or item.get('surface') or item.get('size') or ''))
        bedrooms  = _parse_int(str(item.get('bedrooms') or item.get('rooms') or item.get('chambres') or ''))
        bathrooms = _parse_int(str(item.get('bathrooms') or item.get('salles_bain') or ''))

        contact = item.get('agency') or item.get('agent') or {}
        agency_name = str(contact.get('name') or contact.get('agency_name') or '')[:200]

        return _make_listing(
            self.SOURCE, city[:100], district[:100],
            _guess_type(title), title, price_mad,
            area_m2, bedrooms, bathrooms, href,
            {**_empty_contact(), 'contact_agency': agency_name,
             'contact_name': agency_name, 'contact_type': 'agence' if agency_name else ''}
        )

    def _extract_html(self, soup: BeautifulSoup) -> list:
        """Extraction HTML : cherche les liens vers les annonces individuelles."""
        results = []
        seen = set()

        # Les liens de listing suivent le pattern /fr/annonces/immo-{ville}/.../{id}
        links = soup.select('a[href*="/fr/annonces/immo-"]')
        # Exclure les liens vidéo
        links = [a for a in links if '/video' not in a.get('href', '')]

        for link in links:
            href = link.get('href', '')
            if not href.startswith('http'):
                href = 'https://agenz.ma' + href
            if href in seen:
                continue
            seen.add(href)

            # Extraire ville / type depuis l'URL
            # Pattern: /fr/annonces/immo-{city}/vente-{type}/{district}/{id}
            url_m = re.search(r'/immo-([^/]+)/vente-([^/]+)/([^/]+)/(\d+)', href)
            city     = url_m.group(1).replace('-', ' ').title() if url_m else 'Maroc'
            ptype_str= url_m.group(2) if url_m else ''
            district = url_m.group(3).replace('-', ' ').title() if url_m else ''

            # Extraire les données du bloc parent
            container = link.parent
            for _ in range(5):
                if container is None:
                    break
                text = container.get_text(' ')
                if any(k in text for k in ('DH', 'm²')):
                    break
                container = container.parent

            if not container:
                continue

            full_text = container.get_text(' ')
            price_mad = None
            for m in re.finditer(r'([\d\s]+)\s*DH', full_text):
                price_mad = _parse_price_mad(m.group(0))
                if price_mad:
                    break
            if not price_mad:
                continue

            title     = link.get_text(strip=True)[:300] or href
            area_m2   = _parse_area(full_text)
            bedrooms  = _parse_int(re.search(r'(\d+)\s*CH', full_text).group(1)) if re.search(r'(\d+)\s*CH', full_text) else None
            bathrooms = _parse_int(re.search(r'(\d+)\s*SDB', full_text).group(1)) if re.search(r'(\d+)\s*SDB', full_text) else None

            results.append(_make_listing(
                self.SOURCE, city, district,
                _guess_type(ptype_str + ' ' + title), title,
                price_mad, area_m2, bedrooms, bathrooms, href
            ))

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 5. MAROCANNONCES
# ══════════════════════════════════════════════════════════════════════════════

class MarocAnnoncesScraper:
    SOURCE = 'marocannonces'
    # URL correcte pour la catégorie vente immobilier
    BASE   = 'https://www.marocannonces.com/categorie/16/Vente-immobilier.html?p={page}'

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for page in range(1, max_pages + 1):
            soup = _get(session, self.BASE.format(page=page))
            if not soup:
                break

            cards = soup.select('li.holder, .listing-item, .ann-item')
            if not cards:
                # Fallback : chercher des éléments avec prix
                cards = [li for li in soup.select('li')
                         if 'DH' in li.get_text() and li.select('a')]
            if not cards:
                break

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield _enrich_contact(session, listing)

            if page < max_pages:
                _delay()

    def _parse_card(self, card) -> Optional[dict]:
        text = card.get_text(' ')
        if not any(k in text.lower() for k in ('dh', 'mad', 'appartement', 'villa',
                                                'terrain', 'bureau', 'maison', 'immo')):
            return None

        price_el = card.select_one('.price, [class*="price"], b, strong, .prixann')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else _parse_price_mad(text)
        if not price_mad:
            return None

        link  = card.select_one('a[href*="marocannonces"]') or card.select_one('a')
        href  = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://www.marocannonces.com' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        # Localisation
        loc_el = card.select_one('.ville, .city, [class*="location"], [class*="ville"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        if not location_raw:
            # Try to find city from text
            for ville in VILLES_MAROC:
                if ville in text.lower():
                    location_raw = ville
                    break
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)

        contact = {
            'contact_phone':  phones[0] if phones else '',
            'contact_phone2': phones[1] if len(phones) > 1 else '',
            'contact_email':  email,
            'contact_name':   '',
            'contact_agency': '',
            'contact_type':   _detect_contact_type(text),
        }
        return _make_listing(self.SOURCE, city, dist,
                             _guess_type(title + ' ' + text), title,
                             price_mad, area_m2, None, None, href, contact)


# ══════════════════════════════════════════════════════════════════════════════
# 6. MASAKEN
# ══════════════════════════════════════════════════════════════════════════════

class MasakenScraper:
    SOURCE  = 'masaken'
    # Scraper par ville car pas d'URL globale fonctionnelle
    VILLES  = ['casablanca', 'marrakech', 'rabat', 'tanger', 'agadir',
               'fes', 'meknes', 'oujda', 'kenitra', 'tetouan', 'sale']
    TYPES   = ['appartement', 'villa', 'terrain']
    BASE    = 'https://www.masaken.ma/fr/vendre/{ptype}/{ville}'

    def scrape(self, max_pages=2, city_filter='') -> Iterator[dict]:
        session = _new_session()
        villes = [city_filter.lower()] if city_filter else self.VILLES

        for ville in villes:
            for ptype in self.TYPES:
                url = self.BASE.format(ptype=ptype, ville=ville)
                for page in range(1, max_pages + 1):
                    page_url = url if page == 1 else f'{url}?page={page}'
                    soup = _get(session, page_url)
                    if not soup:
                        break

                    listings = self._extract(soup, ville, ptype)
                    if not listings:
                        break

                    for listing in listings:
                        yield _enrich_contact(session, listing)

                    if page < max_pages:
                        _delay(0.8, 1.5)

    def _extract(self, soup: BeautifulSoup, ville: str, ptype: str) -> list:
        results = []
        seen = set()

        # Cherche tous les blocs avec prix MAD
        price_nodes = soup.find_all(string=re.compile(r'[\d\s.,]+\s*MAD'))
        for node in price_nodes:
            try:
                price_mad = _parse_price_mad(node)
                if not price_mad:
                    continue

                # Monter pour trouver le container
                container = node.parent
                for _ in range(8):
                    if container is None:
                        break
                    t = container.get_text(' ')
                    if 'm²' in t and len(t) > 30:
                        break
                    container = container.parent

                if not container:
                    continue

                full_text = container.get_text(' ')
                key = full_text[:60]
                if key in seen:
                    continue
                seen.add(key)

                area_m2  = _parse_area(full_text)
                bedrooms = _parse_int(re.search(r'(\d+)\s*(?:ch|chambre)', full_text, re.I).group(1)) if re.search(r'(\d+)\s*(?:ch|chambre)', full_text, re.I) else None

                link_tag = container.find('a', href=True)
                href = ''
                if link_tag:
                    href = link_tag['href']
                    if not href.startswith('http'):
                        href = 'https://www.masaken.ma' + href

                title_el = container.find(['h2', 'h3', 'h4', 'a'])
                title = (title_el.get_text(strip=True) if title_el else '')[:300]

                phones   = _extract_phones(full_text)
                contact  = {**_empty_contact(),
                            'contact_phone': phones[0] if phones else '',
                            'contact_phone2': phones[1] if len(phones) > 1 else ''}

                results.append(_make_listing(
                    self.SOURCE, ville.title(), '',
                    _guess_type(ptype), title, price_mad,
                    area_m2, bedrooms, None, href, contact
                ))
            except Exception:
                continue

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 7. LOGICIMMO (logicimmo.ma — agence prestige)
# ══════════════════════════════════════════════════════════════════════════════

class LogicImmoScraper:
    SOURCE = 'logicimmo'
    URLS   = [
        'https://logicimmo.ma/vente-appartement-maroc.html',
        'https://logicimmo.ma/vente-villa-maroc.html',
        'https://logicimmo.ma/vente-duplex-maroc.html',
        'https://logicimmo.ma/vente-loft-maroc.html',
    ]

    def scrape(self, max_pages=2, city_filter='') -> Iterator[dict]:
        session = _new_session()
        for base_url in self.URLS:
            for page in range(1, max_pages + 1):
                url = base_url if page == 1 else re.sub(r'\.html$', f'/page/{page}.html', base_url)
                soup = _get(session, url)
                if not soup:
                    break

                cards = soup.select('.sl-item.property-grid, .sl-item, [class*="property-grid"]')
                if not cards:
                    break

                for card in cards:
                    listing = self._parse_card(card)
                    if listing:
                        if city_filter and city_filter.lower() not in listing['city'].lower():
                            continue
                        yield _enrich_contact(session, listing)

                if page < max_pages:
                    _delay()

    def _parse_card(self, card) -> Optional[dict]:
        # Prix dans .property-info
        price_el = card.select_one('.price, [class*="price"], .amount')
        price_mad = _parse_price_mad(price_el.get_text(strip=True)) if price_el else None
        if not price_mad:
            # Chercher dans le texte complet
            text = card.get_text(' ')
            price_mad = _parse_price_mad(text)
        if not price_mad:
            return None

        # Lien detail
        link = card.select_one('a.view-detail, a[href*="vente"]') or card.select_one('a')
        href = link.get('href', '') if link else ''
        if href and not href.startswith('http'):
            href = 'https://logicimmo.ma' + href

        # Titre
        title_el = card.select_one('.property-info a, h2, h3, .title')
        title = (title_el.get_text(strip=True) if title_el else '')[:300]

        # Surface dans .image-bottom .left
        area_el = card.select_one('.image-bottom .left, [class*="size"], [class*="area"]')
        area_m2 = _parse_area(area_el.get_text(strip=True)) if area_el else _parse_area(card.get_text())

        # Chambres / SDB (icônes)
        right_el = card.select_one('.image-bottom .right')
        bedrooms = bathrooms = None
        if right_el:
            spans = right_el.select('span')
            if len(spans) >= 1:
                bedrooms = _parse_int(spans[0].get_text(strip=True))
            if len(spans) >= 2:
                bathrooms = _parse_int(spans[1].get_text(strip=True))

        # Localisation (dans le titre ou lien)
        city = 'Maroc'
        for ville in VILLES_MAROC:
            if ville in (title + href).lower():
                city = ville.title()
                break

        # Localisation depuis .location ou .address
        loc_el = card.select_one('[class*="location"], [class*="address"], [class*="quartier"]')
        district = loc_el.get_text(strip=True) if loc_el else ''

        return _make_listing(
            self.SOURCE, city, district,
            _guess_type(title), title, price_mad,
            area_m2, bedrooms, bathrooms, href,
            {**_empty_contact(), 'contact_agency': 'Logic-Immo.ma',
             'contact_type': 'agence'}
        )


# ══════════════════════════════════════════════════════════════════════════════
# 8. BIKHIR
# ══════════════════════════════════════════════════════════════════════════════

class BikhirScraper:
    SOURCE = 'bikhir'
    URLS   = [
        'https://www.bikhir.ma/annonces/immobilier/vente?page={page}',
        'https://www.bikhir.ma/fr/immobilier/vente?page={page}',
        'https://www.bikhir.ma/categorie/immobilier/vente?page={page}',
    ]

    def scrape(self, max_pages=5, city_filter='') -> Iterator[dict]:
        session = _new_session()
        working_url = None

        for url_tpl in self.URLS:
            soup = _get(session, url_tpl.format(page=1))
            if soup and soup.select('article, [class*="listing"], [class*="annonce"], [class*="property"]'):
                working_url = url_tpl
                break

        if not working_url:
            logger.warning('[Bikhir] Site inaccessible ou structure non reconnue')
            return

        for page in range(1, max_pages + 1):
            soup = _get(session, working_url.format(page=page))
            if not soup:
                break

            cards = (soup.select('[class*="listing"], [class*="annonce"], [class*="property"]')
                     or soup.select('article'))
            if not cards:
                break

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    if city_filter and city_filter.lower() not in listing['city'].lower():
                        continue
                    yield _enrich_contact(session, listing)

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
            href = 'https://www.bikhir.ma' + href
        title = (link.get_text(strip=True) if link else '')[:300]

        loc_el = card.select_one('[class*="loc"], [class*="city"], [class*="ville"]')
        location_raw = loc_el.get_text(strip=True) if loc_el else ''
        city, dist = _split_location(location_raw) if location_raw else ('Maroc', '')

        area_m2  = _parse_area(text)
        phones   = _extract_phones(text)
        email    = _extract_email(text)
        bedrooms = _parse_int(re.search(r'(\d+)\s*(?:ch|chambre)', text, re.I).group(1)) if re.search(r'(\d+)\s*(?:ch|chambre)', text, re.I) else None

        contact = {
            'contact_phone':  phones[0] if phones else '',
            'contact_phone2': phones[1] if len(phones) > 1 else '',
            'contact_email':  email,
            'contact_name':   '',
            'contact_agency': '',
            'contact_type':   _detect_contact_type(text),
        }
        return _make_listing(self.SOURCE, city, dist,
                             _guess_type(title), title, price_mad,
                             area_m2, bedrooms, None, href, contact)


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ══════════════════════════════════════════════════════════════════════════════

SCRAPERS = {
    'mubawab':      MubawabScraper,
    'avito':        AvitoScraper,
    'sarouty':      SaroutyScraper,
    'agenz':        AgenzScraper,
    'marocannonces': MarocAnnoncesScraper,
    'masaken':      MasakenScraper,
    'logicimmo':    LogicImmoScraper,
    'bikhir':       BikhirScraper,
}


def _is_opportunity(listing: dict) -> bool:
    ppm2 = listing.get('price_per_m2_mad')
    return bool(ppm2 and ppm2 < 9_000)


def scrape_all(sources: list = None, max_pages: int = 5,
               city_filter: str = '') -> Iterator[dict]:
    from properties.models import Property

    if sources is None:
        sources = list(SCRAPERS.keys())

    total_new = 0
    total_dup = 0

    for source_name in sources:
        cls = SCRAPERS.get(source_name)
        if not cls:
            logger.warning(f'[Scraper] Source inconnue : {source_name}')
            yield {
                'error': f'Source "{source_name}" non reconnue',
                'source': source_name,
                'is_new': False,
                'total_new': total_new,
                'total_dup': total_dup,
            }
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
                            source           = listing['source'],
                            city             = listing['city'],
                            district         = listing.get('district', ''),
                            property_type    = listing.get('property_type', 'apartment'),
                            title            = listing.get('title', ''),
                            price_mad        = listing['price_mad'],
                            price_per_m2_mad = listing.get('price_per_m2_mad'),
                            area_m2          = listing.get('area_m2'),
                            bedrooms         = listing.get('bedrooms'),
                            bathrooms        = listing.get('bathrooms'),
                            url              = url,
                            scraped_at       = date.today(),
                            is_opportunity   = listing.get('is_opportunity', False),
                            contact_name     = listing.get('contact_name', ''),
                            contact_phone    = listing.get('contact_phone', ''),
                            contact_phone2   = listing.get('contact_phone2', ''),
                            contact_email    = listing.get('contact_email', ''),
                            contact_agency   = listing.get('contact_agency', ''),
                            contact_type     = listing.get('contact_type', ''),
                        )
                        listing['id']     = prop.pk
                        listing['is_new'] = True
                        total_new += 1
                    except Exception as e:
                        logger.error(f'[DB] Erreur ({source_name}): {e}')
                        listing['is_new'] = False
                else:
                    listing['is_new'] = False
                    total_dup += 1

                listing['total_new'] = total_new
                listing['total_dup'] = total_dup
                yield _enrich_contact(session, listing)

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
