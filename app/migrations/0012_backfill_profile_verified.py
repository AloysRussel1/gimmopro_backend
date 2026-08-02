from django.db import migrations


def backfill_verified(apps, schema_editor):
    """Les comptes créés avant l'ajout de la vérification d'email sont
    considérés vérifiés d'office (comptes de confiance déjà en usage) —
    seules les nouvelles inscriptions démarrent avec is_verified=False."""
    Profile = apps.get_model('app', 'Profile')
    Profile.objects.filter(is_verified=False).update(is_verified=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0011_profile_is_verified'),
    ]

    operations = [
        migrations.RunPython(backfill_verified, noop_reverse),
    ]
