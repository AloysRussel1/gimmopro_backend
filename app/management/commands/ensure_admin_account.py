import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from app.models import Profile
from app.utils import _generer_username_depuis_email


class Command(BaseCommand):
    """Garantit qu'un compte Super Admin de secours existe et est actif, à
    partir des variables d'environnement SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD.
    Ne fait RIEN si elles ne sont pas définies -- pas de secret en dur dans le
    code (un mot de passe committé dans l'historique Git y reste pour
    toujours, même après suppression ultérieure du fichier).

    Idempotent et pensé pour tourner à CHAQUE démarrage (voir Procfile) :
    - Si le compte n'existe pas -> il est créé.
    - S'il existe mais n'est pas correctement configuré (inactif / pas admin,
      ex: après un redémarrage sur une base qui s'est révélée non-persistante)
      -> il est réparé, mot de passe resynchronisé depuis la variable d'env.
    - S'il existe et est déjà correctement configuré -> rien n'est touché,
      surtout PAS le mot de passe (on ne doit jamais écraser un mot de passe
      que l'utilisateur aurait changé depuis dans l'app).
    """
    help = "Crée/répare un compte Super Admin de secours depuis SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD (no-op si absentes)."

    def handle(self, *args, **options):
        email    = os.environ.get('SUPERADMIN_EMAIL', '').strip()
        password = os.environ.get('SUPERADMIN_PASSWORD', '')

        if not email or not password:
            self.stdout.write("SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD non définies -- aucun compte de secours géré.")
            return

        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            username = _generer_username_depuis_email(email)
            user = User.objects.create_user(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Compte Super Admin de secours créé : {email} (username={username})"))
        elif not (user.is_active and user.is_staff and user.is_superuser):
            user.set_password(password)
            self.stdout.write(self.style.WARNING(
                f"Compte {email} trouvé mais mal configuré (is_active={user.is_active}, "
                f"is_staff={user.is_staff}, is_superuser={user.is_superuser}) -- réparé, mot de passe resynchronisé."
            ))
        else:
            self.stdout.write(f"Compte Super Admin {email} déjà correctement configuré -- rien à faire.")
            return

        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save()

        profile, created_profile = Profile.objects.get_or_create(user=user, defaults={'is_verified': True})
        if not created_profile and not profile.is_verified:
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])
