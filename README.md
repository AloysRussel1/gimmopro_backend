# 🏠 GimmoPro — Backend API

> API REST Django pour la gestion locative · JWT · PDF · PostgreSQL-ready

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.1-green?logo=django)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/DRF-3.14-red)](https://www.django-rest-framework.org)
[![Railway](https://img.shields.io/badge/Deployed-Railway-purple)](https://railway.app)
[![Tests](https://img.shields.io/badge/Tests-31%20passing-brightgreen)](#tests)

---

## 📋 À propos

GimmoPro est une plateforme de gestion locative développée pour digitaliser la gestion de biens immobiliers au Cameroun. Elle permet à un propriétaire de gérer ses logements, compartiments, locataires et paiements depuis n'importe quel appareil.

**Problème résolu** : Remplace la gestion manuscrite (cahiers, stylos) par une application mobile accessible partout.

---

## ✨ Fonctionnalités

### 🏠 Gestion des logements
- CRUD complet sur les logements et compartiments (appartements, studios, chambres, boutiques)
- Statut automatique libre/occupé à l'entrée et au départ d'un locataire
- Historique complet d'occupation par compartiment

### 👤 Gestion des locataires
- Enregistrement avec lien direct au compartiment occupé
- Numéro de contrat généré automatiquement (`CONT-2025-0001`)
- Calcul automatique du statut (Actif / En retard)
- Génération de contrat de bail en PDF

### 💳 Gestion des paiements
- Paiements multi-mois (1, 2, 3, 6, 12 mois)
- Calcul automatique de la période couverte
- Mise à jour automatique de la date de prochain paiement
- Génération de reçu de paiement en PDF

### 📊 Dashboard & Rapports
- Statistiques en temps réel (taux d'occupation, revenus, retards)
- Rapport mensuel complet en PDF (encaissements, retards, résumé financier)
- Liste des locataires en retard avec montants dus

### 🔐 Authentification
- JWT (access + refresh tokens)
- Connexion par **username ou email**
- Inscription avec validation email unique
- Blacklist des tokens à la déconnexion

---

## 🛠 Stack technique

| Couche | Technologie |
|--------|------------|
| Framework | Django 5.1 + Django REST Framework 3.14 |
| Auth | djangorestframework-simplejwt |
| PDF | ReportLab |
| Base de données | SQLite (dev) / PostgreSQL (prod) |
| Déploiement | Railway |
| Auth backend | Custom (email ou username) |

---

## 🗄 Modèles de données

```
Logement
  └── Compartiment (APPARTEMENT / STUDIO / CHAMBRE / BOUTIQUE)
        ├── Occupant (locataire actif)
        ├── HistoriqueOccupation (anciens locataires)
        └── Paiement (multi-mois)
```

---

## 🚀 Installation locale

### Prérequis
- Python 3.11+
- pip

### Étapes

```bash
# 1. Cloner le repo
git clone https://github.com/AloysRussel1/gimmopro_backend.git
cd gimmopro_backend

# 2. Créer et activer l'environnement virtuel
python -m venv venv
source venv/bin/activate        # Linux/Mac
.\venv\Scripts\Activate.ps1    # Windows PowerShell

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Appliquer les migrations
python manage.py migrate

# 5. Créer un superutilisateur
python manage.py createsuperuser

# 6. Lancer le serveur
python manage.py runserver
```

L'API est disponible sur `http://localhost:8000/api/`

---

## 📡 Endpoints API

### Authentification
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| POST | `/api/auth/register/` | Créer un compte |
| POST | `/api/auth/login/` | Connexion (username ou email) |
| POST | `/api/auth/refresh/` | Rafraîchir le token |
| POST | `/api/auth/logout/` | Déconnexion |

### Logements
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET/POST | `/api/logements/` | Liste et création |
| GET/PUT/DELETE | `/api/logements/{id}/` | Détail, modification, suppression |
| GET | `/api/logements/{id}/compartiments/` | Compartiments d'un logement |

### Occupants
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET/POST | `/api/occupants/` | Liste et création |
| GET/PUT/DELETE | `/api/occupants/{id}/` | Détail, modification, suppression |
| POST | `/api/occupants/{id}/liberer/` | Enregistrer le départ |
| GET | `/api/occupants/{id}/contrat/` | Télécharger le contrat PDF |

### Paiements
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET/POST | `/api/paiements/` | Liste et enregistrement |
| GET | `/api/paiements/{id}/recu/` | Télécharger le reçu PDF |

### Rapports
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/api/dashboard/stats/` | Statistiques globales |
| GET | `/api/rapports/mensuel/?mois=5&annee=2026` | Rapport mensuel PDF |

---

## 🧪 Tests

```bash
python manage.py test app
```

**31 tests** couvrant :
- ✅ Modèles (création, logique métier, cascade)
- ✅ Authentification (register, login, token, accès refusé)
- ✅ API Logements (CRUD complet)
- ✅ API Compartiments (CRUD, filtres)
- ✅ API Occupants (création, suppression)
- ✅ API Paiements (création, filtre par occupant)
- ✅ Dashboard (stats en temps réel)

---

## 🌐 Démo en ligne

**Frontend** : [gimmopro.vercel.app](https://gimmopro.vercel.app)  
**API** : [gimmoprobackend-production.up.railway.app](https://gimmoprobackend-production.up.railway.app)

---

## 👨‍💻 Auteur

**Aloys Russel Tonfo**  
Étudiant en Génie informatique — Polytechnique Montréal  
[github.com/AloysRussel1](https://github.com/AloysRussel1)