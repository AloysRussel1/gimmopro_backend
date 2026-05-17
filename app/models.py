from django.db import models
from datetime import date, timedelta
from django.utils import timezone
import datetime


def generer_numero_contrat():
    """Génère un numéro de contrat unique : CONT-YYYY-XXXX"""
    annee = datetime.date.today().year
    # Compter les contrats de cette année
    count = Occupant.objects.filter(
        numero_contrat__startswith=f"CONT-{annee}-"
    ).count()
    return f"CONT-{annee}-{str(count + 1).zfill(4)}"


class Logement(models.Model):
    nom          = models.CharField(max_length=200, unique=True)
    localisation = models.CharField(max_length=300)
    description  = models.TextField(blank=True)
    date_creation = models.DateField(default=timezone.now)

    def __str__(self):
        return self.nom

    @property
    def nb_compartiments(self):
        return self.compartiments.count()

    @property
    def nb_occupes(self):
        return self.compartiments.filter(statut='OCCUPE').count()

    @property
    def nb_libres(self):
        return self.compartiments.filter(statut='LIBRE').count()


class Compartiment(models.Model):
    TYPE_CHOICES = [
        ('CHAMBRE',     'Chambre'),
        ('APPARTEMENT', 'Appartement'),
        ('STUDIO',      'Studio'),
        ('BOUTIQUE',    'Boutique'),
    ]
    STATUT_CHOICES = [
        ('LIBRE',  'Libre'),
        ('OCCUPE', 'Occupé'),
    ]

    logement  = models.ForeignKey(Logement, on_delete=models.CASCADE, related_name='compartiments')
    type      = models.CharField(max_length=20, choices=TYPE_CHOICES)
    nom       = models.CharField(max_length=200)
    statut    = models.CharField(max_length=10, choices=STATUT_CHOICES, default='LIBRE')
    chambres  = models.IntegerField(default=0)
    salons    = models.IntegerField(default=0)
    douches   = models.IntegerField(default=0)
    cuisines  = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.nom} ({self.get_type_display()}) — {self.get_statut_display()}"

    @property
    def occupant_actuel(self):
        return self.occupants.filter(actif=True).first()


class Occupant(models.Model):
    compartiment           = models.ForeignKey(
        Compartiment, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='occupants'
    )
    logement               = models.ForeignKey(
        Logement, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='occupants'
    )
    nom_complet            = models.CharField(max_length=255)
    email                  = models.EmailField(unique=True)
    telephone              = models.CharField(max_length=20)
    cni                    = models.CharField(max_length=20, unique=True)
    numero_contrat         = models.CharField(max_length=50, unique=True, blank=True)
    date_debut_contrat     = models.DateField()
    loyer                  = models.DecimalField(max_digits=10, decimal_places=2)
    date_prochain_paiement = models.DateField()
    statut                 = models.CharField(
        max_length=20,
        choices=[('Actif', 'Actif'), ('En retard', 'En retard'), ('Parti', 'Parti')],
        default='Actif'
    )
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.nom_complet

    def save(self, *args, **kwargs):
        # Générer le numéro de contrat automatiquement
        if not self.numero_contrat:
            self.numero_contrat = generer_numero_contrat()

        # Calculer le statut
        if not self.actif:
            self.statut = 'Parti'
        else:
            self.statut = 'En retard' if date.today() > self.date_prochain_paiement else 'Actif'

        super().save(*args, **kwargs)

        # Mettre à jour le statut du compartiment
        if self.compartiment:
            autres_actifs = self.compartiment.occupants.filter(actif=True).exclude(pk=self.pk)
            nouveau_statut = 'OCCUPE' if (self.actif or autres_actifs.exists()) else 'LIBRE'
            Compartiment.objects.filter(pk=self.compartiment.pk).update(statut=nouveau_statut)

        # Créer l'historique si premier save
        if self.actif and self.pk:
            HistoriqueOccupation.objects.get_or_create(
                occupant=self,
                compartiment=self.compartiment,
                defaults={
                    'date_entree': self.date_debut_contrat,
                    'loyer': self.loyer,
                }
            )

    def liberer(self):
        """Marque le départ du locataire et libère le compartiment."""
        # Mettre à jour l'historique
        HistoriqueOccupation.objects.filter(
            occupant=self, date_sortie__isnull=True
        ).update(date_sortie=date.today())

        self.actif  = False
        self.statut = 'Parti'
        # Sauvegarder sans déclencher la création d'historique
        Occupant.objects.filter(pk=self.pk).update(actif=False, statut='Parti')
        if self.compartiment:
            Compartiment.objects.filter(pk=self.compartiment.pk).update(statut='LIBRE')


class HistoriqueOccupation(models.Model):
    """Historique de tous les occupants d'un compartiment."""
    compartiment  = models.ForeignKey(
        Compartiment, on_delete=models.CASCADE,
        related_name='historique', null=True, blank=True
    )
    occupant      = models.ForeignKey(
        Occupant, on_delete=models.CASCADE,
        related_name='historique', null=True, blank=True
    )
    nom_occupant  = models.CharField(max_length=255, blank=True)  # snapshot au cas où suppression
    date_entree   = models.DateField()
    date_sortie   = models.DateField(null=True, blank=True)
    loyer         = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.nom_occupant or self.occupant} — {self.compartiment} ({self.date_entree})"

    def save(self, *args, **kwargs):
        if self.occupant and not self.nom_occupant:
            self.nom_occupant = self.occupant.nom_complet
        super().save(*args, **kwargs)

    @property
    def duree_jours(self):
        fin = self.date_sortie or date.today()
        return (fin - self.date_entree).days

    class Meta:
        ordering = ['-date_entree']


class Paiement(models.Model):
    occupant           = models.ForeignKey(Occupant, on_delete=models.CASCADE, related_name='paiements')
    montant_verse      = models.DecimalField(max_digits=10, decimal_places=2)
    nombre_mois        = models.IntegerField(default=1)
    date_paiement      = models.DateField(default=timezone.now)
    date_debut_periode = models.DateField()
    date_fin_periode   = models.DateField()
    statut             = models.CharField(
        max_length=20,
        choices=[('Payé', 'Payé'), ('En attente', 'En attente')],
        default='Payé'
    )
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.occupant.nom_complet} — {self.montant_verse} ({self.nombre_mois} mois)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        next_date = self.date_fin_periode + timedelta(days=1)
        Occupant.objects.filter(pk=self.occupant.pk).update(
            date_prochain_paiement=next_date,
            statut='Actif'
        )

    class Meta:
        ordering = ['-date_paiement']