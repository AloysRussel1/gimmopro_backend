from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal

from .models import Logement, Compartiment, Occupant, Paiement, Depense


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
# Alignés sur le schéma actuel (post-retrofit multi-tenant) :
#  - Logement/Occupant sont rattachés à un `proprietaire` (User) — les vues
#    filtrent STRICTEMENT par request.user, donc tout objet créé hors API
#    doit avoir le bon propriétaire pour être visible dans les tests API.
#  - Compartiment n'a PAS de champ `occupant` : le lien se fait dans l'autre
#    sens, via Occupant.compartiment.
#  - Paiement n'a PAS de champ `date_prochain_paiement` (ça, c'est un champ
#    d'Occupant) : Paiement a `date_debut_periode`/`date_fin_periode`, et
#    c'est LUI qui met à jour `Occupant.date_prochain_paiement` dans son
#    save().

def create_user(username="owner", email=None, password="test123"):
    return User.objects.create_user(username=username, password=password, email=email or f"{username}@mail.com")


def create_logement(proprietaire, nom="Résidence Test", localisation="Montréal", description="Test"):
    return Logement.objects.create(
        proprietaire=proprietaire, nom=nom, localisation=localisation, description=description
    )


def create_compartiment(logement, nom="Studio 1", type="STUDIO", statut="LIBRE"):
    return Compartiment.objects.create(
        logement=logement,
        nom=nom,
        type=type,
        statut=statut,
        chambres=1,
        salons=1,
        douches=1,
        cuisines=0,
    )


def create_occupant(logement, suffix="1", compartiment=None):
    return Occupant.objects.create(
        logement=logement,
        compartiment=compartiment,
        email=f"test{suffix}@mail.com",
        telephone="0600000000",
        cni=f"CNI{suffix}",
        nom_complet=f"Locataire {suffix}",
        date_debut_contrat=date.today(),
        loyer=Decimal("500.00"),
        date_prochain_paiement=date.today() + timedelta(days=30),
        statut="Actif",
    )


def create_paiement(occupant, montant=Decimal("500.00")):
    debut = date.today()
    return Paiement.objects.create(
        occupant=occupant,
        montant_verse=montant,
        nombre_mois=1,
        date_paiement=date.today(),
        date_debut_periode=debut,
        date_fin_periode=debut + timedelta(days=29),
        statut="Payé",
    )


# ─────────────────────────────────────────
# MODEL TESTS
# ─────────────────────────────────────────

class LogementModelTest(TestCase):
    def setUp(self):
        self.user = create_user("logement_owner")

    def test_creation_logement(self):
        logement = create_logement(self.user)
        self.assertEqual(str(logement), "Résidence Test")
        self.assertEqual(Logement.objects.count(), 1)

    def test_logement_nom_unique(self):
        create_logement(self.user)
        with self.assertRaises(Exception):
            create_logement(self.user)  # même propriétaire + même nom → doit échouer


class OccupantModelTest(TestCase):
    def setUp(self):
        self.user = create_user("occupant_owner")
        self.logement = create_logement(self.user)

    def test_creation_occupant(self):
        occupant = create_occupant(self.logement)
        self.assertEqual(str(occupant), "Locataire 1")
        self.assertEqual(occupant.statut, "Actif")

    def test_statut_en_retard_automatique(self):
        """Un occupant dont la date de paiement est dépassée doit être En retard."""
        occupant = Occupant.objects.create(
            logement=self.logement,
            email="retard@mail.com",
            telephone="0600000001",
            cni="CNI_RETARD",
            nom_complet="Locataire Retard",
            date_debut_contrat=date.today() - timedelta(days=60),
            loyer=Decimal("400.00"),
            date_prochain_paiement=date.today() - timedelta(days=10),
            statut="Actif",
        )
        self.assertEqual(occupant.statut, "En retard")

    def test_statut_actif_si_paiement_futur(self):
        occupant = create_occupant(self.logement)
        self.assertEqual(occupant.statut, "Actif")


