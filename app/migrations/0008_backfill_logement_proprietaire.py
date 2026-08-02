from django.db import migrations


def backfill_proprietaire(apps, schema_editor):
    """Les logements créés avant l'ajout du champ proprietaire n'ont pas de
    propriétaire. On les rattache au premier utilisateur existant (le compte
    de dev/test) pour ne pas perdre l'accès aux données locales existantes.
    Sans utilisateur en base, on ne fait rien (rien à rattacher)."""
    User = apps.get_model('auth', 'User')
    Logement = apps.get_model('app', 'Logement')

    premier_user = User.objects.order_by('id').first()
    if premier_user is None:
        return

    Logement.objects.filter(proprietaire__isnull=True).update(proprietaire=premier_user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0007_logement_proprietaire_alter_logement_nom_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_proprietaire, noop_reverse),
    ]
