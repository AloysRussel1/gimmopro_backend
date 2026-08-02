from django.contrib import admin
from .models import Logement, Compartiment, Occupant, Paiement, Depense


@admin.register(Logement)
class LogementAdmin(admin.ModelAdmin):
    list_display  = ['id', 'nom', 'localisation', 'nb_compartiments', 'nb_occupes', 'nb_libres']
    search_fields = ['nom', 'localisation']


@admin.register(Compartiment)
class CompartimentAdmin(admin.ModelAdmin):
    list_display  = ['id', 'nom', 'type', 'statut', 'logement']
    list_filter   = ['type', 'statut']
    search_fields = ['nom']


@admin.register(Occupant)
class OccupantAdmin(admin.ModelAdmin):
    list_display  = ['id', 'nom_complet', 'telephone', 'loyer', 'statut', 'actif', 'compartiment', 'date_prochain_paiement']
    list_filter   = ['statut', 'actif']
    search_fields = ['nom_complet', 'email', 'cni']


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ['id', 'occupant', 'montant_verse', 'nombre_mois', 'date_paiement', 'date_fin_periode', 'statut']
    list_filter  = ['statut']


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display  = ['id', 'libelle', 'logement', 'montant', 'categorie', 'date']
    list_filter   = ['categorie']
    search_fields = ['libelle']