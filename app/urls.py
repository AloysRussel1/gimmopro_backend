from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

urlpatterns = [

    # ── Auth ──────────────────────────────────────────
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/',    TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/',  TokenRefreshView.as_view(),    name='token_refresh'),
    path('auth/logout/',   views.LogoutView.as_view(),    name='logout'),

    # ── Dashboard ─────────────────────────────────────
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),

    # ── Logements ─────────────────────────────────────
    path('logements/',              views.LogementListCreateView.as_view(), name='logement-list-create'),
    path('logements/<int:logement_id>/', views.LogementDetailView.as_view(),     name='logement-detail'),

    # ── Compartiments ─────────────────────────────────
    path('logements/<int:logement_id>/compartiments/',        views.CompartimentsByLogementView.as_view(), name='logement-compartiments'),
    path('logements/<int:logement_id>/compartiments/ajouter/', views.CompartimentCreateView.as_view(),     name='add-compartiment'),
    path('compartiments/<int:compartiment_id>/',               views.CompartimentDetailView.as_view(),     name='compartiment-detail'),

    # ── Occupants ─────────────────────────────────────
    path('occupants/',                views.OccupantListCreateView.as_view(), name='occupant-list-create'),
    path('occupants/<int:occupant_id>/', views.OccupantDetailView.as_view(),     name='occupant-detail'),

    # ── Paiements ─────────────────────────────────────
    # GET ?occupant_id=X pour filtrer par occupant
    path('paiements/',                views.PaiementListCreateView.as_view(), name='paiement-list-create'),
    path('paiements/<int:paiement_id>/', views.PaiementDetailView.as_view(),     name='paiement-detail'),
]