from django.contrib import admin
from .models import Logement, Compartiment, Occupant, Paiement


@admin.register(Logement)
class LogementAdmin(admin.ModelAdmin):
    list_display = ['id', 'nom', 'localisation']
    search_fields = ['nom', 'localisation']


@admin.register(Compartiment)
class CompartimentAdmin(admin.ModelAdmin):
    list_display = ['id', 'nom', 'type', 'statut', 'logement', 'occupant']
    list_filter = ['type', 'statut']
    search_fields = ['nom']


@admin.register(Occupant)
class OccupantAdmin(admin.ModelAdmin):
    list_display = ['id', 'nom_complet', 'telephone', 'loyer', 'statut', 'date_prochain_paiement']
    list_filter = ['statut']
    search_fields = ['nom_complet', 'email', 'cni']


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ['id', 'occupant', 'montant_verse', 'date_paiement', 'statut']
    list_filter = ['statut']