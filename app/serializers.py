from rest_framework import serializers
from datetime import datetime
from .models import Logement, Compartiment, Occupant, Paiement


class LogementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Logement
        fields = ['id', 'nom', 'localisation', 'description']


class CompartimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compartiment
        fields = ['id', 'type', 'nom', 'statut', 'occupant', 'logement',
                'chambres', 'salons', 'douches', 'cuisines']


class OccupantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Occupant
        fields = [
            'id', 'email', 'telephone', 'cni', 'nom_complet',
            'numero_contrat', 'date_debut_contrat', 'loyer',
            'date_prochain_paiement', 'statut', 'logement',
        ]

    def _validate_date(self, value, field_name):
        try:
            if isinstance(value, str):
                datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            try:
                return datetime.strptime(value, "%d/%m/%Y").date()
            except ValueError:
                raise serializers.ValidationError(
                    {field_name: "Format attendu : YYYY-MM-DD"}
                )

    def validate_date_debut_contrat(self, value):
        return self._validate_date(value, "date_debut_contrat")

    def validate_date_prochain_paiement(self, value):
        return self._validate_date(value, "date_prochain_paiement")


class PaiementSerializer(serializers.ModelSerializer):
    occupant_nom = serializers.CharField(source='occupant.nom_complet', read_only=True)

    class Meta:
        model = Paiement
        fields = [
            'id', 'occupant', 'occupant_nom',
            'montant_verse', 'date_paiement',
            'date_prochain_paiement', 'statut',
        ]
        read_only_fields = ['statut']