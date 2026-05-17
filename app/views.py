from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.http import HttpResponse
from datetime import datetime, date
import io

from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Logement, Compartiment, Occupant, Paiement, HistoriqueOccupation
from .serializers import (
    LogementSerializer, CompartimentSerializer,
    OccupantSerializer, PaiementSerializer, HistoriqueOccupationSerializer,
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
        from decimal import Decimal
        paiements      = Paiement.objects.all()
        occupants_actifs = Occupant.objects.filter(actif=True)

        # Retards
        en_retard = occupants_actifs.filter(statut='En retard')

        # Revenus du mois courant
        mois = date.today().month
        annee = date.today().year
        revenus_mois = sum(
            p.montant_verse for p in paiements.filter(
                date_paiement__month=mois, date_paiement__year=annee
            )
        )

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
                'total':     occupants_actifs.count(),
                'actifs':    occupants_actifs.filter(statut='Actif').count(),
                'en_retard': en_retard.count(),
                'retardataires': [
                    {
                        'id': o.id,
                        'nom': o.nom_complet,
                        'compartiment': o.compartiment.nom if o.compartiment else '—',
                        'depuis': str(o.date_prochain_paiement),
                        'loyer': float(o.loyer),
                    }
                    for o in en_retard[:5]
                ],
            },
            'paiements': {
                'total_revenus':  float(sum(p.montant_verse for p in paiements)),
                'revenus_mois':   float(revenus_mois),
                'payes':          paiements.filter(statut='Payé').count(),
                'en_attente':     paiements.filter(statut='En attente').count(),
            },
        })


# ── LOGEMENTS ─────────────────────────────────────

class LogementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(LogementSerializer(Logement.objects.all(), many=True).data)

    def post(self, request):
        s = LogementSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class LogementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, logement_id):
        return Response(LogementSerializer(get_object_or_404(Logement, id=logement_id)).data)

    def put(self, request, logement_id):
        l = get_object_or_404(Logement, id=logement_id)
        s = LogementSerializer(l, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, logement_id):
        get_object_or_404(Logement, id=logement_id).delete()
        return Response(status=204)


# ── COMPARTIMENTS ─────────────────────────────────

class CompartimentsByLogementView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = CompartimentSerializer

    def get_queryset(self):
        qs     = Compartiment.objects.filter(logement_id=self.kwargs['logement_id'])
        statut = self.request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut=statut)
        return qs


class CompartimentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, logement_id):
        logement = get_object_or_404(Logement, id=logement_id)
        s = CompartimentSerializer(data=request.data)
        if s.is_valid():
            s.save(logement=logement)
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class CompartimentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        return Response(CompartimentSerializer(
            get_object_or_404(Compartiment, id=compartiment_id)
        ).data)

    def put(self, request, compartiment_id):
        c = get_object_or_404(Compartiment, id=compartiment_id)
        s = CompartimentSerializer(c, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, compartiment_id):
        get_object_or_404(Compartiment, id=compartiment_id).delete()
        return Response(status=204)


class HistoriqueCompartimentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        historique = HistoriqueOccupation.objects.filter(compartiment_id=compartiment_id)
        return Response(HistoriqueOccupationSerializer(historique, many=True).data)


# ── OCCUPANTS ─────────────────────────────────────

class OccupantListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Occupant.objects.filter(actif=True)
        if request.query_params.get('compartiment_id'):
            qs = qs.filter(compartiment_id=request.query_params['compartiment_id'])
        if request.query_params.get('logement_id'):
            qs = qs.filter(logement_id=request.query_params['logement_id'])
        return Response(OccupantSerializer(qs, many=True).data)

    def post(self, request):
        s = OccupantSerializer(data=request.data)
        if s.is_valid():
            occupant = s.save()
            if occupant.compartiment and not occupant.logement:
                occupant.logement = occupant.compartiment.logement
                Occupant.objects.filter(pk=occupant.pk).update(logement=occupant.logement)
            return Response(OccupantSerializer(occupant).data, status=201)
        return Response(s.errors, status=400)


class OccupantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        return Response(OccupantSerializer(get_object_or_404(Occupant, id=occupant_id)).data)

    def put(self, request, occupant_id):
        o = get_object_or_404(Occupant, id=occupant_id)
        s = OccupantSerializer(o, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, occupant_id):
        get_object_or_404(Occupant, id=occupant_id).delete()
        return Response(status=204)


class OccupantLibererView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        occupant.liberer()
        return Response({'message': f'{occupant.nom_complet} a quitté le logement.'})


