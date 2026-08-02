import logging

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

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

        # Chercher par username d'abord
        try:
            user = User.objects.get(username=username)
            logger.warning("  -> trouvé par USERNAME exact : id=%s email=%r is_active=%s", user.id, user.email, user.is_active)
        except User.DoesNotExist:
            # Essayer par email
            try:
                user = User.objects.get(email__iexact=username)
                logger.warning("  -> trouvé par EMAIL (iexact) : id=%s username=%r is_active=%s", user.id, user.username, user.is_active)
            except User.DoesNotExist:
                logger.warning("  -> rejeté : aucun compte ne correspond ni par username ni par email")
                return None
            except User.MultipleObjectsReturned:
                # Si plusieurs comptes ont le même email, prendre le premier actif
                doublons = list(User.objects.filter(email__iexact=username).values_list('id', 'username', 'is_active'))
                logger.warning("  -> PLUSIEURS comptes partagent cet email : %s", doublons)
                user = User.objects.filter(email__iexact=username, is_active=True).first()
                if not user:
                    logger.warning("  -> rejeté : aucun des comptes en doublon n'est actif")
                    return None
                logger.warning("  -> retenu parmi les doublons : id=%s", user.id)

        # Vérifier le mot de passe
        pwd_ok = user.check_password(password)
        can_auth = self.user_can_authenticate(user)
        logger.warning("  -> check_password=%s, user_can_authenticate (is_active)=%s", pwd_ok, can_auth)

        if pwd_ok and can_auth:
            logger.warning("  -> AUTHENTIFIÉ : id=%s", user.id)
            return user

        logger.warning("  -> rejeté : mot de passe incorrect ou compte inactif")
        return None