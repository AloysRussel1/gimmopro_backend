from django.shortcuts import render
from django.shortcuts import get_object_or_404
from datetime import datetime
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from .models import Logement, Compartiment
from .serializers import LogementSerializer, CompartimentSerializer, OccupantSerializer

class LogementCreateView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = LogementSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogementListView(APIView):
    def get(self, request):
        logements = Logement.objects.all()
        serializer = LogementSerializer(logements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class LogementDetailView(APIView):
    def get(self, request, logement_id, *args, **kwargs):
        logement = get_object_or_404(Logement, id=logement_id)  # Récupérer le logement par ID
        serializer = LogementSerializer(logement)
        return Response(serializer.data, status=status.HTTP_200_OK)
class AddCompartimentView(APIView):
    def post(self, request, logement_id):
        logement = Logement.objects.get(id=logement_id)  # Récupérer le logement
        serializer = CompartimentSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(logement=logement)  # Associer le logement au compartiment
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class CompartimentsByLogementView(ListAPIView):
    serializer_class = CompartimentSerializer

    def get_queryset(self):
        logement_id = self.kwargs.get('logement_id')
        return Compartiment.objects.filter(logement_id=logement_id)
    
class CompartimentDetailView(APIView):
    def get(self, request, compartiment_id, *args, **kwargs):
        compartiment = get_object_or_404(Compartiment, id=compartiment_id)  # Récupérer le compartiment par ID
        serializer = CompartimentSerializer(compartiment)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class AddOccupantView(APIView):
    def post(self, request, logement_id=None):
        # Convertir les dates en format YYYY-MM-DD si possible
        date_fields = ['date_debut_contrat', 'date_prochain_paiement']
        for field in date_fields:
            if field in request.data:
                try:
                    request.data[field] = datetime.strptime(request.data[field], "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    # Ignorer si la conversion échoue, le sérialiseur gérera l'erreur
                    pass

        # Récupérer le logement
        logement = None
        if logement_id:
            try:
                logement = Logement.objects.get(id=logement_id)
            except Logement.DoesNotExist:
                return Response({"error": "Logement non trouvé."}, status=status.HTTP_404_NOT_FOUND)

        # Sérialiser l'occupant
        serializer = OccupantSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(logement=logement)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
