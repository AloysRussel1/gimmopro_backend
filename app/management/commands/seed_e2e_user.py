from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from app.models import Logement, Occupant, Profile

EMAIL = 'e2e.test@gimmopro.local'
PASSWORD = 'CypressTest123!'


class Command(BaseCommand):
    """Crée/réinitialise un compte de test actif, à identifiants fixes et
    connus, utilisé UNIQUEMENT par la suite Cypress locale pour se connecter
    sans dépendre d'un vrai envoi d'email (que Cypress ne peut pas lire).
    Refuse de s'exécuter si DEBUG=False -- ce compte a un mot de passe
    public (visible dans ce fichier), il ne doit jamais exister en
    production. Idempotent : réinitialise aussi les données métier du
    compte pour repartir d'un état propre à chaque exécution du test."""
    help = "Crée/réinitialise le compte de test E2E Cypress (refuse si DEBUG=False)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Refusé : DEBUG=False (ce compte de test ne doit jamais exister en production).")

        user, _ = User.objects.get_or_create(email=EMAIL, defaults={'username': 'e2e_test'})
        user.set_password(PASSWORD)
        user.is_active = True
        user.save()

        Profile.objects.update_or_create(
            user=user, defaults={'is_verified': True, 'terms_accepted_at': timezone.now()}
        )

        # Repart d'un état propre. Occupant.logement est en SET_NULL (pas
        # CASCADE) -- supprimer les logements ne supprime PAS les occupants,
        # ça les orpheline juste (logement=NULL). Sans cette ligne, les
        # occupants du run précédent s'accumulent et finissent par violer la
        # contrainte unique_together (proprietaire, email)/(proprietaire, cni)
        # sur un CNI/email fixe réutilisé à chaque exécution du test --
        # trouvé exactement comme ça, via un vrai run Cypress qui a échoué.
        Occupant.objects.filter(proprietaire=user).delete()
        Logement.objects.filter(proprietaire=user).delete()

        self.stdout.write(self.style.SUCCESS(f"Compte E2E prêt : {EMAIL} / {PASSWORD}"))
