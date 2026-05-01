import logging
import threading
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.signing import dumps, loads, BadSignature
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.conf import settings
from .forms import RegisterForm, ProfileForm

logger = logging.getLogger(__name__)


def _send_email_async(subject, message, from_email, recipient, html_message, log_tag='Email'):
    """
    Envoie un email dans un thread daemon pour ne pas bloquer la vue HTTP.
    SMTP peut prendre 30-120s sur Render — cette fonction évite le timeout gunicorn.
    """
    def _send():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=[recipient],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f'[{log_tag}] Email envoye a {recipient}')
        except Exception as e:
            logger.error(f'[{log_tag}] ERREUR SMTP ({type(e).__name__}) pour {recipient}: {e}')
    t = threading.Thread(target=_send, daemon=True)
    t.start()


def register_view(request):
    if request.user.is_authenticated:
        return redirect('predictions:form')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Désactivé jusqu'à vérification email
            user.save()
            form.save_m2m()

            # Générer le token de vérification (valide 24h)
            token = dumps(user.pk, salt='email-verification-orchiimmo')
            verify_url = request.build_absolute_uri(
                reverse('accounts:verify_email', args=[token])
            )

            # Envoyer l'email en arrière-plan (évite de bloquer la réponse HTTP)
            try:
                html_body = render_to_string('accounts/emails/verification_email.html', {
                    'user': user,
                    'verify_url': verify_url,
                })
            except Exception as e:
                logger.error(f'[Email] Erreur rendu template: {e}')
                html_body = None

            _send_email_async(
                subject='✅ Vérifiez votre compte Orchiimmo',
                message=f'Bonjour {user.first_name},\n\nCliquez ici pour vérifier votre compte :\n{verify_url}\n\nCe lien expire dans 24 heures.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient=user.email,
                html_message=html_body,
                log_tag='Verification',
            )

            return redirect('accounts:verification_sent')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form})


def verify_email_view(request, token):
    """Active le compte après clic sur le lien de vérification."""
    try:
        user_pk = loads(token, salt='email-verification-orchiimmo', max_age=86400)
        user = User.objects.get(pk=user_pk)
        if not user.is_active:
            user.is_active = True
            user.save()
        login(request, user)
        messages.success(request, f'Bienvenue {user.first_name} ! Votre compte est vérifié ✅')
        return redirect('predictions:form')
    except (BadSignature, User.DoesNotExist, Exception):
        return render(request, 'accounts/email_verified.html', {'error': True})


def verification_sent_view(request):
    """Page informant l'utilisateur de vérifier son email."""
    return render(request, 'accounts/email_verification_sent.html')


def resend_verification_view(request):
    """Renvoie l'email de vérification pour un username donné."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        try:
            user = User.objects.get(username=username, is_active=False)
            token = dumps(user.pk, salt='email-verification-orchiimmo')
            verify_url = request.build_absolute_uri(
                reverse('accounts:verify_email', args=[token])
            )
            try:
                html_body = render_to_string('accounts/emails/verification_email.html', {
                    'user': user, 'verify_url': verify_url,
                })
            except Exception as e:
                logger.error(f'[Email] Erreur rendu template renvoi: {e}')
                html_body = None

            _send_email_async(
                subject='✅ Vérifiez votre compte Orchiimmo',
                message=f'Lien de vérification : {verify_url}',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient=user.email,
                html_message=html_body,
                log_tag='Renvoi',
            )
            messages.success(request, f'Email renvoyé à {user.email}')
        except User.DoesNotExist:
            messages.error(request, 'Compte introuvable ou déjà activé.')
    return redirect('accounts:verification_sent')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('predictions:form')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            next_url = request.GET.get('next', 'predictions:form')
            return redirect(next_url)
        else:
            # Vérifier si le compte existe mais est inactif (non vérifié)
            try:
                inactive_user = User.objects.get(username=username, is_active=False)
                messages.warning(
                    request,
                    f'Compte non activé. Vérifiez votre email ({inactive_user.email}). '
                    f'<a href="{reverse("accounts:verification_sent")}">Renvoyer l\'email</a>'
                )
            except User.DoesNotExist:
                messages.error(request, 'Identifiants incorrects. Veuillez réessayer.')
    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    messages.info(request, 'Vous avez été déconnecté.')
    return redirect('home')


@login_required
def profile_view(request):
    profile = request.user.profile
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profil mis à jour avec succès.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=profile)
    predictions = request.user.predictions.order_by('-created_at')[:10]
    return render(request, 'accounts/profile.html', {
        'form': form,
        'predictions': predictions,
    })
