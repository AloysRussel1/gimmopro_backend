"""Utilitaires de formatage pour les documents PDF (contrats, reçus)
et de cloisonnement multi-utilisateur (chaque requête n'accède qu'à
ses propres données)."""
import re
from django.core import signing
from django.shortcuts import get_object_or_404


def _generer_username_depuis_email(email):
    """Django's built-in User a toujours besoin d'un username unique en interne
    (changer AUTH_USER_MODEL en cours de route serait une opération très risquée
    sur une base qui a déjà des migrations et des données réelles). On le dérive
    donc automatiquement de l'email — l'utilisateur, lui, ne voit et ne saisit
    plus jamais que son adresse email. Partagé par RegisterView et la commande
    create_admin_account."""
    from django.contrib.auth.models import User
    base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0].lower()) or 'user'
    username = base
    i = 1
    while User.objects.filter(username=username).exists():
        i += 1
        username = f"{base}{i}"
    return username


def log_activity(user, action, description=''):
    """Journal des actions clés (inscription, connexion, activation/
    désactivation de compte) — jamais bloquant : une erreur ici ne doit
    jamais faire échouer l'action métier qu'elle enregistre."""
    from .models import ActivityLog
    try:
        ActivityLog.objects.create(user=user, action=action, description=description)
    except Exception:
        pass


# ── Cloisonnement multi-tenant ──────────────────────────────────────
# Source unique de vérité pour le filtrage par propriétaire : toute vue qui
# a besoin d'un Logement / Compartiment / Occupant / Paiement DOIT passer par
# une de ces fonctions plutôt que par get_object_or_404() brut, sinon elle
# expose les données de tous les utilisateurs (IDOR).

def get_logement_or_404(user, logement_id):
    from .models import Logement
    return get_object_or_404(Logement, id=logement_id, proprietaire=user)


def get_compartiment_or_404(user, compartiment_id):
    from .models import Compartiment
    return get_object_or_404(Compartiment, id=compartiment_id, logement__proprietaire=user)


def get_occupant_or_404(user, occupant_id):
    from .models import Occupant
    return get_object_or_404(Occupant, id=occupant_id, proprietaire=user)


def get_paiement_or_404(user, paiement_id):
    from .models import Paiement
    return get_object_or_404(Paiement, id=paiement_id, occupant__proprietaire=user)


def get_depense_or_404(user, depense_id):
    from .models import Depense
    return get_object_or_404(Depense, id=depense_id, logement__proprietaire=user)


def get_document_or_404(user, document_id):
    from .models import Document
    return get_object_or_404(Document, id=document_id, proprietaire=user)


def get_etat_des_lieux_or_404(user, edl_id):
    from .models import EtatDesLieux
    return get_object_or_404(EtatDesLieux, id=edl_id, proprietaire=user)

_UNITS = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
          "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
          "dix-sept", "dix-huit", "dix-neuf"]
_TENS = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante", "", "quatre-vingt", ""]


def _deux_chiffres(n, terminal=True):
    """`terminal` = rien d'autre ne suit ce groupe dans le nombre complet.
    'vingt' ne prend un 's' que si terminal (ex: quatre-vingts vs quatre-vingt mille)."""
    if n < 20:
        return _UNITS[n]
    t, u = divmod(n, 10)
    if t == 7:
        return f"soixante-{_UNITS[10 + u]}" if u else "soixante-dix"
    if t == 9:
        return f"quatre-vingt-{_UNITS[10 + u]}" if u else "quatre-vingt-dix"
    base = _TENS[t]
    if t == 8 and u == 0 and terminal:
        base += "s"
    if u == 0:
        return base
    if u == 1 and t != 8:
        return f"{base}-et-un"
    return f"{base}-{_UNITS[u]}"


def _trois_chiffres(n, terminal=True):
    """Même règle pour 'cent' : pluriel seulement si rien ne suit (ex: deux cents
    mais deux cent mille)."""
    c, r = divmod(n, 100)
    if c == 0:
        return _deux_chiffres(r, terminal)
    prefix = "cent" if c == 1 else f"{_UNITS[c]} cent"
    if r == 0:
        return prefix + ("s" if (c > 1 and terminal) else "")
    return f"{prefix} {_deux_chiffres(r, terminal)}"


def nombre_en_lettres(n: int) -> str:
    """Convertit un entier en son écriture en toutes lettres (français)."""
    if n == 0:
        return "zéro"
    if n < 0:
        return f"moins {nombre_en_lettres(-n)}"

    scales = ["", "mille", "million", "milliard"]
    groups = []
    temp = n
    idx = 0
    while temp > 0:
        temp, group = divmod(temp, 1000)
        if group:
            groups.append((group, idx))
        idx += 1

    words = []
    for group, idx in reversed(groups):
        terminal = idx == 0  # rien après ce groupe seulement s'il s'agit des unités finales
        if idx == 0:
            words.append(_trois_chiffres(group, terminal))
        elif idx == 1:
            words.append("mille" if group == 1 else f"{_trois_chiffres(group, terminal)} mille")
        else:
            scale = scales[idx] if idx < len(scales) else f"×1000^{idx}"
            words.append(f"{_trois_chiffres(group, terminal)} {scale}{'s' if group > 1 else ''}")
    return " ".join(words)


