from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.http import HttpResponse
from datetime import datetime, date
import io
import calendar

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


# ── HELPERS PDF ───────────────────────────────────

def get_reportlab():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        return A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors
    except ImportError:
        return None


# ── AUTH ──────────────────────────────────────────

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')
        email    = request.data.get('email', '').strip()

        if not username or not password:
            return Response({'error': 'Username et password sont requis.'}, status=400)
        if len(password) < 8:
            return Response({'error': 'Le mot de passe doit contenir au moins 8 caractères.'}, status=400)
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Ce nom d\'utilisateur existe déjà.'}, status=400)
        if email and User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'Cet email est déjà associé à un compte.'}, status=400)

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
        paiements        = Paiement.objects.all()
        occupants_actifs = Occupant.objects.filter(actif=True)
        en_retard        = occupants_actifs.filter(statut='En retard')
        mois  = date.today().month
        annee = date.today().year
        revenus_mois = sum(
            p.montant_verse for p in paiements.filter(
                date_paiement__month=mois, date_paiement__year=annee
            )
        )
        return Response({
            'logements':    { 'total': Logement.objects.count() },
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
                        'id': o.id, 'nom': o.nom_complet,
                        'compartiment': o.compartiment.nom if o.compartiment else '—',
                        'depuis': str(o.date_prochain_paiement),
                        'loyer':  float(o.loyer),
                    }
                    for o in en_retard[:5]
                ],
            },
            'paiements': {
                'total_revenus': float(sum(p.montant_verse for p in paiements)),
                'revenus_mois':  float(revenus_mois),
                'payes':         paiements.filter(statut='Payé').count(),
                'en_attente':    paiements.filter(statut='En attente').count(),
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
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        rl = get_reportlab()
        if not rl:
            return Response({'error': 'reportlab non installé.'}, status=500)
        A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

        occupant = get_object_or_404(Occupant, id=occupant_id)
        buffer   = io.BytesIO()
        doc      = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
        styles   = getSampleStyleSheet()
        story    = []

        title_style = ParagraphStyle('title', parent=styles['Title'], fontSize=18, spaceAfter=12, alignment=1)
        h2_style    = ParagraphStyle('h2', parent=styles['Heading2'], fontSize=13, spaceAfter=6)
        body_style  = ParagraphStyle('body', parent=styles['Normal'], fontSize=11, leading=16, spaceAfter=6)

        story.append(Paragraph("CONTRAT DE BAIL", title_style))
        story.append(Paragraph(f"N° {occupant.numero_contrat}", styles['Normal']))
        story.append(Spacer(1, 0.5*cm))

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
            ('ALIGN',      (0,0), (-1,-1), 'LEFT'),
            ('VALIGN',     (0,0), (-1,-1), 'TOP'),
            ('PADDING',    (0,0), (-1,-1), 8),
            ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph("BIEN LOUÉ", h2_style))
        comp = occupant.compartiment
        if comp:
            story.append(Paragraph(f"<b>Logement :</b> {comp.logement.nom} — {comp.logement.localisation}", body_style))
            story.append(Paragraph(f"<b>Compartiment :</b> {comp.nom} ({comp.get_type_display()})", body_style))
            story.append(Paragraph(f"<b>Composition :</b> {comp.chambres} chambre(s), {comp.salons} salon(s), {comp.douches} douche(s), {comp.cuisines} cuisine(s)", body_style))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("CONDITIONS FINANCIÈRES", h2_style))
        story.append(Paragraph(f"<b>Loyer mensuel :</b> {int(occupant.loyer):,} FCFA".replace(',', ' '), body_style))
        story.append(Paragraph(f"<b>Date d'entrée :</b> {occupant.date_debut_contrat.strftime('%d/%m/%Y')}", body_style))
        story.append(Paragraph(f"<b>Premier paiement :</b> {occupant.date_prochain_paiement.strftime('%d/%m/%Y')}", body_style))
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph("CLAUSES GÉNÉRALES", h2_style))
        for clause in [
            "1. Le loyer est payable d'avance, au plus tard le 5 de chaque mois.",
            "2. Tout retard de paiement supérieur à 15 jours entraînera une pénalité.",
            "3. Le locataire s'engage à maintenir le bien en bon état d'entretien.",
            "4. Le locataire ne peut sous-louer le bien sans accord écrit du bailleur.",
            "5. Le présent contrat est établi pour une durée indéterminée avec préavis d'un mois.",
        ]:
            story.append(Paragraph(clause, body_style))
        story.append(Spacer(1, 1*cm))

        story.append(Paragraph("SIGNATURES", h2_style))
        sig_table = Table([
            ['Le Bailleur', 'Le Locataire'],
            ['\n\n\n_________________', '\n\n\n_________________'],
            [f"Fait le {date.today().strftime('%d/%m/%Y')}", ''],
        ], colWidths=[8*cm, 8*cm])
        sig_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN',    (0,0), (-1,-1), 'CENTER'),
            ('PADDING',  (0,0), (-1,-1), 8),
        ]))
        story.append(sig_table)

        doc.build(story)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="contrat_{occupant.numero_contrat}.pdf"'
        return response


