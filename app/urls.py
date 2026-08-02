from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # Auth
    path('auth/register/', views.RegisterView.as_view(),             name='register'),
    path('auth/login/',    views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/',  TokenRefreshView.as_view(),                name='token_refresh'),
    path('auth/logout/',   views.LogoutView.as_view(),      name='logout'),
    path('auth/password-reset/',         views.PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('auth/verify-email/',           views.EmailVerifyRequestView.as_view(),   name='verify-email-request'),
    path('auth/verify-email/confirm/',   views.EmailVerifyConfirmView.as_view(),   name='verify-email-confirm'),

    # Dashboard
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),

    # Profil bailleur
    path('profil/', views.ProfileView.as_view(), name='profile'),

    # Rapport mensuel PDF
    path('rapports/mensuel/', views.RapportMensuelPDFView.as_view(), name='rapport-mensuel'),

    # Logements
    path('logements/',                   views.LogementListCreateView.as_view(), name='logement-list-create'),
    path('logements/<int:logement_id>/', views.LogementDetailView.as_view(),     name='logement-detail'),

    # Compartiments
    path('logements/<int:logement_id>/compartiments/',         views.CompartimentsByLogementView.as_view(), name='logement-compartiments'),
    path('logements/<int:logement_id>/compartiments/ajouter/', views.CompartimentCreateView.as_view(),      name='add-compartiment'),
    path('compartiments/<int:compartiment_id>/',               views.CompartimentDetailView.as_view(),      name='compartiment-detail'),
    path('compartiments/<int:compartiment_id>/historique/',    views.HistoriqueCompartimentView.as_view(),  name='compartiment-historique'),

    # Occupants
    path('occupants/',                           views.OccupantListCreateView.as_view(),  name='occupant-list-create'),
    path('occupants/<int:occupant_id>/',         views.OccupantDetailView.as_view(),      name='occupant-detail'),
    path('occupants/<int:occupant_id>/liberer/', views.OccupantLibererView.as_view(),     name='occupant-liberer'),
    path('occupants/<int:occupant_id>/contrat/', views.OccupantContratPDFView.as_view(),  name='occupant-contrat'),

    # Paiements
    path('paiements/',                        views.PaiementListCreateView.as_view(), name='paiement-list-create'),
    path('paiements/<int:paiement_id>/',      views.PaiementDetailView.as_view(),     name='paiement-detail'),
    path('paiements/<int:paiement_id>/recu/', views.RecuPaiementPDFView.as_view(),    name='paiement-recu'),

    # Reçu public — la racine sert la page HTML (aperçu WhatsApp/OG), pas le PDF directement.
    path('paiements/<int:paiement_id>/recu/public/<str:token>/',               views.RecuPublicLandingView.as_view(),   name='paiement-recu-public'),
    path('paiements/<int:paiement_id>/recu/public/<str:token>/telecharger/',   views.RecuPaiementPublicPDFView.as_view(), name='paiement-recu-public-download'),
    path('paiements/<int:paiement_id>/recu/public/<str:token>/image.png',      views.RecuPublicImageView.as_view(),     name='paiement-recu-public-image'),

    # Dépenses / charges
    path('depenses/',                  views.DepenseListCreateView.as_view(), name='depense-list-create'),
    path('depenses/<int:depense_id>/', views.DepenseDetailView.as_view(),     name='depense-detail'),

    # Documents / pièces jointes
    path('documents/',                            views.DocumentListCreateView.as_view(), name='document-list-create'),
    path('documents/<int:document_id>/',          views.DocumentDetailView.as_view(),     name='document-detail'),
    path('documents/<int:document_id>/fichier/',  views.DocumentDownloadView.as_view(),   name='document-download'),

    # État des lieux
    path('etat-des-lieux/',              views.EtatDesLieuxListCreateView.as_view(), name='edl-list-create'),
    path('etat-des-lieux/<int:edl_id>/', views.EtatDesLieuxDetailView.as_view(),     name='edl-detail'),
    path('etat-des-lieux/<int:edl_id>/pdf/', views.EtatDesLieuxPDFView.as_view(),    name='edl-pdf'),

    # Notifications / rappels d'échéances
    path('notifications/dashboard/', views.NotificationsDashboardView.as_view(), name='notifications-dashboard'),

    # ── ADMINISTRATION (IsAdminUser uniquement — cross-tenant) ──────
    path('admin/stats/',   views.AdminStatsView.as_view(),   name='admin-stats'),
    path('admin/users/',   views.AdminUsersListView.as_view(), name='admin-users-list'),
    path('admin/users/<int:user_id>/toggle-active/',  views.AdminUserToggleActiveView.as_view(),  name='admin-user-toggle-active'),
    path('admin/users/<int:user_id>/reset-password/', views.AdminUserResetPasswordView.as_view(), name='admin-user-reset-password'),

    path('admin/logements/',              views.AdminLogementListCreateView.as_view(), name='admin-logement-list-create'),
    path('admin/logements/<int:pk>/',     views.AdminLogementDetailView.as_view(),     name='admin-logement-detail'),
    path('admin/logements/<int:logement_id>/compartiments/', views.AdminCompartimentsByLogementView.as_view(), name='admin-logement-compartiments'),

    path('admin/occupants/',              views.AdminOccupantListCreateView.as_view(), name='admin-occupant-list-create'),
    path('admin/occupants/<int:occupant_id>/', views.AdminOccupantDetailView.as_view(), name='admin-occupant-detail'),

    path('admin/paiements/',              views.AdminPaiementListCreateView.as_view(), name='admin-paiement-list-create'),
    path('admin/paiements/<int:paiement_id>/', views.AdminPaiementDetailView.as_view(), name='admin-paiement-detail'),

    path('admin/depenses/',               views.AdminDepenseListCreateView.as_view(),  name='admin-depense-list-create'),
    path('admin/depenses/<int:pk>/',      views.AdminDepenseDetailView.as_view(),      name='admin-depense-detail'),

    path('admin/etat-des-lieux/',         views.AdminEtatDesLieuxListCreateView.as_view(), name='admin-edl-list-create'),
    path('admin/etat-des-lieux/<int:pk>/', views.AdminEtatDesLieuxDetailView.as_view(),    name='admin-edl-detail'),

    path('admin/activity-logs/', views.AdminActivityLogListView.as_view(), name='admin-activity-logs'),
]