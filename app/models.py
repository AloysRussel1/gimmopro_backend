from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from datetime import date, timedelta
from django.utils import timezone
import datetime
import uuid


def generer_numero_contrat(proprietaire=None):
    """Génère un numéro de contrat unique : CONT-YYYY-XXXX.

    Compté PAR PROPRIÉTAIRE (pas globalement) : sans ça, deux comptes
    différents créant chacun leur 5e occupant de l'année entreraient
    en collision sur CONT-{année}-0005. select_for_update() verrouille
    la ligne le temps de la transaction pour éviter la race condition
    lecture-puis-écriture sous création concurrente (n'a d'effet réel
    que sous PostgreSQL — SQLite ignore silencieusement le verrou).
    """
    annee = datetime.date.today().year
    with transaction.atomic():
        qs = Occupant.objects.select_for_update().filter(numero_contrat__startswith=f"CONT-{annee}-")
        if proprietaire is not None:
            qs = qs.filter(logement__proprietaire=proprietaire)
        dernier = qs.order_by('-numero_contrat').first()
        n = int(dernier.numero_contrat.split('-')[-1]) + 1 if dernier else 1
        return f"CONT-{annee}-{str(n).zfill(4)}"


class Profile(models.Model):
    """Coordonnées du bailleur/gestionnaire — utilisées notamment dans le contrat de bail PDF."""
    user        = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    telephone   = models.CharField(max_length=20, blank=True)
    adresse     = models.CharField(max_length=300, blank=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"Profil de {self.user.username}"


class Logement(models.Model):
    proprietaire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='logements'
    )
    nom          = models.CharField(max_length=200)
    localisation = models.CharField(max_length=300)
    description  = models.TextField(blank=True)
    date_creation = models.DateField(default=timezone.now)

    class Meta:
        # Unique PAR propriétaire, pas globalement — sinon un deuxième compte
        # ne pourrait jamais nommer un bien "Résidence A" si un autre l'a déjà fait.
        unique_together = [('proprietaire', 'nom')]

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
    # Loyer "de référence" du compartiment — utile même vacant, avant tout occupant
    # (Occupant.loyer reste le loyer réellement contractualisé, qui peut différer).
    loyer_reference = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Spécifique au type BOUTIQUE.
    mezzanine       = models.BooleanField(default=False)
    # Nécessaire pour calculer "vacant depuis quand" quand un compartiment
    # n'a JAMAIS eu d'occupant (donc aucun HistoriqueOccupation à consulter).
    date_creation   = models.DateTimeField(auto_now_add=True, null=True)

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
    # Dénormalisé depuis logement.proprietaire (voir save()) : nécessaire pour
    # pouvoir scoper les contraintes d'unicité ci-dessous par propriétaire —
    # unique_together ne peut pas traverser logement__proprietaire directement.
    proprietaire            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='occupants_geres'
    )
    nom_complet            = models.CharField(max_length=255)
    email                  = models.EmailField()
    telephone              = models.CharField(max_length=20)
    cni                    = models.CharField(max_length=20)
    numero_contrat         = models.CharField(max_length=50, blank=True)
    date_debut_contrat     = models.DateField()
    # Optionnel : la majorité des baux ici sont à durée indéterminée (voir le
    # contrat PDF), mais certains bailleurs ont de vrais baux à terme fixe
    # (boutiques, baux annuels renouvelables) — sans ce champ, aucune alerte
    # "bail arrivant à expiration" n'est possible.
    date_fin_contrat       = models.DateField(null=True, blank=True)
    loyer                  = models.DecimalField(max_digits=10, decimal_places=2)
    caution_versee         = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_prochain_paiement = models.DateField()
    statut                 = models.CharField(
        max_length=20,
        choices=[('Actif', 'Actif'), ('En retard', 'En retard'), ('Parti', 'Parti')],
        default='Actif'
    )
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(default=timezone.now)

    class Meta:
        # Unique PAR propriétaire (pas globalement) — sinon un deuxième compte
        # ne pourrait jamais avoir un locataire avec le même email/CNI qu'un
        # locataire d'un AUTRE propriétaire, par pure coïncidence. Et sans ça,
        # generer_numero_contrat() scopé par propriétaire finit forcément par
        # collisionner : deux comptes différents obtiennent tous les deux
        # CONT-2026-0001 pour leur premier locataire de l'année.
        unique_together = [
            ('proprietaire', 'email'),
            ('proprietaire', 'cni'),
            ('proprietaire', 'numero_contrat'),
        ]

    def __str__(self):
        return self.nom_complet

    def save(self, *args, **kwargs):
        # Retenir l'ancien compartiment AVANT le save, pour pouvoir le libérer
        # s'il change (voir plus bas) — sinon un locataire transféré laisse
        # son ancien compartiment bloqué "occupé" indéfiniment.
        ancien_compartiment_id = None
        if self.pk:
            ancien_compartiment_id = (
                Occupant.objects.filter(pk=self.pk).values_list('compartiment_id', flat=True).first()
            )

        if self.logement_id:
            self.proprietaire = self.logement.proprietaire
        elif self.compartiment_id:
            self.proprietaire = self.compartiment.logement.proprietaire

        # Générer le numéro de contrat automatiquement, scopé au propriétaire
        if not self.numero_contrat:
            self.numero_contrat = generer_numero_contrat(self.proprietaire)

        # Calculer le statut
        if not self.actif:
            self.statut = 'Parti'
        else:
            self.statut = 'En retard' if date.today() > self.date_prochain_paiement else 'Actif'

        super().save(*args, **kwargs)

        # Libère l'ANCIEN compartiment si le locataire vient d'en changer
        if ancien_compartiment_id and ancien_compartiment_id != self.compartiment_id:
            Compartiment.objects.filter(pk=ancien_compartiment_id).exclude(
                occupants__actif=True
            ).update(statut='LIBRE')

        # Mettre à jour le statut du compartiment courant
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
    MODE_CHOICES = [
        ('ESPECES',   'Espèces'),
        ('OM',        'Orange Money'),
        ('MOMO',      'MTN MoMo'),
        ('VIREMENT',  'Virement bancaire'),
        ('CHEQUE',    'Chèque'),
    ]

    occupant           = models.ForeignKey(Occupant, on_delete=models.CASCADE, related_name='paiements')
    montant_verse      = models.DecimalField(max_digits=10, decimal_places=2)
    nombre_mois        = models.IntegerField(default=1)
    mode_paiement      = models.CharField(max_length=20, choices=MODE_CHOICES, default='ESPECES')
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


