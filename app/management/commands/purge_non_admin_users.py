from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import Logement, Document, EtatDesLieux


class Command(BaseCommand):
    """Supprime tous les comptes avec is_superuser=False -- utilisé pour
    repartir d'une base propre lors de tests d'inscription/email en
    production. Mode APERÇU par défaut : rien n'est supprimé tant que
    --confirmer n'est pas explicitement passé, parce que Logement.proprietaire/
    Document.proprietaire/EtatDesLieux.proprietaire sont tous en CASCADE --
    supprimer un compte supprime aussi tous ses logements, occupants,
    paiements, dépenses, documents et états des lieux, pas juste le compte.

    Usage :
        python manage.py purge_non_admin_users             # aperçu, aucune suppression
        python manage.py purge_non_admin_users --confirmer  # suppression réelle
    """
    help = "Supprime tous les comptes non-superadmin (aperçu par défaut, --confirmer pour supprimer réellement)."

    def add_arguments(self, parser):
        parser.add_argument('--confirmer', action='store_true', help="Effectue réellement la suppression (sinon, aperçu seulement).")

    def handle(self, *args, **options):
        utilisateurs = User.objects.filter(is_superuser=False).order_by('date_joined')
        total = utilisateurs.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Aucun compte non-superadmin en base -- rien à faire."))
            return

        self.stdout.write(self.style.WARNING(f"{total} compte(s) non-superadmin trouvé(s) :\n"))
        for u in utilisateurs:
            nb_logements = Logement.objects.filter(proprietaire=u).count()
            nb_documents = Document.objects.filter(proprietaire=u).count()
            nb_edl       = EtatDesLieux.objects.filter(proprietaire=u).count()
            self.stdout.write(
                f"  id={u.id} email={u.email!r} username={u.username!r} "
                f"is_active={u.is_active} date_joined={u.date_joined} "
                f"-- {nb_logements} logement(s), {nb_documents} document(s), {nb_edl} état(s) des lieux "
                f"(+ tout ce qui en dépend en cascade : compartiments, occupants, paiements, dépenses)"
            )

        if not options['confirmer']:
            self.stdout.write(self.style.WARNING(
                f"\nAPERÇU SEULEMENT -- aucune suppression effectuée. "
                f"Relance avec --confirmer pour supprimer réellement ces {total} compte(s) et toutes leurs données."
            ))
            return

        with transaction.atomic():
            supprimes = list(utilisateurs.values_list('email', flat=True))
            utilisateurs.delete()

        self.stdout.write(self.style.SUCCESS(f"\n{len(supprimes)} compte(s) supprimé(s) : {supprimes}"))
