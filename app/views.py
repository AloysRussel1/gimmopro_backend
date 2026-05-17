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
    LogementSerializer, CompartimentSerializer,
    OccupantSerializer, PaiementSerializer,
)


# ── AUTH ──────────────────────────────────────────

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        email    = request.data.get('email', '')

        if not username or not password:
            return Response({'error': 'Username et password sont requis.'}, status=400)
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Ce nom d\'utilisateur existe déjà.'}, status=400)

        user    = User.objects.create_user(username=username, password=password, email=email)
        refresh = RefreshToken.for_user(user)
        return Response({
            'message': 'Compte créé avec succès.',
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
        }, status=201)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get('refresh'))
            token.blacklist()
            return Response({'message': 'Déconnexion réussie.'})
        except Exception:
            return Response({'error': 'Token invalide.'}, status=400)


# ── DASHBOARD ─────────────────────────────────────

class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        paiements = Paiement.objects.all()
        return Response({
            'logements': {
                'total': Logement.objects.count(),
            },
            'compartiments': {
                'total':   Compartiment.objects.count(),
                'libres':  Compartiment.objects.filter(statut='LIBRE').count(),
                'occupes': Compartiment.objects.filter(statut='OCCUPE').count(),
            },
            'occupants': {
                'total':     Occupant.objects.filter(actif=True).count(),
                'actifs':    Occupant.objects.filter(statut='Actif', actif=True).count(),
                'en_retard': Occupant.objects.filter(statut='En retard', actif=True).count(),
            },
            'paiements': {
                'total_revenus': float(sum(p.montant_verse for p in paiements)),
                'payes':         paiements.filter(statut='Payé').count(),
                'en_attente':    paiements.filter(statut='En attente').count(),
            },
        })


# ── LOGEMENTS ─────────────────────────────────────

class LogementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = LogementSerializer(Logement.objects.all(), many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = LogementSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class LogementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, logement_id):
        logement   = get_object_or_404(Logement, id=logement_id)
        serializer = LogementSerializer(logement)
        return Response(serializer.data)

    def put(self, request, logement_id):
        logement   = get_object_or_404(Logement, id=logement_id)
        serializer = LogementSerializer(logement, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, logement_id):
        get_object_or_404(Logement, id=logement_id).delete()
        return Response({'message': 'Logement supprimé.'}, status=204)


# ── COMPARTIMENTS ─────────────────────────────────

class CompartimentsByLogementView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = CompartimentSerializer

    def get_queryset(self):
        qs = Compartiment.objects.filter(logement_id=self.kwargs['logement_id'])
        statut = self.request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut=statut)
        return qs


class CompartimentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, logement_id):
        logement   = get_object_or_404(Logement, id=logement_id)
        serializer = CompartimentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(logement=logement)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class CompartimentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        c = get_object_or_404(Compartiment, id=compartiment_id)
        return Response(CompartimentSerializer(c).data)

    def put(self, request, compartiment_id):
        c          = get_object_or_404(Compartiment, id=compartiment_id)
        serializer = CompartimentSerializer(c, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, compartiment_id):
        get_object_or_404(Compartiment, id=compartiment_id).delete()
        return Response({'message': 'Compartiment supprimé.'}, status=204)


# ── OCCUPANTS ─────────────────────────────────────

class OccupantListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Occupant.objects.filter(actif=True)
        compartiment_id = request.query_params.get('compartiment_id')
        logement_id     = request.query_params.get('logement_id')
        if compartiment_id:
            qs = qs.filter(compartiment_id=compartiment_id)
        if logement_id:
            qs = qs.filter(logement_id=logement_id)
        return Response(OccupantSerializer(qs, many=True).data)

    def post(self, request):
        serializer = OccupantSerializer(data=request.data)
        if serializer.is_valid():
            occupant = serializer.save()
            # Lier automatiquement le logement depuis le compartiment
            if occupant.compartiment and not occupant.logement:
                occupant.logement = occupant.compartiment.logement
                occupant.save()
            return Response(OccupantSerializer(occupant).data, status=201)
        return Response(serializer.errors, status=400)


class OccupantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        o = get_object_or_404(Occupant, id=occupant_id)
        return Response(OccupantSerializer(o).data)

    def put(self, request, occupant_id):
        o          = get_object_or_404(Occupant, id=occupant_id)
        serializer = OccupantSerializer(o, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, occupant_id):
        get_object_or_404(Occupant, id=occupant_id).delete()
        return Response({'message': 'Occupant supprimé.'}, status=204)


class OccupantLibererView(APIView):
    """Marque un occupant comme parti et libère son compartiment."""
    permission_classes = [IsAuthenticated]

    def post(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        occupant.liberer()
        return Response({'message': f'{occupant.nom_complet} a quitté le logement.'})


# ── PAIEMENTS ─────────────────────────────────────

class PaiementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Paiement.objects.all()
        occupant_id = request.query_params.get('occupant_id')
        if occupant_id:
            qs = qs.filter(occupant_id=occupant_id)
        return Response(PaiementSerializer(qs, many=True).data)

    def post(self, request):
        serializer = PaiementSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class PaiementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        p = get_object_or_404(Paiement, id=paiement_id)
        return Response(PaiementSerializer(p).data)

    def delete(self, request, paiement_id):
        get_object_or_404(Paiement, id=paiement_id).delete()
        return Response({'message': 'Paiement supprimé.'}, status=204)