def montant_en_lettres_fcfa(montant) -> str:
    """Ex: 125000 -> 'cent vingt-cinq mille francs CFA'."""
    return f"{nombre_en_lettres(int(montant))} francs CFA"


# ── Liens publics de reçu (signés, sans authentification) ──────────
_RECU_SALT = "gimmopro.recu-public"
RECU_TOKEN_MAX_AGE = 60 * 60 * 24 * 14  # 14 jours


def make_recu_token(paiement_id: int) -> str:
    return signing.TimestampSigner(salt=_RECU_SALT).sign(str(paiement_id))


def verify_recu_token(paiement_id: int, token: str) -> bool:
    try:
        value = signing.TimestampSigner(salt=_RECU_SALT).unsign(token, max_age=RECU_TOKEN_MAX_AGE)
        return int(value) == int(paiement_id)
    except (signing.BadSignature, signing.SignatureExpired, ValueError):
        return False


# ── Réinitialisation de mot de passe ────────────────────────────────
_RESET_SALT = "gimmopro.password-reset"
RESET_TOKEN_MAX_AGE = 60 * 60 * 2  # 2 heures


def make_password_reset_token(user) -> str:
    """Le token embarque un fragment du hash du mot de passe courant :
    dès que le mot de passe change (reset utilisé, ou changé autrement),
    tout token émis avant devient automatiquement invalide — usage unique
    de facto, sans avoir besoin de stocker les tokens en base."""
    payload = f"{user.pk}:{user.password[-12:]}"
    return signing.TimestampSigner(salt=_RESET_SALT).sign(payload)


def verify_password_reset_token(token: str, user_model):
    try:
        value = signing.TimestampSigner(salt=_RESET_SALT).unsign(token, max_age=RESET_TOKEN_MAX_AGE)
        user_id_str, hash_fragment = value.split(':', 1)
        user = user_model.objects.get(pk=int(user_id_str))
        if user.password[-12:] != hash_fragment:
            return None  # mot de passe déjà changé depuis l'émission du lien
        return user
    except (signing.BadSignature, signing.SignatureExpired, ValueError, user_model.DoesNotExist):
        return None


# ── Vérification d'adresse email ────────────────────────────────────
_VERIFY_SALT = "gimmopro.email-verify"
VERIFY_TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 jours


def make_email_verify_token(user) -> str:
    return signing.TimestampSigner(salt=_VERIFY_SALT).sign(str(user.pk))


def verify_email_verify_token(token: str, user_model):
    try:
        value = signing.TimestampSigner(salt=_VERIFY_SALT).unsign(token, max_age=VERIFY_TOKEN_MAX_AGE)
        return user_model.objects.get(pk=int(value))
    except (signing.BadSignature, signing.SignatureExpired, ValueError, user_model.DoesNotExist):
        return None


# ── Envoi des emails ─────────────────────────────────────────────────
# EMAIL_BACKEND est "console" par défaut (voir settings.py) : les emails
# s'affichent dans les logs du serveur en local/dev. Il faut brancher un
# vrai fournisseur (SMTP, SendGrid, etc.) via les variables d'environnement
# avant la mise en production — sans ça, aucun email n'est réellement livré.

def envoyer_email_reset_password(user, token):
    from django.conf import settings
    from django.core.mail import send_mail
    lien = f"{settings.FRONTEND_URL}/reinitialiser-mot-de-passe?token={token}"
    send_mail(
        subject="Réinitialisation de votre mot de passe Gimmopro",
        message=(
            "Bonjour,\n\n"
            "Vous avez demandé la réinitialisation de votre mot de passe Gimmopro.\n"
            f"Cliquez sur ce lien pour choisir un nouveau mot de passe (valable 2 heures) :\n{lien}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email — "
            "votre mot de passe actuel reste inchangé."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def envoyer_email_verification(user, token):
    from django.conf import settings
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    lien = f"{settings.FRONTEND_URL}/verifier-email?token={token}"
    html_message = render_to_string('app/email_verification.html', {'lien': lien})
    send_mail(
        subject="Confirmez votre adresse email — Gimmopro",
        message=(
            "Bienvenue sur Gimmopro !\n\n"
            f"Confirmez votre adresse email en cliquant sur ce lien (valable 7 jours) :\n{lien}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_message,
        fail_silently=False,
    )
