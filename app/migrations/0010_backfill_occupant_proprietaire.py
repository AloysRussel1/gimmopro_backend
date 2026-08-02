from django.db import migrations


def backfill_proprietaire(apps, schema_editor):
    """Remplit Occupant.proprietaire depuis logement.proprietaire (ou, à défaut,
    compartiment.logement.proprietaire) pour les occupants créés avant l'ajout
    de ce champ dénormalisé."""
    Occupant = apps.get_model('app', 'Occupant')

    for occ in Occupant.objects.filter(proprietaire__isnull=True).select_related('logement', 'compartiment__logement'):
        proprietaire = None
        if occ.logement_id and occ.logement.proprietaire_id:
            proprietaire = occ.logement.proprietaire_id
        elif occ.compartiment_id and occ.compartiment.logement.proprietaire_id:
            proprietaire = occ.compartiment.logement.proprietaire_id
        if proprietaire:
            occ.proprietaire_id = proprietaire
            occ.save(update_fields=['proprietaire'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_occupant_proprietaire_alter_occupant_cni_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_proprietaire, noop_reverse),
    ]
