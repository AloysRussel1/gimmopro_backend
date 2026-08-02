from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Diagnostic en lecture seule pour un échec de connexion inexpliqué :
    liste TOUS les comptes qui matchent un identifiant donné, par username
    exact ET par email (insensible à la casse) séparément — le User model de
    Django par défaut n'a PAS de contrainte d'unicité en base sur l'email,
    donc plusieurs comptes peuvent involontairement partager la même adresse
    (ex: plusieurs tentatives d'inscription/activation lors de tests manuels).
    Si EmailOrUsernameBackend tombe sur >1 résultat côté email, il ne garde
    que les comptes actifs — un doublon peut donc faire échouer silencieusement
    une connexion qui semble pourtant correcte.

    Usage :
        python manage.py diagnose_login aloysrussel1@gmail.com
        python manage.py diagnose_login aloysrussel1
    """
    help = "Liste tous les comptes correspondant à un identifiant (username exact + email insensible à la casse), pour diagnostiquer un login qui échoue à tort."

    def add_arguments(self, parser):
        parser.add_argument('identifiant', type=str, help="Username ou email à diagnostiquer.")

    def handle(self, *args, **options):
        identifiant = options['identifiant'].strip()

        par_username = User.objects.filter(username=identifiant)
        par_email    = User.objects.filter(email__iexact=identifiant)

        self.stdout.write(self.style.WARNING(f"— Comptes avec username == {identifiant!r} : {par_username.count()}"))
        for u in par_username:
            self._afficher(u)

        self.stdout.write(self.style.WARNING(f"\n— Comptes avec email ~= {identifiant!r} (insensible à la casse) : {par_email.count()}"))
        for u in par_email:
            self._afficher(u)

        if par_email.count() > 1:
            self.stdout.write(self.style.ERROR(
                "\n[ATTENTION] PLUSIEURS comptes partagent cet email. Si tu te connectes avec l'EMAIL, "
                "EmailOrUsernameBackend ne retient que les comptes actifs parmi ceux-ci — "
                "vérifie que celui avec le bon mot de passe est bien celui qui est actif, "
                "et envisage de désactiver/renommer l'email des doublons."
            ))
        elif par_username.count() == 0 and par_email.count() == 0:
            self.stdout.write(self.style.ERROR("\n[ATTENTION] Aucun compte ne correspond à cet identifiant, ni par username ni par email."))
        else:
            self.stdout.write(self.style.SUCCESS("\nAucun doublon détecté sur cet identifiant."))

    def _afficher(self, u):
        self.stdout.write(
            f"    id={u.id} username={u.username!r} email={u.email!r} "
            f"is_active={u.is_active} is_staff={u.is_staff} "
            f"password_hasher={u.password.split('$')[0] if '$' in u.password else u.password[:12]} "
            f"date_joined={u.date_joined}"
        )
