from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.crypto import get_random_string

from app.models import Profile
from app.utils import _generer_username_depuis_email


class Command(BaseCommand):
    """Crée un compte Super Admin (is_staff=True, is_superuser=True), actif et
    vérifié immédiatement — pas de passage par l'email de confirmation.

    Usage :
        python manage.py create_admin_account admin@exemple.com
        python manage.py create_admin_account admin@exemple.com --password monMotDePasse
    """
    help = "Crée un compte Super Admin avec un mot de passe temporaire (généré si omis)."

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help="Adresse email du compte admin.")
        parser.add_argument('--password', type=str, default=None, help="Mot de passe temporaire (généré aléatoirement si omis).")

    def handle(self, *args, **options):
        email = options['email'].strip()
        try:
            validate_email(email)
        except DjangoValidationError:
            raise CommandError(f"Adresse email invalide : « {email} ».")

        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"Un compte existe déjà pour l'email « {email} ».")

        password = options['password'] or get_random_string(14)

        username = _generer_username_depuis_email(email)
        user = User.objects.create_user(
            username=username, email=email, password=password,
            is_active=True, is_staff=True, is_superuser=True,
        )
        Profile.objects.create(user=user, is_verified=True)

        self.stdout.write(self.style.SUCCESS(f"Super Admin créé : {email} (username={username})"))
        self.stdout.write(self.style.SUCCESS(f"Mot de passe temporaire : {password}"))
        self.stdout.write(self.style.WARNING("À changer dès la première connexion (page Profil)."))
