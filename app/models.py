from django.db import models
from datetime import timedelta, date
from django.utils import timezone

# Modele de logement
class Logement(models.Model):
    nom = models.CharField(max_length=200, unique=True)
    localisation = models.CharField(max_length=300)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.nom

class Compartiment(models.Model):
    TYPE_CHOICES = [
        ('CHAMBRE', 'Chambre'),
        ('APPARTEMENT', 'Appartement'),
        ('STUDIO', 'Studio'),
        ('BOUTIQUE', 'Boutique'),
    ]
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    nom = models.CharField(max_length=200)
    
    STATUT_CHOICES = [
        ('LIBRE', 'Libre'),
        ('OCCUPE', 'Occupé'),
    ]
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default='LIBRE')
    
    # Remplacer 'id_ocupant' par une clé étrangère vers Occupant
    occupant = models.ForeignKey('Occupant', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Relation avec le modèle Logement
    logement = models.ForeignKey(
        'Logement',  # Relation avec le modèle Logement
        on_delete=models.CASCADE,  # Supprime les compartiments si le logement est supprimé
        related_name='compartiments'  # Permet d'accéder aux compartiments via logement.compartiments.all()
    )
    chambres = models.IntegerField(default=0)
    salons = models.IntegerField(default=0)
    douches = models.IntegerField(default=0)
    cuisines = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.type} - {self.nom} ({self.get_statut_display()})"
class Occupant(models.Model):
    logement = models.ForeignKey(Logement, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField(unique=True)
    telephone = models.CharField(max_length=15)
    cni = models.CharField(max_length=20, unique=True)
    nom_complet = models.CharField(max_length=255)
    numero_contrat = models.CharField(max_length=50, unique=True)
    date_debut_contrat = models.DateField()
    loyer = models.DecimalField(max_digits=10, decimal_places=2)
    date_prochain_paiement = models.DateField()
    statut = models.CharField(max_length=20, choices=[('Actif', 'Actif'), ('En retard', 'En retard')])

    def __str__(self):
        return self.nom_complet

    def calculer_statut(self):
        today = date.today()
        if today > self.date_prochain_paiement:
            self.statut = 'En retard'
        else:
            self.statut = 'Actif'
        self.save()

    def save(self, *args, **kwargs):
        self.calculer_statut()
        super(Occupant, self).save(*args, **kwargs)



# Modèle de Paiement
class Paiement(models.Model):
    occupant = models.ForeignKey('Occupant', on_delete=models.CASCADE, related_name='paiements')
    montant_verse = models.DecimalField(max_digits=10, decimal_places=2)
    date_paiement = models.DateField(default=timezone.now)
    date_prochain_paiement = models.DateField()
    statut = models.CharField(max_length=20, choices=[('Payé', 'Payé'), ('En attente', 'En attente')])

    def __str__(self):
        return f'Paiement de {self.montant_verse} pour {self.occupant.nom_complet}'

    def save(self, *args, **kwargs):
        # Mettre à jour le statut de paiement en fonction de la date de paiement
        if self.date_paiement <= self.date_prochain_paiement:
            self.statut = 'Payé'
        else:
            self.statut = 'En retard'
        super(Paiement, self).save(*args, **kwargs)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