class CompartimentModelTest(TestCase):
    def setUp(self):
        self.user = create_user("compartiment_owner")
        self.logement = create_logement(self.user)

    def test_creation_compartiment(self):
        comp = create_compartiment(self.logement)
        self.assertEqual(comp.statut, "LIBRE")
        self.assertEqual(comp.logement, self.logement)

    def test_str_compartiment(self):
        comp = create_compartiment(self.logement)
        self.assertIn("STUDIO", str(comp).upper())

    def test_suppression_logement_supprime_compartiment(self):
        create_compartiment(self.logement)
        self.logement.delete()
        self.assertEqual(Compartiment.objects.count(), 0)

    def test_occupant_actuel_reflete_occupation(self):
        """Compartiment n'a pas de champ `occupant` : le lien passe par
        Occupant.compartiment, et occupant_actuel doit le refléter."""
        comp = create_compartiment(self.logement)
        self.assertIsNone(comp.occupant_actuel)
        occupant = create_occupant(self.logement, compartiment=comp)
        comp.refresh_from_db()
        self.assertEqual(comp.statut, "OCCUPE")
        self.assertEqual(comp.occupant_actuel, occupant)


class PaiementModelTest(TestCase):
    def setUp(self):
        self.user = create_user("paiement_owner")
        self.logement = create_logement(self.user)
        self.occupant = create_occupant(self.logement)

    def test_creation_paiement(self):
        paiement = create_paiement(self.occupant)
        self.assertEqual(paiement.statut, "Payé")
        self.assertEqual(paiement.occupant, self.occupant)

    def test_paiement_str(self):
        paiement = create_paiement(self.occupant)
        self.assertIn("500", str(paiement))

    def test_paiement_avance_date_prochain_paiement(self):
        """C'est Paiement.save() qui met à jour Occupant.date_prochain_paiement
        (et non l'inverse) — Paiement lui-même n'a pas ce champ."""
        create_paiement(self.occupant)
        self.occupant.refresh_from_db()
        self.assertEqual(self.occupant.date_prochain_paiement, date.today() + timedelta(days=30))


# ─────────────────────────────────────────
# AUTH TESTS
# ─────────────────────────────────────────

class AuthTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse("register")
        self.login_url = reverse("token_obtain_pair")
        self.logout_url = reverse("logout")

    def test_register_success(self):
        # Le compte est créé inactif tant que l'email n'est pas confirmé —
        # pas de JWT à l'inscription (voir EmailVerifyConfirmView pour ça).
        res = self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
            "accept_terms": True,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("access", res.data)
        user = User.objects.get(email="aloys@mail.com")
        self.assertFalse(user.is_active)

    def test_register_puis_connexion_refusee_avant_verification(self):
        self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
            "accept_terms": True,
        })
        res = self.client.post(self.login_url, {
            "username": "aloys@mail.com",
            "password": "motdepasse123",
        })
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_register_email_deja_pris(self):
        User.objects.create_user(username="aloys", password="test123", email="aloys@mail.com")
        res = self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
            "accept_terms": True,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_refuse_sans_acceptation_cgu(self):
        """La validation cote frontend ne suffit jamais a elle seule -- un
        appel direct a l'API sans accept_terms doit aussi etre rejete."""
        res = self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email="aloys@mail.com").exists())

    def test_register_refuse_si_acceptation_cgu_false(self):
        res = self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
            "accept_terms": False,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_enregistre_horodatage_acceptation_cgu(self):
        res = self.client.post(self.register_url, {
            "email": "aloys@mail.com",
            "password": "motdepasse123",
            "accept_terms": True,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="aloys@mail.com")
        self.assertIsNotNone(user.profile.terms_accepted_at)

    def test_login_success(self):
        User.objects.create_user(username="aloys", password="motdepasse123")
        res = self.client.post(self.login_url, {
            "username": "aloys",
            "password": "motdepasse123",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)

    def test_login_mauvais_mot_de_passe(self):
        User.objects.create_user(username="aloys", password="motdepasse123")
        res = self.client.post(self.login_url, {
            "username": "aloys",
            "password": "mauvais",
        })
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_acces_refuse_sans_token(self):
        res = self.client.get(reverse("logement-list-create"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ─────────────────────────────────────────
# API TESTS — BASE
# ─────────────────────────────────────────

class AuthenticatedAPITest(APITestCase):
    """Classe de base : crée un user et authentifie le client."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", password="test123")
        res = self.client.post(reverse("token_obtain_pair"), {
            "username": "testuser",
            "password": "test123",
        })
        self.token = res.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")


# ─────────────────────────────────────────
# LOGEMENT API TESTS
# ─────────────────────────────────────────

class LogementAPITest(AuthenticatedAPITest):
    def test_creer_logement(self):
        res = self.client.post(reverse("logement-list-create"), {
            "nom": "Villa Rosa",
            "localisation": "Laval, QC",
            "description": "Belle villa",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["nom"], "Villa Rosa")

    def test_lister_logements(self):
        create_logement(self.user, "Log A")
        create_logement(self.user, "Log B")
        res = self.client.get(reverse("logement-list-create"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

    def test_detail_logement(self):
        logement = create_logement(self.user)
        res = self.client.get(reverse("logement-detail", args=[logement.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["nom"], logement.nom)

    def test_modifier_logement(self):
        logement = create_logement(self.user)
        res = self.client.put(reverse("logement-detail", args=[logement.id]), {
            "nom": "Nouveau Nom",
            "localisation": "Québec",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["nom"], "Nouveau Nom")

    def test_supprimer_logement(self):
        logement = create_logement(self.user)
        res = self.client.delete(reverse("logement-detail", args=[logement.id]))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Logement.objects.count(), 0)

    def test_isolation_multi_tenant(self):
        """Un utilisateur ne doit jamais voir les logements d'un autre."""
        autre = create_user("autre_bailleur")
        create_logement(autre, "Logement d'autrui")
        res = self.client.get(reverse("logement-list-create"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 0)


# ─────────────────────────────────────────
# COMPARTIMENT API TESTS
# ─────────────────────────────────────────

class CompartimentAPITest(AuthenticatedAPITest):
    def setUp(self):
        super().setUp()
        self.logement = create_logement(self.user)

    def test_ajouter_compartiment(self):
        res = self.client.post(
            reverse("add-compartiment", args=[self.logement.id]),
            {
                "nom": "Studio 101",
                "type": "STUDIO",
                "statut": "LIBRE",
                "logement": self.logement.id,
                "chambres": 1,
                "salons": 1,
                "douches": 1,
                "cuisines": 0,
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_lister_compartiments_par_logement(self):
        create_compartiment(self.logement, nom="C1")
        create_compartiment(self.logement, nom="C2")
        res = self.client.get(reverse("logement-compartiments", args=[self.logement.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

    def test_detail_compartiment(self):
        comp = create_compartiment(self.logement)
        res = self.client.get(reverse("compartiment-detail", args=[comp.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_supprimer_compartiment(self):
        comp = create_compartiment(self.logement)
        res = self.client.delete(reverse("compartiment-detail", args=[comp.id]))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
# OCCUPANT API TESTS
# ─────────────────────────────────────────

class OccupantAPITest(AuthenticatedAPITest):
    def setUp(self):
        super().setUp()
        self.logement = create_logement(self.user)

    def test_creer_occupant(self):
        res = self.client.post(reverse("occupant-list-create"), {
            "logement": self.logement.id,
            "email": "nouveau@mail.com",
            "telephone": "0600000099",
            "cni": "CNI999",
            "nom_complet": "Jean Dupont",
            "date_debut_contrat": str(date.today()),
            "loyer": "600.00",
            "date_prochain_paiement": str(date.today() + timedelta(days=30)),
            "statut": "Actif",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_lister_occupants(self):
        create_occupant(self.logement, "A")
        create_occupant(self.logement, "B")
        res = self.client.get(reverse("occupant-list-create"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

    def test_supprimer_occupant(self):
        occupant = create_occupant(self.logement)
        res = self.client.delete(reverse("occupant-detail", args=[occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
# PAIEMENT API TESTS
# ─────────────────────────────────────────

class PaiementAPITest(AuthenticatedAPITest):
    def setUp(self):
        super().setUp()
        self.logement = create_logement(self.user)
        self.occupant = create_occupant(self.logement)

    def test_creer_paiement(self):
        res = self.client.post(reverse("paiement-list-create"), {
            "occupant": self.occupant.id,
            "montant_verse": "500.00",
            "nombre_mois": 1,
            "date_paiement": str(date.today()),
            "date_debut_periode": str(date.today()),
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_lister_paiements(self):
        create_paiement(self.occupant)
        res = self.client.get(reverse("paiement-list-create"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data), 1)

    def test_filtrer_paiements_par_occupant(self):
        create_paiement(self.occupant)
        res = self.client.get(
            reverse("paiement-list-create") + f"?occupant_id={self.occupant.id}"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)


# ─────────────────────────────────────────
# DASHBOARD STATS TEST
# ─────────────────────────────────────────

class DashboardStatsTest(AuthenticatedAPITest):
    def test_stats_dashboard(self):
        logement = create_logement(self.user)
        comp = create_compartiment(logement)
        # Compartiment n'a pas de champ `occupant` : c'est le fait de créer un
        # Occupant actif rattaché à ce compartiment qui bascule automatiquement
        # son statut à OCCUPE (voir Occupant.save()).
        occupant = create_occupant(logement, compartiment=comp)
        create_paiement(occupant)

        res = self.client.get(reverse("dashboard-stats"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("logements", res.data)
        self.assertIn("compartiments", res.data)
        self.assertIn("occupants", res.data)
        self.assertIn("paiements", res.data)
        self.assertEqual(res.data["compartiments"]["occupes"], 1)
        self.assertGreater(res.data["paiements"]["total_revenus"], 0)


# ─────────────────────────────────────────
# REÇU DE CAUTION TESTS
# ─────────────────────────────────────────

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CautionRecuAPITest(AuthenticatedAPITest):
    def setUp(self):
        super().setUp()
        self.logement = create_logement(self.user)
        self.occupant = create_occupant(self.logement)
        self.occupant.caution_versee = Decimal("300.00")
        self.occupant.date_versement_caution = date.today()
        self.occupant.save()

    def test_pdf_recu_caution(self):
        res = self.client.get(reverse("occupant-caution-recu", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/pdf")

    def test_pdf_recu_caution_refuse_si_montant_nul(self):
        self.occupant.caution_versee = Decimal("0.00")
        self.occupant.save()
        res = self.client.get(reverse("occupant-caution-recu", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pdf_recu_caution_refuse_si_date_absente(self):
        self.occupant.date_versement_caution = None
        self.occupant.save()
        res = self.client.get(reverse("occupant-caution-recu", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_envoi_recu_caution_succes(self):
        res = self.client.post(reverse("occupant-caution-envoyer", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.occupant.email])
        self.assertEqual(len(sent.attachments), 1)
        filename, content, mimetype = sent.attachments[0]
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

    def test_envoi_recu_caution_refuse_si_montant_nul(self):
        self.occupant.caution_versee = Decimal("0.00")
        self.occupant.save()
        res = self.client.post(reverse("occupant-caution-envoyer", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_envoi_recu_caution_refuse_si_email_absent(self):
        self.occupant.email = ""
        self.occupant.save()
        res = self.client.post(reverse("occupant-caution-envoyer", args=[self.occupant.id]))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_isolation_multi_tenant(self):
        """Un occupant d'un autre propriétaire ne doit jamais être accessible."""
        autre = create_user("autre_bailleur_caution")
        autre_logement = create_logement(autre, "Logement d'autrui")
        autre_occupant = create_occupant(autre_logement)
        autre_occupant.caution_versee = Decimal("300.00")
        autre_occupant.date_versement_caution = date.today()
        autre_occupant.save()

        res_pdf = self.client.get(reverse("occupant-caution-recu", args=[autre_occupant.id]))
        self.assertEqual(res_pdf.status_code, status.HTTP_404_NOT_FOUND)

        res_envoi = self.client.post(reverse("occupant-caution-envoyer", args=[autre_occupant.id]))
        self.assertEqual(res_envoi.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(mail.outbox), 0)


# ─────────────────────────────────────────
# EXPORTS COMPTABLES (Excel / CSV) TESTS
# ─────────────────────────────────────────

class ExportAPITest(AuthenticatedAPITest):
    """NB: le paramètre de requête est 'export_format', jamais 'format' --
    'format' est réservé par DRF (URL_FORMAT_OVERRIDE, utilisé pour la
    négociation de contenu) : passer ?format=xlsx dans les tests ferait
    échouer la requête avec un faux 404 avant même d'atteindre la vue,
    exactement le bug repéré et corrigé pour ces endpoints."""

    def setUp(self):
        super().setUp()
        self.logement = create_logement(self.user)
        self.occupant = create_occupant(self.logement)
        create_paiement(self.occupant, montant=Decimal("25000.50"))
        Depense.objects.create(logement=self.logement, libelle="Réparation", montant=Decimal("5000.00"), date=date.today())

    def test_export_paiements_xlsx(self):
        res = self.client.get(reverse("export-paiements") + "?export_format=xlsx")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(res.content.startswith(b"PK"))  # xlsx = zip

    def test_export_paiements_csv(self):
        res = self.client.get(reverse("export-paiements") + "?export_format=csv")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", res["Content-Type"])
        body = res.content.decode("utf-8-sig")
        self.assertIn("Locataire", body)  # en-tête
        self.assertIn(self.occupant.nom_complet, body)

    def test_export_depenses_csv(self):
        res = self.client.get(reverse("export-depenses") + "?export_format=csv")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.content.decode("utf-8-sig")
        self.assertIn("Réparation", body)

    def test_export_recapitulatif_annuel_csv(self):
        annee = date.today().year
        res = self.client.get(reverse("export-recapitulatif-annuel") + f"?export_format=csv&annee={annee}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.content.decode("utf-8-sig")
        self.assertIn("TOTAL ANNÉE", body)

    def test_export_paiements_filtre_annee_exclut_hors_periode(self):
        res = self.client.get(reverse("export-paiements") + "?export_format=csv&annee=2019")
        body = res.content.decode("utf-8-sig")
        self.assertNotIn(self.occupant.nom_complet, body)

    def test_export_defaut_xlsx_sans_parametre(self):
        """Sans export_format explicite, retombe sur xlsx."""
        res = self.client.get(reverse("export-paiements"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.content.startswith(b"PK"))

    def test_export_isolation_multi_tenant(self):
        """Le filtre logement d'un autre propriétaire doit être refusé (404),
        jamais silencieusement ignoré ni exposer ses données."""
        autre = create_user("autre_bailleur_export")
        autre_logement = create_logement(autre, "Logement d'autrui export")
        res = self.client.get(reverse("export-paiements") + f"?logement={autre_logement.id}")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_export_paiements_ne_contient_pas_donnees_autre_proprietaire(self):
        autre = create_user("autre_bailleur_export2")
        autre_logement = create_logement(autre, "Logement autrui 2")
        autre_occupant = create_occupant(autre_logement, suffix="autrui")
        create_paiement(autre_occupant)

        res = self.client.get(reverse("export-paiements") + "?export_format=csv")
        body = res.content.decode("utf-8-sig")
        self.assertNotIn(autre_occupant.nom_complet, body)