class OccupantContratPDFView(APIView):
    """Génère un contrat de bail en PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib import colors
        except ImportError:
            return Response({'error': 'reportlab non installé.'}, status=500)

        occupant = get_object_or_404(Occupant, id=occupant_id)
        buffer   = io.BytesIO()

        doc    = SimpleDocTemplate(buffer, pagesize=A4,
                                   topMargin=2*cm, bottomMargin=2*cm,
                                   leftMargin=2.5*cm, rightMargin=2.5*cm)
        styles = getSampleStyleSheet()
        story  = []

        title_style = ParagraphStyle('title', parent=styles['Title'],
                                     fontSize=18, spaceAfter=12, alignment=1)
        h2_style    = ParagraphStyle('h2', parent=styles['Heading2'],
                                     fontSize=13, spaceAfter=6)
        body_style  = ParagraphStyle('body', parent=styles['Normal'],
                                     fontSize=11, leading=16, spaceAfter=6)

        # En-tête
        story.append(Paragraph("CONTRAT DE BAIL", title_style))
        story.append(Paragraph(f"N° {occupant.numero_contrat}", styles['Normal']))
        story.append(Spacer(1, 0.5*cm))

        # Infos propriétaire / locataire
        story.append(Paragraph("PARTIES", h2_style))

        data = [
            ['BAILLEUR', 'LOCATAIRE'],
            [
                f"{occupant.logement.nom if occupant.logement else '—'}\n{occupant.logement.localisation if occupant.logement else ''}",
                f"{occupant.nom_complet}\nTél: {occupant.telephone}\nCNI: {occupant.cni}"
            ]
        ]
        t = Table(data, colWidths=[8*cm, 8*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#C9A84C')),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,0), 11),
            ('ALIGN',      (0,0), (-1,-1), 'LEFT'),
            ('VALIGN',     (0,0), (-1,-1), 'TOP'),
            ('PADDING',    (0,0), (-1,-1), 8),
            ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.5*cm))

        # Bien loué
        story.append(Paragraph("BIEN LOUÉ", h2_style))
        comp = occupant.compartiment
        if comp:
            story.append(Paragraph(
                f"<b>Logement :</b> {comp.logement.nom} — {comp.logement.localisation}", body_style))
            story.append(Paragraph(
                f"<b>Compartiment :</b> {comp.nom} ({comp.get_type_display()})", body_style))
            story.append(Paragraph(
                f"<b>Composition :</b> {comp.chambres} chambre(s), {comp.salons} salon(s), "
                f"{comp.douches} douche(s), {comp.cuisines} cuisine(s)", body_style))
        story.append(Spacer(1, 0.3*cm))

        # Conditions financières
        story.append(Paragraph("CONDITIONS FINANCIÈRES", h2_style))
        story.append(Paragraph(
            f"<b>Loyer mensuel :</b> {int(occupant.loyer):,} FCFA".replace(',', ' '), body_style))
        story.append(Paragraph(
            f"<b>Date d'entrée :</b> {occupant.date_debut_contrat.strftime('%d/%m/%Y')}", body_style))
        story.append(Paragraph(
            f"<b>Premier paiement :</b> {occupant.date_prochain_paiement.strftime('%d/%m/%Y')}", body_style))
        story.append(Spacer(1, 0.5*cm))

        # Clauses
        story.append(Paragraph("CLAUSES GÉNÉRALES", h2_style))
        clauses = [
            "1. Le loyer est payable d'avance, au plus tard le 5 de chaque mois.",
            "2. Tout retard de paiement supérieur à 15 jours entraînera une pénalité.",
            "3. Le locataire s'engage à maintenir le bien en bon état d'entretien.",
            "4. Le locataire ne peut sous-louer le bien sans accord écrit du bailleur.",
            "5. Le présent contrat est établi pour une durée indéterminée avec préavis d'un mois.",
        ]
        for clause in clauses:
            story.append(Paragraph(clause, body_style))
        story.append(Spacer(1, 1*cm))

        # Signatures
        story.append(Paragraph("SIGNATURES", h2_style))
        sig_data = [
            ['Le Bailleur', 'Le Locataire'],
            ['\n\n\n_________________', '\n\n\n_________________'],
            [f"Fait le {date.today().strftime('%d/%m/%Y')}", ''],
        ]
        sig_table = Table(sig_data, colWidths=[8*cm, 8*cm])
        sig_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN',    (0,0), (-1,-1), 'CENTER'),
            ('PADDING',  (0,0), (-1,-1), 8),
        ]))
        story.append(sig_table)

        doc.build(story)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="contrat_{occupant.numero_contrat}.pdf"'
        )
        return response


# ── PAIEMENTS ─────────────────────────────────────

class PaiementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Paiement.objects.all()
        if request.query_params.get('occupant_id'):
            qs = qs.filter(occupant_id=request.query_params['occupant_id'])
        return Response(PaiementSerializer(qs, many=True).data)

    def post(self, request):
        s = PaiementSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class PaiementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        return Response(PaiementSerializer(get_object_or_404(Paiement, id=paiement_id)).data)

    def delete(self, request, paiement_id):
        get_object_or_404(Paiement, id=paiement_id).delete()
        return Response(status=204)