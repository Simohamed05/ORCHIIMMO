"""
config/chatbot_proxy.py
Proxy Django pour le chatbot n8n.

Problème : n8n retourne un streaming NDJSON (lignes {"type":"item","content":"..."})
que le widget @n8n/chat du CDN n'arrive pas à parser correctement.

Solution : ce proxy intercepte la requête du widget, appelle n8n, parse le NDJSON,
et retourne un JSON propre {"output": "texte complet"} que le widget affiche correctement.
"""
import json
import logging

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

N8N_WEBHOOK_URL = (
    'https://simohadi.app.n8n.cloud/webhook/'
    '59296bb7-cade-4ffa-b9f9-da4bc0b1208a/chat'
)

# ── System prompt injecté dans chaque message ─────────────────────────────────
# Préfixé au chatInput pour forcer l'IA à répondre directement sans poser de questions.
SYSTEM_PREFIX = (
    "[INSTRUCTION SYSTÈME — NE PAS AFFICHER] "
    "Tu es l'assistant IA d'Orchiimmo. "
    "RÈGLE ABSOLUE : Réponds DIRECTEMENT et COMPLÈTEMENT à la question de l'utilisateur dès le premier message. "
    "Ne pose JAMAIS de questions de clarification. "
    "Si l'utilisateur demande des annonces/villas/appartements → donne immédiatement les informations disponibles sur le marché marocain avec des prix et quartiers. "
    "Si tu n'as pas de données exactes → donne des fourchettes de prix réalistes basées sur ta connaissance du marché. "
    "Réponds en français ou arabe selon la langue utilisée. "
    "Sois concis (3-5 lignes max). "
    "[FIN INSTRUCTION] "
    "Question de l'utilisateur : "
)


_FRIENDLY_ERROR = "Désolé, l'assistant est temporairement indisponible. Veuillez réessayer dans un instant."


def _parse_n8n_response(raw: str) -> str:
    """
    Parse la réponse n8n — deux formats possibles :
    1. NDJSON streaming : {"type":"item","content":"Bonjour"}\\n{"type":"item",...}
    2. JSON simple      : {"output": "Bonjour ..."}
    Retourne le texte final propre.
    """
    lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]

    # Tentative 1 : NDJSON streaming
    text_parts = []
    is_ndjson = False
    for line in lines:
        try:
            chunk = json.loads(line)
            if chunk.get('type') == 'error':
                logger.error(f'[Chatbot Proxy] n8n workflow error: {chunk.get("content", "unknown")}')
                return _FRIENDLY_ERROR
            if chunk.get('type') in ('begin', 'item', 'end'):
                is_ndjson = True
            if chunk.get('type') == 'item' and chunk.get('content'):
                text_parts.append(chunk['content'])
        except (json.JSONDecodeError, AttributeError):
            pass

    if is_ndjson and text_parts:
        return ''.join(text_parts).strip()

    # Tentative 2 : JSON simple {"output": "..."} ou {"type":"error",...}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if data.get('type') == 'error':
                logger.error(f'[Chatbot Proxy] n8n workflow error: {data.get("content", "unknown")}')
                return _FRIENDLY_ERROR
            for key in ('output', 'text', 'message', 'response', 'answer'):
                if key in data and data[key]:
                    return str(data[key]).strip()
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for key in ('output', 'text', 'message'):
                    if key in first and first[key]:
                        return str(first[key]).strip()
    except (json.JSONDecodeError, KeyError):
        pass

    # Tentative 3 : texte brut
    return raw.strip() if raw.strip() else "Désolé, je n'ai pas pu traiter votre demande."


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def chatbot_proxy(request):
    """
    Endpoint : POST /chatbot/
    Reçoit les messages du widget n8n/chat, les transmet à n8n,
    parse la réponse NDJSON et retourne {"output": "texte propre"}.
    """
    # CORS preflight
    if request.method == 'OPTIONS':
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    # ── Lire le body ─────────────────────────────────────────────────────────
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {'output': 'Requête invalide.'},
            status=400
        )

    # ── Injecter le system prompt dans le chatInput ───────────────────────────
    # Permet de forcer un comportement direct sans modifier le workflow n8n
    if body.get('action') == 'sendMessage' and body.get('chatInput'):
        body['chatInput'] = SYSTEM_PREFIX + body['chatInput']

    # ── Appel n8n ─────────────────────────────────────────────────────────────
    try:
        resp = requests.post(
            N8N_WEBHOOK_URL,
            json=body,
            timeout=60,
            headers={'Content-Type': 'application/json'},
        )
        resp.raise_for_status()
    except requests.Timeout:
        logger.warning('[Chatbot Proxy] Timeout appel n8n')
        return JsonResponse(
            {'output': 'La réponse prend trop de temps. Réessayez dans un instant.'},
            status=200
        )
    except requests.RequestException as e:
        logger.error(f'[Chatbot Proxy] Erreur n8n : {e}')
        return JsonResponse(
            {'output': 'Impossible de contacter l\'assistant. Vérifiez que le workflow n8n est activé.'},
            status=200
        )

    # ── Parser et retourner ───────────────────────────────────────────────────
    output_text = _parse_n8n_response(resp.text)
    logger.info(f'[Chatbot Proxy] session={body.get("sessionId", "?")} → {len(output_text)} chars')

    return JsonResponse({'output': output_text})