class Depense(models.Model):
    """Charge/dépense rattachée à un logement (réparations, factures, taxes…).
    Volontairement séparée de Paiement — une dépense n'est jamais un loyer et
    ne doit jamais entrer dans les calculs de revenus/encaissements."""
    CATEGORIE_CHOICES = [
        ('REPARATION',  'Réparations'),
        ('ELECTRICITE', 'Électricité'),
        ('EAU',         'Eau'),
        ('TAXE',        'Taxe'),
        ('ENTRETIEN',   'Entretien'),
        ('AUTRE',       'Autre'),
    ]

    logement  = models.ForeignKey(Logement, on_delete=models.CASCADE, related_name='depenses')
    libelle   = models.CharField(max_length=255)
    montant   = models.DecimalField(max_digits=10, decimal_places=2)
    date      = models.DateField(default=timezone.now)
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, default='AUTRE')
    note      = models.TextField(blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.libelle} — {self.montant} FCFA ({self.logement.nom})"

    class Meta:
        ordering = ['-date']


def valider_fichier_document(fichier):
    """Refuse tout fichier > 5 Mo ou dont l'extension n'est pas PDF/PNG/JPEG —
    seule ligne de défense côté modèle, dupliquée côté serializer pour un
    message d'erreur DRF propre avant même l'écriture disque."""
    max_octets = 5 * 1024 * 1024
    if fichier.size > max_octets:
        raise DjangoValidationError("Le fichier dépasse la taille maximale autorisée (5 Mo).")
    ext = fichier.name.rsplit('.', 1)[-1].lower() if '.' in fichier.name else ''
    if ext not in ('pdf', 'png', 'jpg', 'jpeg'):
        raise DjangoValidationError("Format non autorisé — seuls les fichiers PDF, PNG et JPEG sont acceptés.")


