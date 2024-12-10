from django.urls import path
from . import views

urlpatterns = [
    path('logements/', views.LogementCreateView.as_view(), name='logement-create'),
    path('logements_list/', views.LogementListView.as_view(), name='logement-list'),
    path('logements/<int:logement_id>/', views.LogementDetailView.as_view(), name='logement-detail'),
    path('logement/<int:logement_id>/ajouter-compartiment/', views.AddCompartimentView.as_view(), name='add-compartiment'),
    path('logements/<int:logement_id>/compartiments/', views.CompartimentsByLogementView.as_view(), name='logement-compartiments'),
    path('compartiments/<int:compartiment_id>/', views.CompartimentDetailView.as_view(), name='compartiment-detail'),
    path('occupants/', views.AddOccupantView.as_view(), name='add_occupant'),
]

