from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Logement, Compartiment, Occupant, Paiement
from .serializers import (
    LogementSerializer,
    CompartimentSerializer,
    OccupantSerializer,
    PaiementSerializer,
)


# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email", "")

        if not username or not password:
            return Response(
                {"error": "Username et password sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {"error": "Ce nom d'utilisateur existe déjà."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.create_user(username=username, password=password, email=email)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "message": "Compte créé avec succès.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Déconnexion réussie."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "Token invalide."}, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────

class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total_logements = Logement.objects.count()
        total_compartiments = Compartiment.objects.count()
        compartiments_libres = Compartiment.objects.filter(statut="LIBRE").count()
        compartiments_occupes = Compartiment.objects.filter(statut="OCCUPE").count()

        total_occupants = Occupant.objects.count()
        occupants_actifs = Occupant.objects.filter(statut="Actif").count()
        occupants_en_retard = Occupant.objects.filter(statut="En retard").count()

        paiements = Paiement.objects.all()
        total_revenus = sum(p.montant_verse for p in paiements)
        paiements_en_attente = paiements.filter(statut="En attente").count()
        paiements_payes = paiements.filter(statut="Payé").count()

        return Response(
            {
                "logements": {
                    "total": total_logements,
                },
                "compartiments": {
                    "total": total_compartiments,
                    "libres": compartiments_libres,
                    "occupes": compartiments_occupes,
                },
                "occupants": {
                    "total": total_occupants,
                    "actifs": occupants_actifs,
                    "en_retard": occupants_en_retard,
                },
                "paiements": {
                    "total_revenus": float(total_revenus),
                    "payes": paiements_payes,
                    "en_attente": paiements_en_attente,
                },
            },
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────
# LOGEMENTS
# ─────────────────────────────────────────

class LogementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logements = Logement.objects.all()
        serializer = LogementSerializer(logements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = LogementSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, logement_id):
        logement = get_object_or_404(Logement, id=logement_id)
        serializer = LogementSerializer(logement)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, logement_id):
        logement = get_object_or_404(Logement, id=logement_id)
        serializer = LogementSerializer(logement, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, logement_id):
        logement = get_object_or_404(Logement, id=logement_id)
        logement.delete()
        return Response({"message": "Logement supprimé."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
# COMPARTIMENTS
# ─────────────────────────────────────────

class CompartimentsByLogementView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CompartimentSerializer

    def get_queryset(self):
        logement_id = self.kwargs.get("logement_id")
        return Compartiment.objects.filter(logement_id=logement_id)


class CompartimentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, logement_id):
        logement = get_object_or_404(Logement, id=logement_id)
        serializer = CompartimentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(logement=logement)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompartimentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        compartiment = get_object_or_404(Compartiment, id=compartiment_id)
        serializer = CompartimentSerializer(compartiment)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, compartiment_id):
        compartiment = get_object_or_404(Compartiment, id=compartiment_id)
        serializer = CompartimentSerializer(compartiment, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, compartiment_id):
        compartiment = get_object_or_404(Compartiment, id=compartiment_id)
        compartiment.delete()
        return Response({"message": "Compartiment supprimé."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
# OCCUPANTS
# ─────────────────────────────────────────

class OccupantListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        occupants = Occupant.objects.all()
        serializer = OccupantSerializer(occupants, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Conversion de date si nécessaire
        data = request.data.copy()
        for field in ["date_debut_contrat", "date_prochain_paiement"]:
            if field in data:
                try:
                    data[field] = datetime.strptime(data[field], "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass

        serializer = OccupantSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OccupantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        serializer = OccupantSerializer(occupant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        serializer = OccupantSerializer(occupant, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        occupant.delete()
        return Response({"message": "Occupant supprimé."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
# PAIEMENTS
# ─────────────────────────────────────────

class PaiementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        occupant_id = request.query_params.get("occupant_id")
        if occupant_id:
            paiements = Paiement.objects.filter(occupant_id=occupant_id).order_by("-date_paiement")
        else:
            paiements = Paiement.objects.all().order_by("-date_paiement")
        serializer = PaiementSerializer(paiements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PaiementSerializer(data=request.data)
        if serializer.is_valid():
            paiement = serializer.save()
            # Mettre à jour la date de prochain paiement de l'occupant
            occupant = paiement.occupant
            occupant.date_prochain_paiement = paiement.date_prochain_paiement
            occupant.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaiementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        paiement = get_object_or_404(Paiement, id=paiement_id)
        serializer = PaiementSerializer(paiement)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, paiement_id):
        paiement = get_object_or_404(Paiement, id=paiement_id)
        paiement.delete()
        return Response({"message": "Paiement supprimé."}, status=status.HTTP_204_NO_CONTENT)