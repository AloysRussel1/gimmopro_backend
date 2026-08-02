from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from app.models import Profile


class Command(BaseCommand):
    """Active manuellement un compte (is_active=True + Profile.is_verified=True)
    sans passer par le lien reçu par email — utile quand l'envoi SMTP est en
    panne et qu'on a besoin de tester/débloquer un compte immédiatement.

    Usage :
        python manage.py activate_user quelquun@email.com
    """
    help = "Active manuellement un compte utilisateur par email, en contournant la vérification par email."

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help="Adresse email du compte à activer.")

    def handle(self, *args, **options):
        email = options['email'].strip()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"Aucun compte trouvé pour l'email « {email} ».")
        except User.MultipleObjectsReturned:
            raise CommandError(
                f"Plusieurs comptes partagent l'email « {email} » — "
                "active-les individuellement via l'admin Django (/admin/)."
            )

        if user.is_active:
            self.stdout.write(self.style.WARNING(f"{email} (username={user.username}) est déjà actif — rien à faire."))
            return

        user.is_active = True
        user.save(update_fields=['is_active'])

        profile, _ = Profile.objects.get_or_create(user=user)
        if not profile.is_verified:
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])

        self.stdout.write(self.style.SUCCESS(
            f"{email} (username={user.username}) activé avec succès. Connexion possible dès maintenant."
        ))
