from rest_framework import serializers
from datetime import timedelta
from .models import Logement, Compartiment, Occupant, Paiement, HistoriqueOccupation


class LogementSerializer(serializers.ModelSerializer):
    nb_compartiments = serializers.ReadOnlyField()
    nb_occupes       = serializers.ReadOnlyField()
    nb_libres        = serializers.ReadOnlyField()

    class Meta:
        model  = Logement
        fields = ['id', 'nom', 'localisation', 'description',
                  'nb_compartiments', 'nb_occupes', 'nb_libres']


class OccupantMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Occupant
        fields = ['id', 'nom_complet', 'telephone', 'loyer',
                  'date_prochain_paiement', 'statut']


class CompartimentSerializer(serializers.ModelSerializer):
    occupant_actuel = OccupantMiniSerializer(read_only=True)

    class Meta:
        model  = Compartiment
        fields = ['id', 'logement', 'type', 'nom', 'statut',
                  'chambres', 'salons', 'douches', 'cuisines',
                  'occupant_actuel']


class HistoriqueOccupationSerializer(serializers.ModelSerializer):
    duree_jours = serializers.ReadOnlyField()

    class Meta:
        model  = HistoriqueOccupation
        fields = ['id', 'nom_occupant', 'date_entree', 'date_sortie',
                  'loyer', 'duree_jours']


class OccupantSerializer(serializers.ModelSerializer):
    compartiment_nom = serializers.CharField(source='compartiment.nom',     read_only=True)
    logement_nom     = serializers.CharField(source='logement.nom',         read_only=True)
    logement_loc     = serializers.CharField(source='logement.localisation', read_only=True)

    class Meta:
        model  = Occupant
        fields = [
            'id', 'nom_complet', 'email', 'telephone', 'cni',
            'numero_contrat', 'date_debut_contrat', 'loyer',
            'date_prochain_paiement', 'statut', 'actif',
            'compartiment', 'compartiment_nom',
            'logement', 'logement_nom', 'logement_loc',
        ]
        read_only_fields = ['numero_contrat']

    def validate(self, data):
        compartiment = data.get('compartiment')
        if compartiment and compartiment.statut == 'OCCUPE':
            if self.instance and self.instance.compartiment == compartiment:
                return data
            raise serializers.ValidationError(
                {'compartiment': 'Ce compartiment est déjà occupé.'}
            )
        return data


class PaiementSerializer(serializers.ModelSerializer):
    occupant_nom     = serializers.CharField(source='occupant.nom_complet',      read_only=True)
    compartiment_nom = serializers.CharField(source='occupant.compartiment.nom', read_only=True)

    class Meta:
        model  = Paiement
        fields = [
            'id', 'occupant', 'occupant_nom', 'compartiment_nom',
            'montant_verse', 'nombre_mois',
            'date_paiement', 'date_debut_periode', 'date_fin_periode',
            'statut', 'note',
        ]
        read_only_fields = ['statut', 'date_fin_periode']

    def validate(self, data):
        if 'date_debut_periode' in data and 'nombre_mois' in data:
            from dateutil.relativedelta import relativedelta
            debut = data['date_debut_periode']
            nb    = data['nombre_mois']
            data['date_fin_periode'] = debut + relativedelta(months=nb) - timedelta(days=1)
        return data