from django.db import models
from datetime import date, timedelta
from django.utils import timezone


class Logement(models.Model):
    nom          = models.CharField(max_length=200, unique=True)
    localisation = models.CharField(max_length=300)
    description  = models.TextField(blank=True)

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
    numero_contrat         = models.CharField(max_length=50, unique=True)
    date_debut_contrat     = models.DateField()
    loyer                  = models.DecimalField(max_digits=10, decimal_places=2)
    date_prochain_paiement = models.DateField()
    statut                 = models.CharField(
        max_length=20,
        choices=[('Actif', 'Actif'), ('En retard', 'En retard'), ('Parti', 'Parti')],
        default='Actif'
    )
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom_complet

    def calculer_statut(self):
        if not self.actif:
            self.statut = 'Parti'
            return
        today = date.today()
        self.statut = 'En retard' if today > self.date_prochain_paiement else 'Actif'

    def save(self, *args, **kwargs):
        self.calculer_statut()
        super().save(*args, **kwargs)
        if self.compartiment:
            nouveau_statut = 'OCCUPE' if self.actif else (
                'OCCUPE' if self.compartiment.occupants.filter(actif=True).exclude(pk=self.pk).exists()
                else 'LIBRE'
            )
            Compartiment.objects.filter(pk=self.compartiment.pk).update(statut=nouveau_statut)

    def liberer(self):
        self.actif = False
        self.save()


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
            date_prochain_paiement=next_date
        )

    class Meta:
        ordering = ['-date_paiement']