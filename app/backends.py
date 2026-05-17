from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailOrUsernameBackend(ModelBackend):
    """
    Permet la connexion avec email OU username + password.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # Chercher par username d'abord
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # Essayer par email
            try:
                user = User.objects.get(email__iexact=username)
            except User.DoesNotExist:
                return None
            except User.MultipleObjectsReturned:
                # Si plusieurs comptes ont le même email, prendre le premier actif
                user = User.objects.filter(email__iexact=username, is_active=True).first()
                if not user:
                    return None

        # Vérifier le mot de passe
        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None