def document_upload_path(instance, filename):
    """Nom de fichier randomisé (jamais le nom d'origine) pour éviter toute
    collision et empêcher qu'un nom de fichier ne révèle des infos entre
    bailleurs ; le dossier reste namespacé par propriétaire par prudence,
    mais l'accès réel est de toute façon contrôlé par DocumentDownloadView,
    jamais par MEDIA_URL direct."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    unique = uuid.uuid4().hex
    proprio_id = instance.proprietaire_id or 'tmp'
    nom = f"{unique}.{ext}" if ext else unique
    return f"documents/proprietaire_{proprio_id}/{nom}"


class Document(models.Model):
    """Pièce jointe (CNI, contrat signé, facture, quittance externe…)
    rattachée à un locataire et/ou un logement. Le fichier ne doit jamais
    être exposé via son URL brute (voir DocumentDownloadView)."""
    TYPE_CHOICES = [
        ('CNI_PASSEPORT',     'CNI / Passeport'),
        ('CONTRAT_SIGNE',     'Contrat signé'),
        ('FACTURE_TRAVAUX',   'Facture travaux'),
        ('QUITTANCE_EXTERNE', 'Quittance externe'),
        ('AUTRE',             'Autre'),
    ]

    proprietaire  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='documents')
    occupant      = models.ForeignKey(Occupant, on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    logement      = models.ForeignKey(Logement, on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    type_document = models.CharField(max_length=20, choices=TYPE_CHOICES, default='AUTRE')
    fichier       = models.FileField(upload_to=document_upload_path, validators=[valider_fichier_document])
    nom_fichier   = models.CharField(max_length=255, blank=True)
    taille_octets = models.PositiveIntegerField(default=0)
    date_televersement = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_televersement']

    def __str__(self):
        return self.nom_fichier or f"Document #{self.pk}"

    def save(self, *args, **kwargs):
        if self.fichier and not self.nom_fichier:
            self.nom_fichier = self.fichier.name.rsplit('/', 1)[-1]
        if self.fichier:
            try:
                self.taille_octets = self.fichier.size
            except (OSError, ValueError):
                pass
        super().save(*args, **kwargs)


class EtatDesLieux(models.Model):
    """Constat contradictoire d'entrée ou de sortie, pièce par pièce, avec
    remise des clés — sert de base légale en cas de litige sur la caution."""
    TYPE_CHOICES = [('ENTREE', 'Entrée'), ('SORTIE', 'Sortie')]
    ETAT_CHOICES = [('BON', 'Bon'), ('MOYEN', 'Moyen'), ('MAUVAIS', 'Mauvais')]

    proprietaire     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='etats_des_lieux')
    occupant         = models.ForeignKey(Occupant, on_delete=models.CASCADE, related_name='etats_des_lieux')
    logement         = models.ForeignKey(Logement, on_delete=models.CASCADE, null=True, blank=True, related_name='etats_des_lieux')
    compartiment     = models.ForeignKey(Compartiment, on_delete=models.SET_NULL, null=True, blank=True, related_name='etats_des_lieux')
    type             = models.CharField(max_length=10, choices=TYPE_CHOICES)
    date_realisation = models.DateField(default=date.today)
    etat_general     = models.CharField(max_length=10, choices=ETAT_CHOICES, default='BON')
    cles_remises     = models.PositiveIntegerField(default=0)
    observations     = models.TextField(blank=True)
    # Détail pièce par pièce, ex. {"Salon": {"Peinture": "Bon", "Électricité": "Moyen"}, ...}
    champs_details   = models.JSONField(default=dict, blank=True)
    date_creation    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_realisation']

    def __str__(self):
        return f"État des lieux {self.get_type_display()} — {self.occupant.nom_complet} ({self.date_realisation})"

    def save(self, *args, **kwargs):
        # Auto-dérivé de l'occupant pour garantir la cohérence bailleur/logement
        # même si l'appelant ne les fournit pas explicitement.
        if self.occupant_id and not self.proprietaire_id:
            self.proprietaire = self.occupant.proprietaire
        if self.occupant_id and not self.logement_id:
            self.logement = self.occupant.logement
        if self.occupant_id and not self.compartiment_id:
            self.compartiment = self.occupant.compartiment
        super().save(*args, **kwargs)


class ActivityLog(models.Model):
    """Journal des actions clés de la plateforme (pas un audit exhaustif de
    chaque requête) — alimente l'onglet "Logs" de l'interface admin."""
    ACTION_CHOICES = [
        ('REGISTER',             'Inscription'),
        ('LOGIN',                'Connexion'),
        ('ACCOUNT_ACTIVATED',    'Compte activé'),
        ('ACCOUNT_DEACTIVATED',  'Compte désactivé'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='activity_logs'
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    # Capture une info identifiante (ex: email) au moment du log — reste
    # lisible même si le compte est supprimé plus tard (user devient NULL).
    description = models.CharField(max_length=255, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_creation']

    def __str__(self):
        return f"{self.get_action_display()} — {self.description or self.user}"