from rest_framework import serializers
from datetime import timedelta
from django.contrib.auth.models import User
from .models import (
    Logement, Compartiment, Occupant, Paiement, HistoriqueOccupation, Profile, Depense,
    Document, EtatDesLieux, ActivityLog,
)
from .utils import make_recu_token


class DepenseSerializer(serializers.ModelSerializer):
    logement_nom = serializers.CharField(source='logement.nom', read_only=True)

    class Meta:
        model  = Depense
        fields = ['id', 'logement', 'logement_nom', 'libelle', 'montant', 'date', 'categorie', 'note']


class ProfileSerializer(serializers.ModelSerializer):
    username     = serializers.CharField(source='user.username', read_only=True)
    email        = serializers.EmailField(source='user.email', read_only=True)
    nom          = serializers.SerializerMethodField()
    # Utilisé côté frontend uniquement pour l'affichage/la navigation (AdminRoute) —
    # la vraie protection des endpoints admin est IsAdminUser côté backend.
    is_staff     = serializers.BooleanField(source='user.is_staff', read_only=True)
    is_superuser = serializers.BooleanField(source='user.is_superuser', read_only=True)

    class Meta:
        model  = Profile
        fields = ['username', 'email', 'nom', 'telephone', 'adresse', 'is_verified', 'is_staff', 'is_superuser', 'terms_accepted_at']
        read_only_fields = ['is_verified', 'terms_accepted_at']

    def get_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username


class AdminUserSerializer(serializers.ModelSerializer):
    """Vue d'ensemble admin d'un compte — jamais utilisé hors des vues
    IsAdminUser. is_verified passe par un SerializerMethodField (pas un
    source dotted) pour ne pas planter si un compte très ancien n'a pas
    encore de Profile."""
    is_verified  = serializers.SerializerMethodField()
    nb_logements = serializers.IntegerField(read_only=True, default=0)  # annotate côté vue

    class Meta:
        model  = User
        fields = ['id', 'username', 'email', 'is_active', 'is_staff', 'is_superuser',
                  'date_joined', 'is_verified', 'nb_logements']
        read_only_fields = fields

    def get_is_verified(self, obj):
        return getattr(getattr(obj, 'profile', None), 'is_verified', False)


class ActivityLogSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()

    class Meta:
        model  = ActivityLog
        fields = ['id', 'user', 'user_email', 'action', 'description', 'date_creation']

    def get_user_email(self, obj):
        return obj.user.email if obj.user_id else None


class LogementSerializer(serializers.ModelSerializer):
    nb_compartiments = serializers.ReadOnlyField()
    nb_occupes       = serializers.ReadOnlyField()
    nb_libres        = serializers.ReadOnlyField()

    class Meta:
        model  = Logement
        fields = ['id', 'nom', 'localisation', 'description',
                  'nb_compartiments', 'nb_occupes', 'nb_libres']


class AdminLogementSerializer(LogementSerializer):
    """Réservée aux vues admin (cross-tenant) — seule différence avec
    LogementSerializer : proprietaire devient un champ écrivable, puisque
    la vue "tenant" normale le fixe elle-même via s.save(proprietaire=request.user)
    et n'a donc jamais eu besoin de l'exposer."""
    proprietaire       = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    proprietaire_email = serializers.CharField(source='proprietaire.email', read_only=True)

    class Meta(LogementSerializer.Meta):
        fields = LogementSerializer.Meta.fields + ['proprietaire', 'proprietaire_email']


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
                  'loyer_reference', 'mezzanine',
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
            'numero_contrat', 'date_debut_contrat', 'date_fin_contrat', 'loyer', 'caution_versee',
            'date_versement_caution',
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
    occupant_nom       = serializers.CharField(source='occupant.nom_complet',      read_only=True)
    occupant_telephone = serializers.CharField(source='occupant.telephone',        read_only=True)
    occupant_email     = serializers.CharField(source='occupant.email',            read_only=True)
    compartiment_nom   = serializers.CharField(source='occupant.compartiment.nom', read_only=True)
    recu_token         = serializers.SerializerMethodField()

    class Meta:
        model  = Paiement
        fields = [
            'id', 'occupant', 'occupant_nom', 'occupant_telephone', 'occupant_email',
            'compartiment_nom',
            'montant_verse', 'nombre_mois', 'mode_paiement',
            'date_paiement', 'date_debut_periode', 'date_fin_periode',
            'statut', 'note', 'recu_token',
        ]
        read_only_fields = ['statut', 'date_fin_periode']

    def get_recu_token(self, obj):
        return make_recu_token(obj.id)

    def validate(self, data):
        if 'date_debut_periode' in data and 'nombre_mois' in data:
            from dateutil.relativedelta import relativedelta
            debut = data['date_debut_periode']
            nb    = data['nombre_mois']
            data['date_fin_periode'] = debut + relativedelta(months=nb) - timedelta(days=1)
        return data


class DocumentSerializer(serializers.ModelSerializer):
    # Le fichier n'est jamais renvoyé en lecture (pas d'URL brute exposée) —
    # le téléchargement passe exclusivement par DocumentDownloadView, qui
    # revérifie la propriété avant de streamer les octets.
    occupant_nom           = serializers.SerializerMethodField()
    logement_nom           = serializers.SerializerMethodField()
    type_document_display  = serializers.CharField(source='get_type_document_display', read_only=True)

    class Meta:
        model  = Document
        fields = [
            'id', 'occupant', 'occupant_nom', 'logement', 'logement_nom',
            'type_document', 'type_document_display',
            'fichier', 'nom_fichier', 'taille_octets', 'date_televersement',
        ]
        read_only_fields = ['nom_fichier', 'taille_octets', 'date_televersement']
        extra_kwargs = {'fichier': {'write_only': True}}

    def get_occupant_nom(self, obj):
        return obj.occupant.nom_complet if obj.occupant_id else None

    def get_logement_nom(self, obj):
        return obj.logement.nom if obj.logement_id else None

    def validate(self, data):
        occupant = data.get('occupant', getattr(self.instance, 'occupant', None))
        logement = data.get('logement', getattr(self.instance, 'logement', None))
        if not occupant and not logement:
            raise serializers.ValidationError(
                "Un document doit être rattaché à un locataire ou à un logement."
            )
        return data


class EtatDesLieuxSerializer(serializers.ModelSerializer):
    occupant_nom     = serializers.CharField(source='occupant.nom_complet', read_only=True)
    logement_nom     = serializers.SerializerMethodField()
    compartiment_nom = serializers.SerializerMethodField()
    type_display     = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model  = EtatDesLieux
        fields = [
            'id', 'occupant', 'occupant_nom',
            'logement', 'logement_nom', 'compartiment', 'compartiment_nom',
            'type', 'type_display', 'date_realisation', 'etat_general',
            'cles_remises', 'observations', 'champs_details', 'date_creation',
        ]
        # logement/compartiment sont auto-dérivés de l'occupant dans
        # EtatDesLieux.save() — jamais fournis par le client.
        read_only_fields = ['logement', 'compartiment', 'date_creation']

    def get_logement_nom(self, obj):
        return obj.logement.nom if obj.logement_id else None

    def get_compartiment_nom(self, obj):
        return obj.compartiment.nom if obj.compartiment_id else None