import logging

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

logger = logging.getLogger(__name__)


class EmailOrUsernameBackend(ModelBackend):
    """
    Permet la connexion avec email OU username + password.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Log de diagnostic temporaire — jamais le mot de passe en clair,
        # juste sa longueur pour détecter un problème d'encodage/espace parasite
        # sans jamais faire fuiter le secret dans les logs.
        logger.warning(
            "EmailOrUsernameBackend.authenticate() reçu : identifiant=%r, longueur mot de passe=%s",
            username, len(password) if password else None,
        )

        if username is None or password is None:
            logger.warning("  -> rejeté : identifiant ou mot de passe manquant")
            return None

        # Une seule requête, insensible à la casse sur LES DEUX champs — avant,
        # seule la recherche par email était __iexact ; la recherche par
        # username exigeait une casse parfaite, ce qui pouvait à tort rejeter
        # un identifiant saisi avec une casse différente de celle enregistrée.
        candidats = list(User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)))
        logger.warning(
            "  -> %d compte(s) correspondant à %r (username ou email, insensible à la casse) : %s",
            len(candidats), username, [(u.id, u.username, u.email, u.is_active) for u in candidats],
        )

        if not candidats:
            logger.warning("  -> rejeté : aucun compte ne correspond ni par username ni par email")
            return None

        if len(candidats) == 1:
            user = candidats[0]
        else:
            # Doublon (ex: plusieurs comptes partageant le même email — le
            # User model par défaut de Django n'a pas de contrainte d'unicité
            # dessus). Priorité à une correspondance EXACTE de username, puis
            # à un compte actif, dans cet ordre.
            exact = [u for u in candidats if u.username.lower() == username.strip().lower()]
            pool = exact or candidats
            actifs = [u for u in pool if u.is_active]
            user = (actifs or pool)[0]
            logger.warning("  -> PLUSIEURS comptes correspondaient, retenu : id=%s", user.id)

        # Vérifier le mot de passe
        pwd_ok = user.check_password(password)
        can_auth = self.user_can_authenticate(user)
        logger.warning("  -> check_password=%s, user_can_authenticate (is_active)=%s", pwd_ok, can_auth)

        if pwd_ok and can_auth:
            logger.warning("  -> AUTHENTIFIÉ : id=%s", user.id)
            return user

        logger.warning("  -> rejeté : mot de passe incorrect ou compte inactif")
        return None