# ── REÇU DE PAIEMENT PDF ──────────────────────────

class RecuPaiementPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        rl = get_reportlab()
        if not rl:
            return Response({'error': 'reportlab non installé.'}, status=500)
        A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

        paiement = get_object_or_404(Paiement, id=paiement_id)
        occupant = paiement.occupant
        buffer   = io.BytesIO()
        doc      = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
        styles   = getSampleStyleSheet()
        story    = []

        title_style  = ParagraphStyle('title',  parent=styles['Title'],   fontSize=20, spaceAfter=6,  alignment=1)
        center_style = ParagraphStyle('center', parent=styles['Normal'],  fontSize=11, spaceAfter=4,  alignment=1)
        h2_style     = ParagraphStyle('h2',     parent=styles['Heading2'],fontSize=13, spaceAfter=6)
        body_style   = ParagraphStyle('body',   parent=styles['Normal'],  fontSize=11, leading=16, spaceAfter=4)

        # En-tête
        story.append(Paragraph("REÇU DE PAIEMENT", title_style))
        story.append(Paragraph(f"N° REÇU-{paiement.id:04d}", center_style))
        story.append(Paragraph(f"Date : {paiement.date_paiement.strftime('%d/%m/%Y')}", center_style))
        story.append(Spacer(1, 0.5*cm))

        # Montant en évidence
        montant_data = [[f"{int(paiement.montant_verse):,} FCFA".replace(',', ' ')]]
        montant_table = Table(montant_data, colWidths=[16*cm])
        montant_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#C9A84C')),
            ('TEXTCOLOR',  (0,0), (-1,-1), colors.HexColor('#0A0A0F')),
            ('FONTNAME',   (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 24),
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('PADDING',    (0,0), (-1,-1), 16),
            ('BORDERRADIUS',(0,0),(-1,-1), 8),
        ]))
        story.append(montant_table)
        story.append(Spacer(1, 0.5*cm))

        # Infos locataire
        story.append(Paragraph("LOCATAIRE", h2_style))
        story.append(Paragraph(f"<b>Nom :</b> {occupant.nom_complet}", body_style))
        story.append(Paragraph(f"<b>Téléphone :</b> {occupant.telephone}", body_style))
        if occupant.compartiment:
            story.append(Paragraph(f"<b>Logement :</b> {occupant.compartiment.logement.nom}", body_style))
            story.append(Paragraph(f"<b>Compartiment :</b> {occupant.compartiment.nom}", body_style))
        story.append(Spacer(1, 0.3*cm))

        # Détails paiement
        story.append(Paragraph("DÉTAILS DU PAIEMENT", h2_style))
        details = [
            ['Description', 'Valeur'],
            ['Loyer mensuel',       f"{int(occupant.loyer):,} FCFA".replace(',', ' ')],
            ['Nombre de mois',      str(paiement.nombre_mois)],
            ['Période couverte',    f"Du {paiement.date_debut_periode.strftime('%d/%m/%Y')} au {paiement.date_fin_periode.strftime('%d/%m/%Y')}"],
            ['Montant total versé', f"{int(paiement.montant_verse):,} FCFA".replace(',', ' ')],
            ['Prochain paiement',   f"À partir du {(paiement.date_fin_periode).strftime('%d/%m/%Y')}"],
            ['Statut',              paiement.statut],
        ]
        if paiement.note:
            details.append(['Note', paiement.note])

        t = Table(details, colWidths=[8*cm, 8*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1C1C27')),
            ('TEXTCOLOR',     (0,0), (-1,0),  colors.HexColor('#C9A84C')),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 10),
            ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING',       (0,0), (-1,-1), 8),
            ('GRID',          (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
            ('FONTNAME',      (0,1), (0,-1),  'Helvetica-Bold'),
        ]))
        story.append(t)
        story.append(Spacer(1, 1*cm))

        # Signature
        story.append(Paragraph("Signature du bailleur", h2_style))
        story.append(Paragraph("\n\n\n_________________", body_style))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(f"Émis le {date.today().strftime('%d/%m/%Y')}", center_style))

        doc.build(story)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="recu_paiement_{paiement.id:04d}.pdf"'
        return response


# ── RAPPORT MENSUEL PDF ───────────────────────────

class RapportMensuelPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rl = get_reportlab()
        if not rl:
            return Response({'error': 'reportlab non installé.'}, status=500)
        A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

        mois_param  = request.query_params.get('mois',  date.today().month)
        annee_param = request.query_params.get('annee', date.today().year)
        mois  = int(mois_param)
        annee = int(annee_param)

        nom_mois = ['', 'Janvier','Février','Mars','Avril','Mai','Juin',
                    'Juillet','Août','Septembre','Octobre','Novembre','Décembre'][mois]

        paiements_mois = Paiement.objects.filter(
            date_paiement__month=mois, date_paiement__year=annee
        ).select_related('occupant', 'occupant__compartiment', 'occupant__logement')

        occupants_actifs = Occupant.objects.filter(actif=True).select_related('compartiment', 'logement')
        total_attendu    = sum(o.loyer for o in occupants_actifs)
        total_encaisse   = sum(p.montant_verse for p in paiements_mois)
        occupants_payes  = set(p.occupant_id for p in paiements_mois)
        occupants_retard = [o for o in occupants_actifs if o.id not in occupants_payes]

        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)
        styles = getSampleStyleSheet()
        story  = []

        title_style  = ParagraphStyle('title',  parent=styles['Title'],   fontSize=18, spaceAfter=4,  alignment=1)
        center_style = ParagraphStyle('center', parent=styles['Normal'],  fontSize=11, spaceAfter=4,  alignment=1)
        h2_style     = ParagraphStyle('h2',     parent=styles['Heading2'],fontSize=13, spaceAfter=6,  spaceBefore=12)
        body_style   = ParagraphStyle('body',   parent=styles['Normal'],  fontSize=10, leading=14, spaceAfter=4)

        story.append(Paragraph(f"RAPPORT MENSUEL — {nom_mois} {annee}", title_style))
        story.append(Paragraph(f"Généré le {date.today().strftime('%d/%m/%Y')}", center_style))
        story.append(Spacer(1, 0.5*cm))

        # Résumé financier
        story.append(Paragraph("RÉSUMÉ FINANCIER", h2_style))
        resume = [
            ['', ''],
            ['Total attendu ce mois',   f"{int(total_attendu):,} FCFA".replace(',', ' ')],
            ['Total encaissé',          f"{int(total_encaisse):,} FCFA".replace(',', ' ')],
            ['Reste à encaisser',       f"{int(total_attendu - total_encaisse):,} FCFA".replace(',', ' ')],
            ['Taux de recouvrement',    f"{int((total_encaisse/total_attendu*100) if total_attendu > 0 else 0)} %"],
            ['Nombre de paiements',     str(paiements_mois.count())],
            ['Locataires en retard',    str(len(occupants_retard))],
        ]
        t_resume = Table(resume, colWidths=[9*cm, 7*cm])
        t_resume.setStyle(TableStyle([
            ('SPAN',         (0,0), (-1,0)),
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#C9A84C')),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.HexColor('#0A0A0F')),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 11),
            ('ALIGN',        (1,1), (1,-1),  'RIGHT'),
            ('FONTNAME',     (0,1), (0,-1),  'Helvetica-Bold'),
            ('PADDING',      (0,0), (-1,-1), 8),
            ('GRID',         (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#F5F5F5')]),
        ]))
        story.append(t_resume)

        # Paiements reçus
        if paiements_mois.exists():
            story.append(Paragraph("PAIEMENTS REÇUS", h2_style))
            rows = [['Locataire', 'Compartiment', 'Période', 'Montant', 'Date']]
            for p in paiements_mois:
                rows.append([
                    p.occupant.nom_complet,
                    p.occupant.compartiment.nom if p.occupant.compartiment else '—',
                    f"{p.date_debut_periode.strftime('%d/%m')} → {p.date_fin_periode.strftime('%d/%m/%Y')}",
                    f"{int(p.montant_verse):,}".replace(',', ' '),
                    p.date_paiement.strftime('%d/%m/%Y'),
                ])
            t_pay = Table(rows, colWidths=[4.5*cm, 3.5*cm, 4*cm, 3*cm, 2.5*cm])
            t_pay.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1C1C27')),
                ('TEXTCOLOR',     (0,0), (-1,0),  colors.HexColor('#C9A84C')),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
                ('PADDING',       (0,0), (-1,-1), 6),
                ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),  [colors.white, colors.HexColor('#F5F5F5')]),
            ]))
            story.append(t_pay)

        # Retards
        if occupants_retard:
            story.append(Paragraph("LOCATAIRES EN RETARD", h2_style))
            rows_r = [['Locataire', 'Téléphone', 'Compartiment', 'Loyer mensuel']]
            for o in occupants_retard:
                rows_r.append([
                    o.nom_complet, o.telephone,
                    o.compartiment.nom if o.compartiment else '—',
                    f"{int(o.loyer):,} FCFA".replace(',', ' '),
                ])
            t_retard = Table(rows_r, colWidths=[4.5*cm, 3.5*cm, 4*cm, 4*cm])
            t_retard.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#E05C5C')),
                ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
                ('PADDING',       (0,0), (-1,-1), 6),
                ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),  [colors.HexColor('#FFF5F5'), colors.white]),
            ]))
            story.append(t_retard)

        doc.build(story)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_{nom_mois}_{annee}.pdf"'
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