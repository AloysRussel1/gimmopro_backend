from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Supprime les comptes de test créés pendant une phase de vérification
    manuelle (ex: `gimmoprotest*@...`, `gimmoprofresh*@...`).

    Volontairement restreint aux comptes INACTIFS (is_active=False) —
    un compte de test qui aurait été confirmé par erreur, ou un vrai compte
    dont l'email matcherait le motif par coïncidence, ne sera jamais supprimé
    par cette commande.

    Usage :
        python manage.py cleanup_test_accounts --email-prefix gimmoprotest
        python manage.py cleanup_test_accounts --email-prefix gimmoprotest --dry-run
        python manage.py cleanup_test_accounts --email-prefix gimmoprotest --email-prefix gimmoprofresh
    """
    help = "Supprime les comptes INACTIFS dont l'email commence par un préfixe donné (nettoyage de comptes de test)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--email-prefix', action='append', required=True,
            help="Préfixe d'email à cibler (répétable, ex: --email-prefix gimmoprotest --email-prefix gimmoprofresh).",
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Liste les comptes qui seraient supprimés, sans rien supprimer.",
        )

    def handle(self, *args, **options):
        prefixes = options['email_prefix']
        dry_run = options['dry_run']

        qs = User.objects.none()
        for prefix in prefixes:
            qs = qs | User.objects.filter(is_active=False, email__istartswith=prefix)
        qs = qs.distinct()

        if not qs.exists():
            self.stdout.write("Aucun compte de test inactif trouvé pour ces préfixes.")
            return

        for user in qs:
            self.stdout.write(f"  - {user.email} (username={user.username}, créé le {user.date_joined:%Y-%m-%d})")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n[dry-run] {qs.count()} compte(s) seraient supprimés."))
            return

        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"\n{count} compte(s) de test supprimé(s)."))
