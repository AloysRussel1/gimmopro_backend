from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal

from .models import Logement, Compartiment, Occupant, Paiement


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def create_logement(nom="Résidence Test", localisation="Montréal", description="Test"):
    return Logement.objects.create(nom=nom, localisation=localisation, description=description)


def create_occupant(logement, suffix="1"):
    return Occupant.objects.create(
        logement=logement,
        email=f"test{suffix}@mail.com",
        telephone="0600000000",
        cni=f"CNI{suffix}",
        nom_complet=f"Locataire {suffix}",
        numero_contrat=f"CONT{suffix}",
        date_debut_contrat=date.today(),
        loyer=Decimal("500.00"),
        date_prochain_paiement=date.today() + timedelta(days=30),
        statut="Actif",
    )


def create_compartiment(logement, occupant=None, nom="Studio 1", type="STUDIO", statut="LIBRE"):
    return Compartiment.objects.create(
        logement=logement,
        occupant=occupant,
        nom=nom,
        type=type,
        statut=statut,
        chambres=1,
        salons=1,
        douches=1,
        cuisines=0,
    )


def create_paiement(occupant):
    return Paiement.objects.create(
        occupant=occupant,
        montant_verse=Decimal("500.00"),
        date_paiement=date.today(),
        date_prochain_paiement=date.today() + timedelta(days=30),
        statut="Payé",
    )


# ─────────────────────────────────────────
# MODEL TESTS
# ─────────────────────────────────────────

class LogementModelTest(TestCase):
    def test_creation_logement(self):
        logement = create_logement()
        self.assertEqual(str(logement), "Résidence Test")
        self.assertEqual(Logement.objects.count(), 1)

    def test_logement_nom_unique(self):
        create_logement()
        with self.assertRaises(Exception):
            create_logement()  # même nom → doit échouer


class OccupantModelTest(TestCase):
    def setUp(self):
        self.logement = create_logement()

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
            numero_contrat="CONT_RETARD",
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
        self.logement = create_logement()

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


class PaiementModelTest(TestCase):
    def setUp(self):
        self.logement = create_logement()
        self.occupant = create_occupant(self.logement)

    def test_creation_paiement(self):
        paiement = create_paiement(self.occupant)
        self.assertEqual(paiement.statut, "Payé")
        self.assertEqual(paiement.occupant, self.occupant)

    def test_paiement_str(self):
        paiement = create_paiement(self.occupant)
        self.assertIn("500", str(paiement))


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
        res = self.client.post(self.register_url, {
            "username": "aloys",
            "password": "motdepasse123",
            "email": "aloys@mail.com",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", res.data)

    def test_register_username_deja_pris(self):
        User.objects.create_user(username="aloys", password="test123")
        res = self.client.post(self.register_url, {
            "username": "aloys",
            "password": "motdepasse123",
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

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
        create_logement("Log A")
        create_logement("Log B")
        res = self.client.get(reverse("logement-list-create"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

    def test_detail_logement(self):
        logement = create_logement()
        res = self.client.get(reverse("logement-detail", args=[logement.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["nom"], logement.nom)

    def test_modifier_logement(self):
        logement = create_logement()
        res = self.client.put(reverse("logement-detail", args=[logement.id]), {
            "nom": "Nouveau Nom",
            "localisation": "Québec",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["nom"], "Nouveau Nom")

    def test_supprimer_logement(self):
        logement = create_logement()
        res = self.client.delete(reverse("logement-detail", args=[logement.id]))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Logement.objects.count(), 0)


# ─────────────────────────────────────────
# COMPARTIMENT API TESTS
# ─────────────────────────────────────────

class CompartimentAPITest(AuthenticatedAPITest):
    def setUp(self):
        super().setUp()
        self.logement = create_logement()

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
        self.logement = create_logement()

    def test_creer_occupant(self):
        res = self.client.post(reverse("occupant-list-create"), {
            "logement": self.logement.id,
            "email": "nouveau@mail.com",
            "telephone": "0600000099",
            "cni": "CNI999",
            "nom_complet": "Jean Dupont",
            "numero_contrat": "CONT999",
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
        self.logement = create_logement()
        self.occupant = create_occupant(self.logement)

    def test_creer_paiement(self):
        res = self.client.post(reverse("paiement-list-create"), {
            "occupant": self.occupant.id,
            "montant_verse": "500.00",
            "date_paiement": str(date.today()),
            "date_prochain_paiement": str(date.today() + timedelta(days=30)),
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
        logement = create_logement()
        occupant = create_occupant(logement)
        create_compartiment(logement, occupant=occupant, statut="OCCUPE")
        create_paiement(occupant)

        res = self.client.get(reverse("dashboard-stats"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("logements", res.data)
        self.assertIn("compartiments", res.data)
        self.assertIn("occupants", res.data)
        self.assertIn("paiements", res.data)
        self.assertEqual(res.data["compartiments"]["occupes"], 1)
        self.assertGreater(res.data["paiements"]["total_revenus"], 0)