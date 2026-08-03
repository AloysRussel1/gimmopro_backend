import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from app.models import Profile
from app.utils import _generer_username_depuis_email


class Command(BaseCommand):
    """Garantit qu'un compte Super Admin de secours existe, est actif, et a
    le mot de passe défini par SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD. Ne fait
    RIEN si elles ne sont pas définies -- pas de secret en dur dans le code
    (un mot de passe committé dans l'historique Git y reste pour toujours,
    même après suppression ultérieure du fichier).

    Idempotent et pensé pour tourner à CHAQUE démarrage (voir Procfile) :
    à chaque exécution, le mot de passe et les flags is_active/is_staff/
    is_superuser sont FORCÉS depuis les variables d'environnement -- y
    compris si le compte existait déjà et semblait correctement configuré.
    C'est voulu : ce compte de secours doit rester accessible avec les
    identifiants connus même si un déploiement précédent a fini par pointer
    vers une base différente (ex: bascule SQLite éphémère <-> Postgres) où le
    compte a été modifié autrement. Si un mot de passe différent doit être
    conservé durablement, ne pas définir SUPERADMIN_EMAIL/PASSWORD.
    """
    help = "Crée/force un compte Super Admin de secours depuis SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD à chaque démarrage (no-op si absentes)."

    def handle(self, *args, **options):
        email    = os.environ.get('SUPERADMIN_EMAIL', '').strip()
        password = os.environ.get('SUPERADMIN_PASSWORD', '')

        if not email or not password:
            self.stdout.write("SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD non définies -- aucun compte de secours géré.")
            return

        # Diagnostic sur la FORME du mot de passe lu depuis l'environnement --
        # jamais sa valeur -- pour repérer un copier-coller Railway avec des
        # guillemets ou espaces parasites sans jamais faire fuiter le secret.
        quote_chars = ('"', "'")
        a_des_espaces_parasites = password != password.strip()
        entoure_de_guillemets = bool(password) and password[0] in quote_chars and password[-1] in quote_chars
        self.stdout.write(
            f"SUPERADMIN_PASSWORD lue : longueur={len(password)}, "
            f"espace/tab en début ou fin={a_des_espaces_parasites}, "
            f"entourée de guillemets={entoure_de_guillemets}"
        )

        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            username = _generer_username_depuis_email(email)
            user = User.objects.create_user(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Compte Super Admin de secours créé : {email} (username={username})"))
        else:
            user.set_password(password)
            self.stdout.write(self.style.WARNING(
                f"Compte Super Admin {email} trouvé -- mot de passe et statut admin resynchronisés depuis SUPERADMIN_PASSWORD."
            ))

        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save()

        # Confirmation post-écriture, relue depuis l'objet tel qu'il vient
        # d'être sauvegardé -- aucune valeur secrète.
        self.stdout.write(
            f"Compte Super Admin en BDD : id={user.pk}, username={user.username!r}, "
            f"email={user.email!r}, is_active={user.is_active}, is_staff={user.is_staff}, "
            f"is_superuser={user.is_superuser}"
        )

        profile, created_profile = Profile.objects.get_or_create(user=user, defaults={'is_verified': True})
        if not created_profile and not profile.is_verified:
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])
