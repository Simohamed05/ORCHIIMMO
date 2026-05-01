"""
config/brevo_backend.py
Backend email Django utilisant l'API REST de Brevo (HTTPS port 443).

Pourquoi ne pas utiliser SMTP ?
  Render free tier bloque les connexions SMTP sortantes (ports 465 et 587).
  L'API REST utilise HTTPS (port 443), toujours disponible.

Utilisation dans settings_prod.py :
  EMAIL_BACKEND = 'config.brevo_backend.BrevoAPIBackend'
  BREVO_API_KEY = config('BREVO_API_KEY')
"""
import logging
import requests as _requests
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


def _parse_address(address: str) -> dict:
    """Convertit 'Nom <email>' ou 'email' en dict Brevo {name, email}."""
    address = address.strip()
    if '<' in address:
        name, rest = address.rsplit('<', 1)
        return {'name': name.strip(), 'email': rest.rstrip('>').strip()}
    return {'email': address}


class BrevoAPIBackend(BaseEmailBackend):
    """
    Backend Django qui envoie les emails via l'API REST Brevo.
    Compatible avec send_mail(), EmailMessage et EmailMultiAlternatives.
    """

    def __init__(self, api_key=None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or getattr(settings, 'BREVO_API_KEY', '')

    def send_messages(self, email_messages):
        if not self.api_key:
            logger.error('[BrevoAPI] BREVO_API_KEY non configurée — emails non envoyés')
            return 0

        num_sent = 0
        for message in email_messages:
            try:
                # Expéditeur
                sender = _parse_address(message.from_email)

                # Destinataires
                to_list = [_parse_address(r) for r in message.to]
                if not to_list:
                    continue

                payload = {
                    'sender':      sender,
                    'to':          to_list,
                    'subject':     message.subject,
                    'textContent': message.body,
                }

                # Corps HTML (EmailMultiAlternatives)
                for content, mimetype in getattr(message, 'alternatives', []):
                    if mimetype == 'text/html':
                        payload['htmlContent'] = content
                        break

                # Destinataires CC / BCC
                if message.cc:
                    payload['cc'] = [_parse_address(r) for r in message.cc]
                if message.bcc:
                    payload['bcc'] = [_parse_address(r) for r in message.bcc]

                resp = _requests.post(
                    BREVO_API_URL,
                    headers={
                        'accept':       'application/json',
                        'api-key':      self.api_key,
                        'content-type': 'application/json',
                    },
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                logger.info(f'[BrevoAPI] Email envoyé à {message.to} — messageId: {resp.json().get("messageId")}')
                num_sent += 1

            except _requests.HTTPError as e:
                logger.error(
                    f'[BrevoAPI] Erreur HTTP {e.response.status_code} pour {message.to}: '
                    f'{e.response.text}'
                )
                if not self.fail_silently:
                    raise
            except Exception as e:
                logger.error(f'[BrevoAPI] Erreur pour {message.to}: {type(e).__name__}: {e}')
                if not self.fail_silently:
                    raise

        return num_sent
