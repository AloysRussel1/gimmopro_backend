from rest_framework import serializers
from .models import Logement, Compartiment,Occupant


# Serializer pour le modèle Logement
class LogementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Logement
        fields = ['id', 'nom', 'localisation', 'description']
        

class CompartimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compartiment
        fields = ['id', 'type', 'nom', 'statut', 'occupant', 'logement', 'chambres', 'salons', 'douches', 'cuisines']


from datetime import datetime

class OccupantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Occupant
        fields = [
            'id',
            'email',
            'telephone',
            'cni',
            'nom_complet',
            'numero_contrat',
            'date_debut_contrat',
            'loyer',
            'date_prochain_paiement',
            'statut',
            'logement'
        ]

    def validate_date_debut_contrat(self, value):
        return self.validate_date_format(value, "date_debut_contrat")

    def validate_date_prochain_paiement(self, value):
        return self.validate_date_format(value, "date_prochain_paiement")

    def validate_date_format(self, value, field_name):
        """
        Valide et reformate les dates pour qu'elles soient au format YYYY-MM-DD.
        """
        try:
            # Vérifie si la date est déjà dans le bon format
            if isinstance(value, str):
                datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            try:
                # Essaie de convertir d'autres formats en YYYY-MM-DD
                formatted_date = datetime.strptime(value, "%d/%m/%Y").date()
                return formatted_date
            except ValueError:
                raise serializers.ValidationError(
                    {field_name: "Le format de la date est incorrect. Utilisez le format YYYY-MM-DD."}
                )
