import re
import os
import csv
import logging

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse, FileResponse, Http404
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.decorators import method_decorator
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from dateutil.relativedelta import relativedelta
from datetime import datetime, date, timedelta
from decimal import Decimal
import io
import calendar

from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Logement, Compartiment, Occupant, Paiement, HistoriqueOccupation, Profile, Depense,
    Document, EtatDesLieux, ActivityLog,
)
from .serializers import (
    LogementSerializer, CompartimentSerializer,
    OccupantSerializer, PaiementSerializer, HistoriqueOccupationSerializer,
    ProfileSerializer, DepenseSerializer,
    DocumentSerializer, EtatDesLieuxSerializer,
    AdminLogementSerializer, AdminUserSerializer, ActivityLogSerializer,
)
from .pagination import StandardResultsSetPagination
from .utils import (
    montant_en_lettres_fcfa, fcfa_arrondi, verify_recu_token,
    get_logement_or_404, get_compartiment_or_404, get_occupant_or_404, get_paiement_or_404,
    get_depense_or_404, get_document_or_404, get_etat_des_lieux_or_404,
    make_password_reset_token, verify_password_reset_token, envoyer_email_reset_password,
    make_email_verify_token, verify_email_verify_token, envoyer_email_verification,
    envoyer_email_caution_recu,
    _generer_username_depuis_email, log_activity,
)

NOM_MOIS = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
            'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

logger = logging.getLogger(__name__)


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
        email    = request.data.get('email', '').strip()
        password = request.data.get('password', '')
        accept_terms = request.data.get('accept_terms')

        if not email or not password:
            return Response({'error': 'Email et mot de passe sont requis.'}, status=400)
        try:
            validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'Adresse email invalide.'}, status=400)
        if len(password) < 8:
            return Response({'error': 'Le mot de passe doit contenir au moins 8 caractères.'}, status=400)
        # Vérifié aussi côté frontend, mais ne jamais faire confiance
        # uniquement à une validation client -- un appel direct à l'API
        # pourrait sinon créer un compte sans preuve d'acceptation. Comparé
        # en texte plutôt qu'avec "is True" : un payload multipart/form-data
        # (au lieu de JSON) transmet toujours un booléen sous forme de
        # chaîne ("True"/"False"), jamais un vrai bool Python.
        if str(accept_terms).lower() != 'true':
            return Response({'error': "Vous devez accepter les conditions d'utilisation et la politique de confidentialité."}, status=400)
        if User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'Cet email est déjà associé à un compte.'}, status=400)

        try:
            with transaction.atomic():
                username = _generer_username_depuis_email(email)
                # is_active=False : le compte ne peut pas se connecter tant que
                # l'email n'est pas confirmé — EmailOrUsernameBackend/SimpleJWT
                # refusent déjà l'auth pour un user inactif (Django gère ça
                # nativement, rien à ajouter côté login). Le compte est activé
                # par EmailVerifyConfirmView.
                user = User.objects.create_user(
                    username=username, password=password, email=email, is_active=False
                )
                # Horodatage de preuve : la validation ci-dessus garantit déjà
                # accept_terms is True à ce stade.
                Profile.objects.create(user=user, is_verified=False, terms_accepted_at=timezone.now())
                log_activity(user, 'REGISTER', description=email)
        except IntegrityError:
            # Filet de sécurité derrière le check ci-dessus : deux inscriptions
            # quasi simultanées avec le même email (ou une dérivation de
            # username qui collisionne) peuvent passer le premier check puis
            # se percuter à l'écriture. Avant ce filet, ce cas remontait une
            # IntegrityError non gérée -> 500 brut au lieu d'un 400 propre.
            logger.warning("Inscription en doublon détectée à l'écriture pour %s", email)
            return Response({'error': 'Cet email est déjà associé à un compte.'}, status=400)
        except Exception:
            logger.exception("Erreur inattendue lors de la création du compte pour %s", email)
            return Response({'error': "Erreur lors de la création du compte. Réessayez plus tard."}, status=500)

        token = make_email_verify_token(user)
        try:
            envoyer_email_verification(user, token)
        except Exception as e:
            # L'échec d'envoi ne doit jamais faire échouer la création du compte
            # (l'utilisateur pourra toujours redemander l'envoi via
            # EmailVerifyRequestView) — mais il ne doit plus jamais être invisible.
            # Filet de secours supplémentaire : le lien complet est loggé pour de
            # vrai (pas juste l'erreur), pour pouvoir activer le compte à la main
            # depuis les logs Railway le temps de corriger le SMTP en prod.
            logger.error("Échec de l'envoi de l'email de vérification à %s : %s", email, e, exc_info=True)
            logger.warning(
                "Lien d'activation de secours pour %s : %s/verifier-email?token=%s",
                email, settings.FRONTEND_URL, token,
            )

        # Pas de JWT ici : le compte est inactif tant que l'email n'est pas
        # confirmé, donc rien à connecter pour l'instant.
        return Response({
            'message': "Compte créé avec succès. Un email de confirmation vous a été envoyé.",
        }, status=201)


class LoggingTokenObtainPairSerializer(TokenObtainPairSerializer):
    """SimpleJWT n'émet jamais django.contrib.auth.signals.user_logged_in pour
    une connexion JWT (update_last_login, quand actif, est appelé en direct
    dans validate() — pas via signal) : un receiver de signal ne se
    déclencherait donc jamais ici. Il faut passer par le serializer."""
    def validate(self, attrs):
        data = super().validate(attrs)  # lève avant cette ligne si échec -> échecs de connexion non logués (voulu)
        log_activity(self.user, 'LOGIN', description=self.user.email)
        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = LoggingTokenObtainPairSerializer
    # Explicite plutôt qu'implicite : TokenViewBase (SimpleJWT) met déjà
    # permission_classes=() et authentication_classes=() par défaut (vérifié
    # sur la classe réellement chargée), donc ceci ne change rien au
    # comportement -- mais documente noir sur blanc que le login doit rester
    # accessible sans JWT préalable (on ne peut pas exiger un token pour
    # obtenir un token).
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Log de diagnostic temporaire : la requête HTTP brute telle qu'elle
        # arrive vraiment (avant tout traitement DRF), pour distinguer un
        # problème de payload/en-têtes d'un problème d'identifiants — jamais
        # le mot de passe en clair, et le token Authorization tronqué seulement.
        safe_data = dict(request.data)
        if 'password' in safe_data:
            safe_data['password'] = f"(longueur={len(str(safe_data['password']))})"
        auth_header = request.headers.get('Authorization', '')
        logger.warning(
            "CustomTokenObtainPairView.post() -- data=%r | Content-Type=%r | Origin=%r | "
            "Authorization=%s",
            safe_data,
            request.headers.get('Content-Type'),
            request.headers.get('Origin'),
            (auth_header[:20] + '…') if auth_header else '(absent)',
        )
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get('refresh'))
            token.blacklist()
            return Response({'message': 'Déconnexion réussie.'})
        except Exception:
            return Response({'error': 'Token invalide.'}, status=400)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if email:
            user = User.objects.filter(email__iexact=email).first()
            if user:
                try:
                    envoyer_email_reset_password(user, make_password_reset_token(user))
                except Exception as e:
                    logger.error("Échec de l'envoi de l'email de réinitialisation à %s : %s", email, e, exc_info=True)
        # Réponse identique que le compte existe ou non — évite de révéler
        # par ce biais quelles adresses email sont enregistrées (énumération).
        return Response({'message': "Si un compte existe pour cet email, un lien de réinitialisation vient d'être envoyé."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token        = request.data.get('token', '')
        new_password = request.data.get('new_password', '')

        if not token or not new_password:
            return Response({'error': 'Paramètres manquants.'}, status=400)
        if len(new_password) < 8:
            return Response({'error': 'Le mot de passe doit contenir au moins 8 caractères.'}, status=400)

        user = verify_password_reset_token(token, User)
        if not user:
            return Response({'error': 'Lien invalide ou expiré. Refaites une demande de réinitialisation.'}, status=400)

        user.set_password(new_password)
        user.save(update_fields=['password'])
        return Response({'message': 'Mot de passe mis à jour avec succès. Vous pouvez maintenant vous connecter.'})


class EmailVerifyRequestView(APIView):
    """Renvoie un email de vérification (ex: le premier lien a expiré, ou
    l'envoi initial a échoué). AllowAny + par email : un utilisateur fraîchement
    inscrit est is_active=False, donc SANS JWT — il ne pourrait jamais atteindre
    cet endpoint s'il fallait être authentifié. Réponse identique que le compte
    existe/soit déjà vérifié ou non, pour ne pas permettre l'énumération
    d'emails (même logique que PasswordResetRequestView)."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if email:
            user = User.objects.filter(email__iexact=email, is_active=False).first()
            if user:
                token = make_email_verify_token(user)
                try:
                    envoyer_email_verification(user, token)
                except Exception as e:
                    logger.error("Échec du renvoi de l'email de vérification à %s : %s", email, e, exc_info=True)
                    logger.warning(
                        "Lien d'activation de secours pour %s : %s/verifier-email?token=%s",
                        email, settings.FRONTEND_URL, token,
                    )
        return Response({'message': "Si un compte non vérifié existe pour cet email, un nouveau lien de confirmation vient d'être envoyé."})


class EmailVerifyConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token', '')
        user = verify_email_verify_token(token, User)
        if not user:
            return Response({'error': 'Lien invalide ou expiré.'}, status=400)

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_verified = True
        profile.save(update_fields=['is_verified'])

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
            log_activity(user, 'ACCOUNT_ACTIVATED', description=f"{user.email} (lien email)")

        # Le compte vient d'être activé : on connecte directement l'utilisateur
        # (évite un aller-retour supplémentaire vers l'écran de login).
        refresh = RefreshToken.for_user(user)
        return Response({
            'message': 'Adresse email vérifiée avec succès.',
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
        })


# ── DASHBOARD ─────────────────────────────────────

def _mois_retard(date_prochain_paiement):
    """Nombre de mois entamés de retard depuis la date où le loyer aurait dû
    être payé — un jour de retard compte déjà comme 1 mois entamé."""
    delta = relativedelta(date.today(), date_prochain_paiement)
    mois = delta.years * 12 + delta.months
    if delta.days > 0:
        mois += 1
    return max(mois, 1)


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mes_logements    = Logement.objects.filter(proprietaire=request.user)
        paiements        = Paiement.objects.filter(occupant__logement__in=mes_logements)
        occupants_actifs = Occupant.objects.filter(actif=True, logement__in=mes_logements)
        en_retard        = occupants_actifs.filter(statut='En retard').select_related('compartiment', 'logement')
        compartiments    = Compartiment.objects.filter(logement__in=mes_logements)

        mois, annee = date.today().month, date.today().year

        # Agrégations SQL plutôt que des sum() Python sur des querysets chargés en mémoire.
        # NB: Paiement ne contient QUE des loyers — la caution (Occupant.caution_versee)
        # n'y entre jamais, donc "revenus" et "historique_mensuel" ci-dessous sont déjà
        # naturellement exempts de toute caution, sans traitement particulier à faire.
        revenus_mois       = paiements.filter(date_paiement__month=mois, date_paiement__year=annee).aggregate(t=Sum('montant_verse'))['t'] or 0
        total_revenus      = paiements.aggregate(t=Sum('montant_verse'))['t'] or 0
        total_attendu_mois = occupants_actifs.aggregate(t=Sum('loyer'))['t'] or 0
        caution_totale     = occupants_actifs.aggregate(t=Sum('caution_versee'))['t'] or 0

        depenses_mois = (
            Depense.objects.filter(logement__in=mes_logements, date__month=mois, date__year=annee)
            .aggregate(t=Sum('montant'))['t'] or 0
        )
        revenu_net_mois = float(revenus_mois) - float(depenses_mois)

        # Retardataires : montant réellement dû (loyer × mois de retard cumulés),
        # pas juste le loyer d'un mois — sinon un locataire en retard de 3 mois
        # afficherait le même montant qu'un retard d'1 jour.
        retardataires = []
        montant_retard_total = 0
        for o in en_retard.order_by('date_prochain_paiement'):
            jours_retard = (date.today() - o.date_prochain_paiement).days
            nb_mois      = _mois_retard(o.date_prochain_paiement)
            montant_du   = float(o.loyer) * nb_mois
            montant_retard_total += montant_du
            retardataires.append({
                'id': o.id, 'nom': o.nom_complet, 'telephone': o.telephone,
                'compartiment': o.compartiment.nom if o.compartiment else '—',
                'logement': o.logement.nom if o.logement else '—',
                'depuis': str(o.date_prochain_paiement),
                'jours_retard': jours_retard,
                'mois_retard': nb_mois,
                'loyer': float(o.loyer),
                'montant_du': montant_du,
            })

        # Historique des encaissements sur 6 mois (mois courant inclus), pour le
        # graphique — 6 entrées toujours présentes, même à 0, pas seulement les
        # mois où un paiement existe.
        six_mois_debut = date.today().replace(day=1) - relativedelta(months=5)
        par_mois = (
            paiements.filter(date_paiement__gte=six_mois_debut)
            .annotate(m=TruncMonth('date_paiement'))
            .values('m')
            .annotate(total=Sum('montant_verse'))
        )
        totaux_par_cle = {row['m'].strftime('%Y-%m'): float(row['total']) for row in par_mois}
        historique_mensuel = []
        for i in range(5, -1, -1):
            d = date.today().replace(day=1) - relativedelta(months=i)
            cle = d.strftime('%Y-%m')
            historique_mensuel.append({
                'mois': NOM_MOIS[d.month][:3], 'annee': d.year,
                'total': totaux_par_cle.get(cle, 0.0),
            })

        return Response({
            'logements':    { 'total': mes_logements.count() },
            'compartiments': {
                'total':   compartiments.count(),
                'libres':  compartiments.filter(statut='LIBRE').count(),
                'occupes': compartiments.filter(statut='OCCUPE').count(),
            },
            'occupants': {
                'total':     occupants_actifs.count(),
                'actifs':    occupants_actifs.filter(statut='Actif').count(),
                'en_retard': en_retard.count(),
                'retardataires': retardataires[:20],
            },
            'paiements': {
                'total_revenus':      float(total_revenus),
                'revenus_mois':       float(revenus_mois),
                'total_attendu_mois': float(total_attendu_mois),
                'payes':              paiements.filter(statut='Payé').count(),
                'en_attente':         paiements.filter(statut='En attente').count(),
            },
            'retards': {
                'montant_total': montant_retard_total,
                'nombre':        en_retard.count(),
            },
            'caution_totale': float(caution_totale),
            'depenses': {
                'total_mois': float(depenses_mois),
            },
            'revenu_net_mois': revenu_net_mois,
            'historique_mensuel': historique_mensuel,
        })


# ── LOGEMENTS ─────────────────────────────────────

class LogementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Logement.objects.filter(proprietaire=request.user)
        return Response(LogementSerializer(qs, many=True).data)

    def post(self, request):
        s = LogementSerializer(data=request.data)
        if s.is_valid():
            s.save(proprietaire=request.user)
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class LogementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, logement_id):
        return Response(LogementSerializer(get_logement_or_404(request.user, logement_id)).data)

    def put(self, request, logement_id):
        l = get_logement_or_404(request.user, logement_id)
        s = LogementSerializer(l, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, logement_id):
        get_logement_or_404(request.user, logement_id).delete()
        return Response(status=204)


# ── COMPARTIMENTS ─────────────────────────────────

class CompartimentsByLogementView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = CompartimentSerializer

    def get_queryset(self):
        logement = get_logement_or_404(self.request.user, self.kwargs['logement_id'])
        qs     = Compartiment.objects.filter(logement=logement)
        statut = self.request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut=statut)
        return qs


class CompartimentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, logement_id):
        logement = get_logement_or_404(request.user, logement_id)
        s = CompartimentSerializer(data=request.data)
        if s.is_valid():
            s.save(logement=logement)
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class CompartimentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        return Response(CompartimentSerializer(
            get_compartiment_or_404(request.user, compartiment_id)
        ).data)

    def put(self, request, compartiment_id):
        c = get_compartiment_or_404(request.user, compartiment_id)
        s = CompartimentSerializer(c, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, compartiment_id):
        get_compartiment_or_404(request.user, compartiment_id).delete()
        return Response(status=204)


class HistoriqueCompartimentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, compartiment_id):
        comp = get_compartiment_or_404(request.user, compartiment_id)
        historique = HistoriqueOccupation.objects.filter(compartiment=comp)
        return Response(HistoriqueOccupationSerializer(historique, many=True).data)


# ── OCCUPANTS ─────────────────────────────────────

class OccupantListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Occupant.objects.filter(actif=True, proprietaire=request.user)
        if request.query_params.get('compartiment_id'):
            qs = qs.filter(compartiment_id=request.query_params['compartiment_id'])
        if request.query_params.get('logement_id'):
            qs = qs.filter(logement_id=request.query_params['logement_id'])
        return Response(OccupantSerializer(qs, many=True).data)

    def post(self, request):
        # Vérifie que le compartiment/logement visé appartient bien à l'utilisateur
        # AVANT de créer quoi que ce soit — sinon on pourrait loger un occupant
        # chez un autre propriétaire simplement en devinant un ID.
        compartiment_id = request.data.get('compartiment')
        logement_id     = request.data.get('logement')
        if compartiment_id:
            get_compartiment_or_404(request.user, compartiment_id)
        elif logement_id:
            get_logement_or_404(request.user, logement_id)

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
        return Response(OccupantSerializer(get_occupant_or_404(request.user, occupant_id)).data)

    def put(self, request, occupant_id):
        o = get_occupant_or_404(request.user, occupant_id)
        # Si le locataire est transféré vers un autre compartiment, ce nouveau
        # compartiment doit lui aussi appartenir à l'utilisateur.
        nouveau_comp_id = request.data.get('compartiment')
        if nouveau_comp_id and str(nouveau_comp_id) != str(o.compartiment_id):
            get_compartiment_or_404(request.user, nouveau_comp_id)
        s = OccupantSerializer(o, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, occupant_id):
        get_occupant_or_404(request.user, occupant_id).delete()
        return Response(status=204)


class OccupantLibererView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, occupant_id):
        occupant = get_occupant_or_404(request.user, occupant_id)
        occupant.liberer()
        return Response({'message': f'{occupant.nom_complet} a quitté le logement.'})


@method_decorator(xframe_options_exempt, name='get')
class OccupantContratPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        rl = get_reportlab()
        if not rl:
            return Response({'error': 'reportlab non installé.'}, status=500)
        A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

        occupant = get_occupant_or_404(request.user, occupant_id)
        comp     = occupant.compartiment
        logement = comp.logement if comp else occupant.logement

        proprio_nom      = request.user.get_full_name() or request.user.username
        proprio_email    = request.user.email
        proprio_profile  = Profile.objects.filter(user=request.user).first()
        proprio_tel      = proprio_profile.telephone if proprio_profile else ''
        proprio_adresse  = proprio_profile.adresse if proprio_profile else ''

        jour = occupant.date_debut_contrat.day
        jour_echeance = "1er" if jour == 1 else str(jour)

        loyer_int = fcfa_arrondi(occupant.loyer)
        loyer_txt = f"{loyer_int:,} FCFA".replace(',', ' ')
        loyer_lettres = montant_en_lettres_fcfa(loyer_int)

        caution = occupant.caution_versee or 0
        if caution > 0:
            caution_txt = f"{fcfa_arrondi(caution):,} FCFA ({montant_en_lettres_fcfa(caution)})".replace(',', ' ')
        else:
            caution_txt = "Aucun dépôt de garantie exigé."

        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
        styles = getSampleStyleSheet()
        story  = []

        title_style = ParagraphStyle('title', parent=styles['Title'], fontSize=18, spaceAfter=4, alignment=1)
        meta_style  = ParagraphStyle('meta', parent=styles['Normal'], fontSize=10, alignment=1, textColor=colors.grey, spaceAfter=4)
        h2_style    = ParagraphStyle('h2', parent=styles['Heading2'], fontSize=13, spaceAfter=6, spaceBefore=10, textColor=colors.HexColor('#1E293B'))
        body_style  = ParagraphStyle('body', parent=styles['Normal'], fontSize=10.5, leading=15, spaceAfter=5)
        clause_style = ParagraphStyle('clause', parent=body_style, leftIndent=10, spaceAfter=7)

        # ── En-tête ──
        story.append(Paragraph("CONTRAT DE BAIL D'HABITATION", title_style))
        story.append(Paragraph(
            f"Référence : {occupant.numero_contrat} &nbsp;·&nbsp; Date de signature : {date.today().strftime('%d/%m/%Y')}",
            meta_style
        ))
        story.append(Spacer(1, 0.4*cm))

        # ── Parties ──
        # NB: Paragraph n'interprète jamais un "\n" littéral comme un saut de
        # ligne (contrairement à <br/>) — d'où l'usage de <br/> explicite ici,
        # nécessaire pour un rendu correct en plusieurs lignes dans la cellule.
        story.append(Paragraph("ENTRE LES SOUSSIGNÉS", h2_style))
        proprio_lignes = [proprio_nom]
        if proprio_tel:
            proprio_lignes.append(f"Téléphone : {proprio_tel}")
        if proprio_email:
            proprio_lignes.append(f"Courriel : {proprio_email}")
        if proprio_adresse:
            proprio_lignes.append(f"Adresse : {proprio_adresse}")
        proprio_lignes.append(f"Représentant : {logement.nom if logement else '—'}")

        cell_style = ParagraphStyle('partieCell', parent=body_style, fontSize=10, leading=14, textColor=colors.HexColor('#0F172A'), spaceAfter=0)
        data = [
            ['LE LOCATEUR (Bailleur)', 'LE LOCATAIRE'],
            [
                Paragraph("<br/>".join(proprio_lignes), cell_style),
                Paragraph(
                    f"{occupant.nom_complet}<br/>"
                    f"Téléphone : {occupant.telephone}<br/>"
                    f"Courriel : {occupant.email or '—'}<br/>"
                    f"CNI : {occupant.cni}",
                    cell_style
                ),
            ]
        ]
        t = Table(data, colWidths=[8*cm, 8*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN',      (0,0), (-1,-1), 'LEFT'),
            ('VALIGN',     (0,0), (-1,-1), 'TOP'),
            ('PADDING',    (0,0), (-1,-1), 8),
            ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ]))
        story.append(t)
        story.append(Paragraph("Il a été convenu et arrêté ce qui suit :", body_style))
        story.append(Spacer(1, 0.3*cm))

        # ── Désignation du logement ──
        story.append(Paragraph("ARTICLE 1 — DÉSIGNATION DU LOGEMENT", h2_style))
        if logement:
            story.append(Paragraph(f"<b>Adresse :</b> {logement.nom} — {logement.localisation}", body_style))
        if comp:
            story.append(Paragraph(f"<b>Compartiment loué :</b> {comp.nom} ({comp.get_type_display()})", body_style))
            story.append(Paragraph(
                f"<b>Composition :</b> {comp.chambres} chambre(s), {comp.salons} salon(s), "
                f"{comp.douches} douche(s), {comp.cuisines} cuisine(s)", body_style
            ))
        story.append(Paragraph(
            "L'état des lieux et les équipements inclus font l'objet d'un document distinct "
            "établi contradictoirement à l'entrée du locataire.", body_style
        ))

        # ── Conditions financières ──
        story.append(Paragraph("ARTICLE 2 — CONDITIONS FINANCIÈRES", h2_style))
        story.append(Paragraph(f"<b>Loyer mensuel :</b> {loyer_txt} ({loyer_lettres})", body_style))
        story.append(Paragraph(f"<b>Date d'échéance exacte :</b> le {jour_echeance} de chaque mois, payable d'avance", body_style))
        story.append(Paragraph("<b>Modes de paiement acceptés :</b> Espèces, Orange Money, MTN MoMo, Virement bancaire", body_style))

        # Dépôt de garantie mis en évidence dans un encadré plutôt qu'une simple
        # ligne — c'est le point que les locataires relisent le plus souvent.
        caution_box_style = ParagraphStyle(
            'cautionBox', parent=body_style, backColor=colors.HexColor('#F1F5F9'),
            borderPadding=8, spaceBefore=4, spaceAfter=8,
        )
        story.append(Paragraph(
            f"<b>Dépôt de garantie (caution) :</b> {caution_txt} "
            "Ce dépôt sera restitué au locataire à son départ, dans un délai raisonnable après "
            "l'état des lieux de sortie, déduction faite des réparations locatives éventuellement "
            "nécessaires (voir Article 4.6).",
            caution_box_style
        ))

        # ── Durée du bail ──
        story.append(Paragraph("ARTICLE 3 — DURÉE DU BAIL", h2_style))
        story.append(Paragraph(
            f"<b>Date d'entrée en jouissance :</b> {occupant.date_debut_contrat.strftime('%d/%m/%Y')}", body_style
        ))
        story.append(Paragraph(
            "Le présent bail est conclu pour une durée indéterminée. Il pourra être résilié à tout moment "
            "par l'une ou l'autre des parties moyennant un préavis écrit d'un (1) mois. Le renouvellement "
            "est tacite en l'absence de préavis.", body_style
        ))

        # ── Clauses ──
        story.append(Paragraph("ARTICLE 4 — CLAUSES ET OBLIGATIONS", h2_style))
        for i, clause in enumerate([
            "Le locataire s'engage à user paisiblement des lieux loués et à les maintenir en bon état d'entretien "
            "et de réparations locatives pendant toute la durée du bail.",
            "Le locataire ne peut ni céder son bail, ni sous-louer tout ou partie du logement sans l'accord écrit "
            "préalable du locateur.",
            "Les animaux domestiques sont admis sous réserve qu'ils ne causent aucune nuisance ni dégradation ; "
            "le locateur se réserve le droit d'exiger leur retrait en cas de trouble avéré.",
            "Le locataire s'engage à respecter le règlement intérieur de l'immeuble ainsi que la tranquillité "
            "du voisinage.",
            "Tout retard de paiement supérieur à quinze (15) jours après la date d'échéance pourra entraîner "
            "une mise en demeure, préalable à toute action en résiliation.",
            "À la sortie des lieux, un état des lieux de sortie sera dressé contradictoirement ; le dépôt de "
            "garantie sera restitué dans un délai raisonnable, déduction faite des réparations locatives "
            "éventuellement nécessaires.",
        ], start=1):
            story.append(Paragraph(f"{i}. {clause}", clause_style))

        # Grand espace pour rapprocher les signatures du bas de la page — un
        # ancrage strict au bas de page varierait trop selon la longueur des
        # clauses avec la mise en page en flux de reportlab.
        story.append(Spacer(1, 2.2*cm))

        # ── Signatures ──
        # NB: un "\n" littéral dans une cellule de Table n'est pas fiable pour
        # créer de l'espace — on utilise une vraie ligne de tableau vide avec
        # une hauteur définie à la place (voir aussi _build_recu_pdf).
        story.append(Paragraph("SIGNATURES", h2_style))
        story.append(Paragraph("Les parties reconnaissent avoir lu et pris connaissance de l'intégralité du présent contrat.", body_style))
        story.append(Spacer(1, 0.3*cm))
        sig_table = Table([
            ['Le Locateur', 'Le Locataire'],
            ['Lu et approuvé', 'Lu et approuvé'],
            ['', ''],
            ['_________________', '_________________'],
            [f"Fait le {date.today().strftime('%d/%m/%Y')}", f"Fait le {date.today().strftime('%d/%m/%Y')}"],
        ], colWidths=[8*cm, 8*cm], rowHeights=[None, None, 1.2*cm, None, None])
        sig_table.setStyle(TableStyle([
            ('FONTNAME',  (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',  (0,1), (-1,1), 9),
            ('TEXTCOLOR', (0,1), (-1,1), colors.grey),
            ('VALIGN',    (0,2), (-1,2), 'BOTTOM'),
            ('ALIGN',     (0,0), (-1,-1), 'CENTER'),
            ('PADDING',   (0,0), (-1,-1), 6),
        ]))
        story.append(sig_table)

        doc.build(story)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="contrat_{occupant.numero_contrat}.pdf"'
        return response


# ── REÇU DE PAIEMENT PDF ──────────────────────────

def _build_recu_pdf(paiement):
    """Construit le PDF du reçu et retourne un buffer BytesIO prêt à être servi.
    Partagé entre la vue authentifiée et la vue publique (lien signé)."""
    rl = get_reportlab()
    if not rl:
        return None
    A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

    occupant  = paiement.occupant
    comp      = occupant.compartiment
    immeuble  = comp.logement.nom if comp else (occupant.logement.nom if occupant.logement else '—')
    bailleur  = occupant.proprietaire
    bailleur_nom = (bailleur.get_full_name() or bailleur.username) if bailleur else 'Gimmopro'
    bailleur_email = bailleur.email if bailleur else ''

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
    styles = getSampleStyleSheet()
    story  = []

    title_style  = ParagraphStyle('title',  parent=styles['Title'],   fontSize=20, spaceAfter=6,  alignment=1)
    center_style = ParagraphStyle('center', parent=styles['Normal'],  fontSize=11, spaceAfter=4,  alignment=1)
    h2_style     = ParagraphStyle('h2',     parent=styles['Heading2'],fontSize=13, spaceAfter=6)
    body_style   = ParagraphStyle('body',   parent=styles['Normal'],  fontSize=11, leading=16, spaceAfter=4)
    # NB: Paragraph n'interprète JAMAIS un "\n" littéral comme un saut de ligne
    # (son mini-langage type XML l'ignore, contrairement à <br/>) — c'était la
    # cause des chevauchements/sauts de ligne manquants sur la signature.
    cell_style   = ParagraphStyle('cell', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.white)

    story.append(Paragraph("REÇU DE PAIEMENT — QUITTANCE DE LOYER", title_style))
    story.append(Paragraph(f"N° REÇU-{paiement.id:04d}", center_style))
    debut_txt = f"{NOM_MOIS[paiement.date_debut_periode.month]} {paiement.date_debut_periode.year}"
    fin_txt   = f"{NOM_MOIS[paiement.date_fin_periode.month]} {paiement.date_fin_periode.year}"
    periode_txt = debut_txt if debut_txt == fin_txt else f"{debut_txt} à {fin_txt}"
    story.append(Paragraph(f"Période payée : loyer de {periode_txt}", center_style))
    story.append(Spacer(1, 0.4*cm))

    # Montant + tampon "PAYÉ"
    # NB: `leading` (hauteur de ligne) doit être défini explicitement en fonction
    # de `fontSize` — hériter d'un style pensé pour du texte 10pt (leading=14)
    # sur une police 26pt clippe le texte, faute de place verticale suffisante.
    montant_lettres = montant_en_lettres_fcfa(paiement.montant_verse)
    montant_style = ParagraphStyle('m', parent=cell_style, fontSize=26, leading=32, alignment=1, fontName='Helvetica-Bold')
    payé_style    = ParagraphStyle('s', parent=cell_style, fontSize=13, leading=17, alignment=1, fontName='Helvetica-Bold', textColor=colors.HexColor('#16A34A'), backColor=colors.white)
    montant_data = [[
        Paragraph(f"{fcfa_arrondi(paiement.montant_verse):,} FCFA".replace(',', ' '), montant_style),
        Paragraph("✓ PAYÉ", payé_style),
    ]]
    montant_table = Table(montant_data, colWidths=[12*cm, 4*cm], rowHeights=[1.6*cm])
    montant_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (0,-1), colors.HexColor('#4F46E5')),
        ('BACKGROUND',  (1,0), (1,-1), colors.HexColor('#4F46E5')),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('PADDING',     (0,0), (-1,-1), 10),
    ]))
    story.append(montant_table)
    story.append(Paragraph(f"<i>({montant_lettres})</i>", ParagraphStyle('lettres', parent=body_style, fontSize=9, alignment=1, textColor=colors.grey, spaceBefore=4)))
    story.append(Spacer(1, 0.5*cm))

    # Deux blocs : Bailleur / Locataire
    parties_data = [
        ['BAILLEUR', 'LOCATAIRE'],
        [
            Paragraph(f"{bailleur_nom}" + (f"<br/>{bailleur_email}" if bailleur_email else ''), cell_style),
            Paragraph(f"{occupant.nom_complet}<br/>{occupant.telephone}" + (f"<br/>{comp.nom}" if comp else ''), cell_style),
        ],
    ]
    parties_table = Table(parties_data, colWidths=[8*cm, 8*cm])
    parties_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.HexColor('#F8FAFC')),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#334155')),
        ('VALIGN',     (0,0), (-1,-1), 'TOP'),
        ('PADDING',    (0,0), (-1,-1), 10),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(parties_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("DÉTAILS DU PAIEMENT", h2_style))
    details = [
        ['Description', 'Valeur'],
        ['Loyer mensuel',       f"{fcfa_arrondi(occupant.loyer):,} FCFA".replace(',', ' ')],
        ['Nombre de mois',      str(paiement.nombre_mois)],
        ['Période couverte',    f"Du {paiement.date_debut_periode.strftime('%d/%m/%Y')} au {paiement.date_fin_periode.strftime('%d/%m/%Y')}"],
        ['Mode de paiement',    paiement.get_mode_paiement_display()],
        ['Montant total versé', f"{fcfa_arrondi(paiement.montant_verse):,} FCFA".replace(',', ' ')],
        ['Solde restant dû',    "0 FCFA — payé intégralement"],
        ['Prochain paiement',   f"À partir du {(paiement.date_fin_periode).strftime('%d/%m/%Y')}"],
        ['Statut',              paiement.statut],
    ]
    if paiement.note:
        details.append(['Note', paiement.note])

    t = Table(details, colWidths=[8*cm, 8*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#0F172A')),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.HexColor('#F8FAFC')),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 10),
        ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING',       (0,0), (-1,-1), 8),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTNAME',      (0,1), (0,-1),  'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 1.5*cm))

    # Signature — une vraie table plutôt que des "\n" dans une chaîne brute,
    # pour un espacement fiable au lieu de dépendre du rendu de Paragraph.
    story.append(Paragraph("Signature et cachet du gestionnaire", h2_style))
    sig_table = Table(
        [[''], ['_________________']],
        colWidths=[8*cm], rowHeights=[1.4*cm, 0.6*cm],
    )
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Émis le {date.today().strftime('%d/%m/%Y')} — document généré électroniquement par Gimmopro", center_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_recu_caution_pdf(occupant):
    """Construit le PDF du reçu de dépôt de garantie (caution) et retourne un
    buffer BytesIO prêt à être servi. Même charte graphique que _build_recu_pdf
    (reçu de loyer) pour une cohérence visuelle entre les deux documents.
    L'appelant doit avoir déjà vérifié caution_versee > 0 et
    date_versement_caution non nul avant d'appeler cette fonction."""
    rl = get_reportlab()
    if not rl:
        return None
    A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

    comp     = occupant.compartiment
    immeuble = comp.logement.nom if comp else (occupant.logement.nom if occupant.logement else '—')
    bailleur = occupant.proprietaire
    bailleur_nom = (bailleur.get_full_name() or bailleur.username) if bailleur else 'Gimmopro'
    bailleur_email = bailleur.email if bailleur else ''

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
    styles = getSampleStyleSheet()
    story  = []

    title_style  = ParagraphStyle('title',  parent=styles['Title'],   fontSize=20, spaceAfter=6,  alignment=1)
    center_style = ParagraphStyle('center', parent=styles['Normal'],  fontSize=11, spaceAfter=4,  alignment=1)
    h2_style     = ParagraphStyle('h2',     parent=styles['Heading2'],fontSize=13, spaceAfter=6)
    body_style   = ParagraphStyle('body',   parent=styles['Normal'],  fontSize=11, leading=16, spaceAfter=4)
    cell_style   = ParagraphStyle('cell', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.white)

    story.append(Paragraph("REÇU DE DÉPÔT DE GARANTIE (CAUTION)", title_style))
    story.append(Paragraph(f"Locataire : {occupant.nom_complet}", center_style))
    story.append(Spacer(1, 0.4*cm))

    montant_lettres = montant_en_lettres_fcfa(occupant.caution_versee)
    montant_style = ParagraphStyle('m', parent=cell_style, fontSize=26, leading=32, alignment=1, fontName='Helvetica-Bold')
    payé_style    = ParagraphStyle('s', parent=cell_style, fontSize=13, leading=17, alignment=1, fontName='Helvetica-Bold', textColor=colors.HexColor('#16A34A'), backColor=colors.white)
    montant_data = [[
        Paragraph(f"{fcfa_arrondi(occupant.caution_versee):,} FCFA".replace(',', ' '), montant_style),
        Paragraph("✓ VERSÉ", payé_style),
    ]]
    montant_table = Table(montant_data, colWidths=[12*cm, 4*cm], rowHeights=[1.6*cm])
    montant_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (0,-1), colors.HexColor('#4F46E5')),
        ('BACKGROUND',  (1,0), (1,-1), colors.HexColor('#4F46E5')),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('PADDING',     (0,0), (-1,-1), 10),
    ]))
    story.append(montant_table)
    story.append(Paragraph(f"<i>({montant_lettres})</i>", ParagraphStyle('lettres', parent=body_style, fontSize=9, alignment=1, textColor=colors.grey, spaceBefore=4)))
    story.append(Spacer(1, 0.5*cm))

    parties_data = [
        ['BAILLEUR', 'LOCATAIRE'],
        [
            Paragraph(f"{bailleur_nom}" + (f"<br/>{bailleur_email}" if bailleur_email else ''), cell_style),
            Paragraph(f"{occupant.nom_complet}<br/>{occupant.telephone}" + (f"<br/>{comp.nom}" if comp else ''), cell_style),
        ],
    ]
    parties_table = Table(parties_data, colWidths=[8*cm, 8*cm])
    parties_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.HexColor('#F8FAFC')),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#334155')),
        ('VALIGN',     (0,0), (-1,-1), 'TOP'),
        ('PADDING',    (0,0), (-1,-1), 10),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(parties_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("DÉTAILS DU DÉPÔT DE GARANTIE", h2_style))
    details = [
        ['Description', 'Valeur'],
        ['Logement',            immeuble],
        ['Compartiment',        comp.nom if comp else '—'],
        ['Date de versement',   occupant.date_versement_caution.strftime('%d/%m/%Y')],
        ['Montant versé',       f"{fcfa_arrondi(occupant.caution_versee):,} FCFA".replace(',', ' ')],
    ]
    t = Table(details, colWidths=[8*cm, 8*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#0F172A')),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.HexColor('#F8FAFC')),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 10),
        ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING',       (0,0), (-1,-1), 8),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTNAME',      (0,1), (0,-1),  'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "Ce dépôt sera restitué au locataire à son départ, dans un délai raisonnable après "
        "l'état des lieux de sortie, déduction faite des réparations locatives éventuellement "
        "nécessaires.", body_style
    ))
    story.append(Spacer(1, 1.5*cm))

    story.append(Paragraph("Signature et cachet du gestionnaire", h2_style))
    sig_table = Table(
        [[''], ['_________________']],
        colWidths=[8*cm], rowHeights=[1.4*cm, 0.6*cm],
    )
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Émis le {date.today().strftime('%d/%m/%Y')} — document généré électroniquement par Gimmopro", center_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_recu_og_image(paiement):
    """Image de prévisualisation (Open Graph) pour le lien de reçu partagé par
    WhatsApp/SMS — sans ça, le lien s'affiche comme du texte brut dans la
    discussion plutôt qu'une carte avec miniature. Réutilise Vera.ttf, une
    police livrée avec reportlab (déjà une dépendance) pour avoir un rendu
    correct des accents français — la police par défaut de Pillow ne les a pas."""
    from PIL import Image, ImageDraw, ImageFont
    import reportlab as _rl

    font_dir = os.path.join(os.path.dirname(_rl.__file__), 'fonts')
    f_regular = ImageFont.truetype(os.path.join(font_dir, 'Vera.ttf'), 30)
    f_bold_lg = ImageFont.truetype(os.path.join(font_dir, 'VeraBd.ttf'), 84)
    f_bold_sm = ImageFont.truetype(os.path.join(font_dir, 'VeraBd.ttf'), 28)
    f_footer  = ImageFont.truetype(os.path.join(font_dir, 'VeraBd.ttf'), 26)

    occupant = paiement.occupant
    immeuble = occupant.compartiment.logement.nom if occupant.compartiment else (occupant.logement.nom if occupant.logement else '')
    montant_txt = f"{fcfa_arrondi(paiement.montant_verse):,} FCFA".replace(',', ' ')
    debut_txt = f"Loyer de {NOM_MOIS[paiement.date_debut_periode.month]} {paiement.date_debut_periode.year}"

    img = Image.new('RGB', (1200, 630), '#0F172A')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1200, 10], fill='#4F46E5')
    draw.text((80, 70), "REÇU DE PAIEMENT", font=f_regular, fill='#94A3B8')
    draw.rounded_rectangle([80, 130, 250, 185], radius=24, fill='#16A34A')
    draw.text((113, 145), "PAYÉ", font=f_bold_sm, fill='white')
    draw.text((80, 220), montant_txt, font=f_bold_lg, fill='white')
    draw.text((80, 350), debut_txt, font=f_regular, fill='#CBD5E1')
    if immeuble:
        draw.text((80, 390), immeuble, font=f_regular, fill='#CBD5E1')
    draw.text((80, 630 - 90), "Gimmopro", font=f_footer, fill='#818CF8')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@method_decorator(xframe_options_exempt, name='get')
class RecuPaiementPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        paiement = get_paiement_or_404(request.user, paiement_id)
        buffer = _build_recu_pdf(paiement)
        if buffer is None:
            return Response({'error': 'reportlab non installé.'}, status=500)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="recu_paiement_{paiement.id:04d}.pdf"'
        return response


@method_decorator(xframe_options_exempt, name='get')
class RecuPaiementPublicPDFView(APIView):
    """Téléchargement du PDF brut — accès sans authentification, protégé par un
    token signé à durée de vie limitée (voir app.utils.make_recu_token). Séparée
    de RecuPublicLandingView : un lien WhatsApp/SMS doit pointer vers une page
    HTML (pour l'aperçu Open Graph), pas directement vers un PDF."""
    permission_classes = [AllowAny]

    def get(self, request, paiement_id, token):
        if not verify_recu_token(paiement_id, token):
            return Response({'error': 'Lien invalide ou expiré.'}, status=403)
        paiement = get_object_or_404(Paiement, id=paiement_id)
        buffer = _build_recu_pdf(paiement)
        if buffer is None:
            return Response({'error': 'reportlab non installé.'}, status=500)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="recu_paiement_{paiement.id:04d}.pdf"'
        return response


class RecuPublicLandingView(APIView):
    """Page HTML d'atterrissage du reçu — c'est CETTE url qu'on met dans le
    message WhatsApp/SMS, jamais l'URL du PDF directement. Un lien PDF brut
    n'a pas de balises Open Graph, donc WhatsApp l'affiche comme du texte nu
    sans aperçu ; une page HTML avec og:image donne la belle carte de
    prévisualisation avec miniature."""
    permission_classes = [AllowAny]

    def get(self, request, paiement_id, token):
        if not verify_recu_token(paiement_id, token):
            return HttpResponse('Lien invalide ou expiré.', status=403, content_type='text/plain; charset=utf-8')
        paiement = get_object_or_404(Paiement, id=paiement_id)
        occupant = paiement.occupant
        comp     = occupant.compartiment
        immeuble = comp.logement.nom if comp else (occupant.logement.nom if occupant.logement else '—')
        bailleur = occupant.proprietaire
        bailleur_nom = (bailleur.get_full_name() or bailleur.username) if bailleur else 'Gimmopro'

        debut_txt = f"{NOM_MOIS[paiement.date_debut_periode.month]} {paiement.date_debut_periode.year}"
        fin_txt   = f"{NOM_MOIS[paiement.date_fin_periode.month]} {paiement.date_fin_periode.year}"
        periode_txt = debut_txt if debut_txt == fin_txt else f"{debut_txt} à {fin_txt}"

        base_url = request.build_absolute_uri(
            f'/api/paiements/{paiement_id}/recu/public/{token}/'
        )
        return render(request, 'app/recu_public.html', {
            'montant_txt':      f"{fcfa_arrondi(paiement.montant_verse):,} FCFA".replace(',', ' '),
            'periode_txt':      periode_txt,
            'occupant_nom':     occupant.nom_complet,
            'immeuble':         immeuble,
            'compartiment_nom': comp.nom if comp else '',
            'mode_paiement':    paiement.get_mode_paiement_display(),
            'bailleur_nom':     bailleur_nom,
            'download_url':     f"{base_url}telecharger/",
            'image_url':        f"{base_url}image.png",
            'page_url':         base_url,
        })


class RecuPublicImageView(APIView):
    """Image PNG 1200×630 (format Open Graph standard) utilisée comme miniature
    de la carte de prévisualisation WhatsApp — voir RecuPublicLandingView."""
    permission_classes = [AllowAny]

    def get(self, request, paiement_id, token):
        if not verify_recu_token(paiement_id, token):
            return HttpResponse(status=403)
        paiement = get_object_or_404(Paiement, id=paiement_id)
        buffer = _build_recu_og_image(paiement)
        response = HttpResponse(buffer, content_type='image/png')
        response['Cache-Control'] = 'public, max-age=86400'
        return response


# ── REÇU DE CAUTION (DÉPÔT DE GARANTIE) ───────────

def _caution_recu_erreur(occupant):
    """Renvoie le message d'erreur si un reçu ne peut pas être généré pour cet
    occupant, ou None si tout est en ordre. Émettre un reçu pour une caution
    jamais réellement enregistrée comme versée serait trompeur pour un vrai
    locataire — d'où ce garde-fou avant toute génération de PDF ou envoi."""
    if not occupant.caution_versee or occupant.caution_versee <= 0:
        return "Aucun montant de caution enregistré pour ce locataire."
    if not occupant.date_versement_caution:
        return "La date de versement de la caution n'est pas renseignée."
    return None


@method_decorator(xframe_options_exempt, name='get')
class OccupantCautionRecuPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, occupant_id):
        occupant = get_occupant_or_404(request.user, occupant_id)
        erreur = _caution_recu_erreur(occupant)
        if erreur:
            return Response({'error': erreur}, status=400)
        buffer = _build_recu_caution_pdf(occupant)
        if buffer is None:
            return Response({'error': 'reportlab non installé.'}, status=500)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="recu_caution_{occupant.id:04d}.pdf"'
        return response


class OccupantCautionRecuEnvoyerView(APIView):
    """Envoi manuel du reçu de caution par email — jamais automatique (voir
    envoyer_email_caution_recu). Contrairement à l'inscription, c'est une
    action déclenchée et observée directement par l'utilisateur : un échec
    d'envoi doit remonter clairement au frontend plutôt qu'être seulement
    loggé en silence."""
    permission_classes = [IsAuthenticated]

    def post(self, request, occupant_id):
        occupant = get_occupant_or_404(request.user, occupant_id)
        erreur = _caution_recu_erreur(occupant)
        if erreur:
            return Response({'error': erreur}, status=400)
        if not occupant.email:
            return Response({'error': "Aucune adresse email enregistrée pour ce locataire."}, status=400)

        buffer = _build_recu_caution_pdf(occupant)
        if buffer is None:
            return Response({'error': 'reportlab non installé.'}, status=500)

        try:
            envoyer_email_caution_recu(occupant, buffer)
        except Exception as e:
            logger.error("Échec de l'envoi du reçu de caution à %s : %s", occupant.email, e, exc_info=True)
            return Response({'error': "L'envoi de l'email a échoué. Réessayez dans quelques instants."}, status=502)

        return Response({'message': f"Reçu envoyé à {occupant.email}."})


# ── RAPPORT MENSUEL PDF ───────────────────────────

@method_decorator(xframe_options_exempt, name='get')
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

        nom_mois = NOM_MOIS[mois]
        mes_logements = Logement.objects.filter(proprietaire=request.user)

        paiements_mois = Paiement.objects.filter(
            occupant__logement__in=mes_logements,
            date_paiement__month=mois, date_paiement__year=annee
        ).select_related('occupant', 'occupant__compartiment', 'occupant__logement')

        occupants_actifs = Occupant.objects.filter(
            actif=True, logement__in=mes_logements
        ).select_related('compartiment', 'logement')
        total_attendu    = sum(o.loyer for o in occupants_actifs)
        total_encaisse   = sum(p.montant_verse for p in paiements_mois)
        occupants_payes  = set(p.occupant_id for p in paiements_mois)
        occupants_retard = [o for o in occupants_actifs if o.id not in occupants_payes]

        depenses_mois = Depense.objects.filter(
            logement__in=mes_logements, date__month=mois, date__year=annee
        ).select_related('logement').order_by('-date')
        total_depenses = sum(d.montant for d in depenses_mois)
        revenu_net     = total_encaisse - total_depenses

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
            ['Total attendu ce mois',   f"{fcfa_arrondi(total_attendu):,} FCFA".replace(',', ' ')],
            ['Total loyers encaissés (Entrées)', f"{fcfa_arrondi(total_encaisse):,} FCFA".replace(',', ' ')],
            ['Total dépenses (Sorties)',         f"− {fcfa_arrondi(total_depenses):,} FCFA".replace(',', ' ')],
            ['REVENU NET DU MOIS',               f"{fcfa_arrondi(revenu_net):,} FCFA".replace(',', ' ')],
            ['Reste à encaisser',       f"{fcfa_arrondi(total_attendu - total_encaisse):,} FCFA".replace(',', ' ')],
            ['Taux de recouvrement',    f"{int((total_encaisse/total_attendu*100) if total_attendu > 0 else 0)} %"],
            ['Nombre de paiements',     str(paiements_mois.count())],
            ['Locataires en retard',    str(len(occupants_retard))],
        ]
        t_resume = Table(resume, colWidths=[9*cm, 7*cm])
        t_resume.setStyle(TableStyle([
            ('SPAN',         (0,0), (-1,0)),
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#4F46E5')),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 11),
            ('ALIGN',        (1,1), (1,-1),  'RIGHT'),
            ('FONTNAME',     (0,1), (0,-1),  'Helvetica-Bold'),
            # Ligne "Revenu net" mise en évidence — c'est LE chiffre qui compte le plus.
            ('BACKGROUND',   (0,4), (-1,4),  colors.HexColor('#DCFCE7')),
            ('TEXTCOLOR',    (0,4), (-1,4),  colors.HexColor('#16A34A')),
            ('FONTSIZE',     (0,4), (-1,4),  13),
            ('PADDING',      (0,0), (-1,-1), 8),
            ('GRID',         (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#F5F5F5')]),
        ]))
        story.append(t_resume)

        # Entrées — paiements reçus
        if paiements_mois.exists():
            story.append(Paragraph("ENTRÉES — LOYERS PERÇUS", h2_style))
            rows = [['Locataire', 'Compartiment', 'Période', 'Montant', 'Date']]
            for p in paiements_mois:
                rows.append([
                    p.occupant.nom_complet,
                    p.occupant.compartiment.nom if p.occupant.compartiment else '—',
                    f"{p.date_debut_periode.strftime('%d/%m')} → {p.date_fin_periode.strftime('%d/%m/%Y')}",
                    f"{fcfa_arrondi(p.montant_verse):,}".replace(',', ' '),
                    p.date_paiement.strftime('%d/%m/%Y'),
                ])
            t_pay = Table(rows, colWidths=[4.5*cm, 3.5*cm, 4*cm, 3*cm, 2.5*cm])
            t_pay.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#0F172A')),
                ('TEXTCOLOR',     (0,0), (-1,0),  colors.HexColor('#F8FAFC')),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
                ('PADDING',       (0,0), (-1,-1), 6),
                ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),  [colors.white, colors.HexColor('#F5F5F5')]),
            ]))
            story.append(t_pay)

        # Sorties — dépenses / charges
        if depenses_mois.exists():
            story.append(Paragraph("SORTIES — DÉPENSES & CHARGES", h2_style))
            rows_d = [['Logement', 'Libellé', 'Catégorie', 'Montant', 'Date']]
            for d in depenses_mois:
                rows_d.append([
                    d.logement.nom, d.libelle, d.get_categorie_display(),
                    f"{fcfa_arrondi(d.montant):,}".replace(',', ' '),
                    d.date.strftime('%d/%m/%Y'),
                ])
            t_dep = Table(rows_d, colWidths=[3.5*cm, 4.5*cm, 3*cm, 2.5*cm, 2.5*cm])
            t_dep.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#7C2D12')),
                ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
                ('PADDING',       (0,0), (-1,-1), 6),
                ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),  [colors.white, colors.HexColor('#FFF7ED')]),
            ]))
            story.append(t_dep)

        # Retards
        if occupants_retard:
            story.append(Paragraph("LOCATAIRES EN RETARD", h2_style))
            rows_r = [['Locataire', 'Téléphone', 'Compartiment', 'Loyer mensuel']]
            for o in occupants_retard:
                rows_r.append([
                    o.nom_complet, o.telephone,
                    o.compartiment.nom if o.compartiment else '—',
                    f"{fcfa_arrondi(o.loyer):,} FCFA".replace(',', ' '),
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


# ── EXPORTS COMPTABLES (Excel / CSV) ──────────────

def _reponse_export(headers, rows, nom_fichier, fmt):
    """Construit la réponse HTTP d'export -- CSV (point-virgule, séparateur
    attendu par Excel en locale française ; BOM utf-8-sig pour que les
    caractères accentués s'affichent correctement à l'ouverture, plutôt que
    des caractères corrompus) ou XLSX (openpyxl). `rows` : liste de listes
    de valeurs déjà prêtes à écrire telles quelles (str/int/float/date) --
    jamais de Decimal brut, openpyxl ne le convertit pas de façon fiable
    en cellule numérique."""
    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{nom_fichier}.csv"'
        writer = csv.writer(response, delimiter=';')
        writer.writerow(headers)
        writer.writerows(rows)
        return response

    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    for col in ws.columns:
        largeur = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(largeur + 2, 40)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nom_fichier}.xlsx"'
    return response


class ExportPaiementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fmt = request.query_params.get('export_format', 'xlsx')
        qs = Paiement.objects.filter(occupant__proprietaire=request.user).select_related(
            'occupant', 'occupant__compartiment', 'occupant__logement', 'occupant__compartiment__logement'
        )
        annee    = request.query_params.get('annee')
        mois     = request.query_params.get('mois')
        logement = request.query_params.get('logement')
        if annee:
            qs = qs.filter(date_paiement__year=int(annee))
        if mois:
            qs = qs.filter(date_paiement__month=int(mois))
        if logement:
            get_logement_or_404(request.user, logement)  # 404 si ce logement n'appartient pas à l'utilisateur
            qs = qs.filter(occupant__logement_id=logement)
        qs = qs.order_by('date_paiement')

        headers = [
            'Date paiement', 'Locataire', 'Logement', 'Compartiment',
            'Mode de paiement', 'Nombre de mois', 'Début période', 'Fin période',
            'Montant versé (FCFA)', 'Statut', 'Note',
        ]
        rows = []
        for p in qs:
            comp = p.occupant.compartiment
            logement_nom = comp.logement.nom if comp else (p.occupant.logement.nom if p.occupant.logement else '—')
            rows.append([
                p.date_paiement.strftime('%d/%m/%Y'),
                p.occupant.nom_complet,
                logement_nom,
                comp.nom if comp else '—',
                p.get_mode_paiement_display(),
                p.nombre_mois,
                p.date_debut_periode.strftime('%d/%m/%Y'),
                p.date_fin_periode.strftime('%d/%m/%Y'),
                float(p.montant_verse),
                p.statut,
                p.note,
            ])

        suffixe = f"_{annee}" if annee else ''
        return _reponse_export(headers, rows, f"paiements{suffixe}", fmt)


class ExportDepensesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fmt = request.query_params.get('export_format', 'xlsx')
        qs = Depense.objects.filter(logement__proprietaire=request.user).select_related('logement')
        annee    = request.query_params.get('annee')
        mois     = request.query_params.get('mois')
        logement = request.query_params.get('logement')
        if annee:
            qs = qs.filter(date__year=int(annee))
        if mois:
            qs = qs.filter(date__month=int(mois))
        if logement:
            get_logement_or_404(request.user, logement)
            qs = qs.filter(logement_id=logement)
        qs = qs.order_by('date')

        headers = ['Date', 'Logement', 'Libellé', 'Catégorie', 'Montant (FCFA)', 'Note']
        rows = [
            [
                d.date.strftime('%d/%m/%Y'), d.logement.nom, d.libelle,
                d.get_categorie_display(), float(d.montant), d.note,
            ]
            for d in qs
        ]

        suffixe = f"_{annee}" if annee else ''
        return _reponse_export(headers, rows, f"depenses{suffixe}", fmt)


class ExportRecapitulatifAnnuelView(APIView):
    """Un total par mois (loyers encaissés, dépenses, revenu net) sur toute
    l'année -- vue d'ensemble comptable/fiscale, distincte du rapport
    mensuel PDF qui détaille un seul mois à la fois."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fmt   = request.query_params.get('export_format', 'xlsx')
        annee = int(request.query_params.get('annee', date.today().year))
        mes_logements = Logement.objects.filter(proprietaire=request.user)

        headers = ['Mois', 'Loyers encaissés (FCFA)', 'Dépenses (FCFA)', 'Revenu net (FCFA)']
        rows = []
        total_encaisse = Decimal('0')
        total_depenses = Decimal('0')
        for m in range(1, 13):
            encaisse = Paiement.objects.filter(
                occupant__logement__in=mes_logements, date_paiement__year=annee, date_paiement__month=m
            ).aggregate(t=Sum('montant_verse'))['t'] or Decimal('0')
            depenses = Depense.objects.filter(
                logement__in=mes_logements, date__year=annee, date__month=m
            ).aggregate(t=Sum('montant'))['t'] or Decimal('0')
            rows.append([NOM_MOIS[m], float(encaisse), float(depenses), float(encaisse - depenses)])
            total_encaisse += encaisse
            total_depenses += depenses

        rows.append(['TOTAL ANNÉE', float(total_encaisse), float(total_depenses), float(total_encaisse - total_depenses)])
        return _reponse_export(headers, rows, f"recapitulatif_annuel_{annee}", fmt)


# ── PAIEMENTS ─────────────────────────────────────

class PaiementListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Paiement.objects.filter(occupant__proprietaire=request.user)
        if request.query_params.get('occupant_id'):
            qs = qs.filter(occupant_id=request.query_params['occupant_id'])
        return Response(PaiementSerializer(qs, many=True).data)

    def post(self, request):
        occupant_id = request.data.get('occupant')
        if occupant_id:
            get_occupant_or_404(request.user, occupant_id)
        s = PaiementSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class PaiementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, paiement_id):
        return Response(PaiementSerializer(get_paiement_or_404(request.user, paiement_id)).data)

    def delete(self, request, paiement_id):
        get_paiement_or_404(request.user, paiement_id).delete()
        return Response(status=204)


# ── DÉPENSES / CHARGES ────────────────────────────

class DepenseListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Depense.objects.filter(logement__proprietaire=request.user)
        if request.query_params.get('logement_id'):
            qs = qs.filter(logement_id=request.query_params['logement_id'])
        return Response(DepenseSerializer(qs, many=True).data)

    def post(self, request):
        logement_id = request.data.get('logement')
        if not logement_id:
            return Response({'logement': ['Ce champ est requis.']}, status=400)
        get_logement_or_404(request.user, logement_id)  # 404 si le logement n'appartient pas à l'utilisateur
        s = DepenseSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class DepenseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, depense_id):
        return Response(DepenseSerializer(get_depense_or_404(request.user, depense_id)).data)

    def put(self, request, depense_id):
        d = get_depense_or_404(request.user, depense_id)
        s = DepenseSerializer(d, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, depense_id):
        get_depense_or_404(request.user, depense_id).delete()
        return Response(status=204)


# ── PROFIL BAILLEUR ────────────────────────────────

class ProfileView(APIView):
    """Coordonnées du propriétaire/gestionnaire connecté (téléphone, adresse),
    utilisées notamment dans le contrat de bail PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    def put(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        s = ProfileSerializer(profile, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)


# ── DOCUMENTS / PIÈCES JOINTES ────────────────────

class DocumentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Document.objects.filter(proprietaire=request.user)
        if request.query_params.get('occupant_id'):
            qs = qs.filter(occupant_id=request.query_params['occupant_id'])
        if request.query_params.get('logement_id'):
            qs = qs.filter(logement_id=request.query_params['logement_id'])
        return Response(DocumentSerializer(qs, many=True).data)

    def post(self, request):
        # Comme pour Occupant/Dépense : on vérifie la propriété du locataire/
        # logement visé AVANT d'écrire le fichier sur disque.
        occupant_id = request.data.get('occupant')
        logement_id = request.data.get('logement')
        if occupant_id:
            get_occupant_or_404(request.user, occupant_id)
        if logement_id:
            get_logement_or_404(request.user, logement_id)

        s = DocumentSerializer(data=request.data)
        if s.is_valid():
            document = s.save(proprietaire=request.user)
            return Response(DocumentSerializer(document).data, status=201)
        return Response(s.errors, status=400)


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        return Response(DocumentSerializer(get_document_or_404(request.user, document_id)).data)

    def delete(self, request, document_id):
        document = get_document_or_404(request.user, document_id)
        document.fichier.delete(save=False)  # supprime aussi le fichier sur disque, pas juste la ligne en base
        document.delete()
        return Response(status=204)


class DocumentDownloadView(APIView):
    """Unique point d'accès aux octets d'un document. Ne JAMAIS exposer
    `fichier.url` dans un serializer à la place : MEDIA_URL n'a aucun
    contrôle d'accès, alors que cette vue revérifie la propriété à chaque
    appel via get_document_or_404()."""
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        document = get_document_or_404(request.user, document_id)
        if not document.fichier or not document.fichier.storage.exists(document.fichier.name):
            raise Http404
        return FileResponse(
            document.fichier.open('rb'),
            filename=document.nom_fichier or document.fichier.name.rsplit('/', 1)[-1],
            as_attachment=False,
        )


# ── ÉTAT DES LIEUX ─────────────────────────────────

class EtatDesLieuxListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = EtatDesLieux.objects.filter(proprietaire=request.user)
        if request.query_params.get('occupant_id'):
            qs = qs.filter(occupant_id=request.query_params['occupant_id'])
        if request.query_params.get('logement_id'):
            qs = qs.filter(logement_id=request.query_params['logement_id'])
        return Response(EtatDesLieuxSerializer(qs, many=True).data)

    def post(self, request):
        occupant_id = request.data.get('occupant')
        if not occupant_id:
            return Response({'occupant': ['Ce champ est requis.']}, status=400)
        get_occupant_or_404(request.user, occupant_id)  # 404 si l'occupant n'appartient pas à l'utilisateur

        s = EtatDesLieuxSerializer(data=request.data)
        if s.is_valid():
            edl = s.save(proprietaire=request.user)
            return Response(EtatDesLieuxSerializer(edl).data, status=201)
        return Response(s.errors, status=400)


class EtatDesLieuxDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, edl_id):
        return Response(EtatDesLieuxSerializer(get_etat_des_lieux_or_404(request.user, edl_id)).data)

    def put(self, request, edl_id):
        edl = get_etat_des_lieux_or_404(request.user, edl_id)
        s = EtatDesLieuxSerializer(edl, data=request.data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, edl_id):
        get_etat_des_lieux_or_404(request.user, edl_id).delete()
        return Response(status=204)


@method_decorator(xframe_options_exempt, name='get')
class EtatDesLieuxPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, edl_id):
        rl = get_reportlab()
        if not rl:
            return Response({'error': 'reportlab non installé.'}, status=500)
        A4, getSampleStyleSheet, ParagraphStyle, cm, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, colors = rl

        edl      = get_etat_des_lieux_or_404(request.user, edl_id)
        occupant = edl.occupant
        comp     = edl.compartiment
        logement = edl.logement

        proprio_nom = request.user.get_full_name() or request.user.username

        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2.5*cm, rightMargin=2.5*cm)
        styles = getSampleStyleSheet()
        story  = []

        accent = colors.HexColor('#4F46E5')
        ink    = colors.HexColor('#0F172A')
        muted  = colors.HexColor('#64748B')

        title_style = ParagraphStyle('title', parent=styles['Title'], fontSize=18, spaceAfter=4, alignment=1, textColor=accent)
        meta_style  = ParagraphStyle('meta', parent=styles['Normal'], fontSize=10, alignment=1, textColor=muted, spaceAfter=4)
        h2_style    = ParagraphStyle('h2', parent=styles['Heading2'], fontSize=13, spaceAfter=6, spaceBefore=12, textColor=ink)
        body_style  = ParagraphStyle('body', parent=styles['Normal'], fontSize=10.5, leading=15, spaceAfter=4)

        type_label = "D'ENTRÉE" if edl.type == 'ENTREE' else "DE SORTIE"
        story.append(Paragraph(f"ÉTAT DES LIEUX {type_label}", title_style))
        story.append(Paragraph(
            f"Réalisé le {edl.date_realisation.strftime('%d/%m/%Y')} &nbsp;·&nbsp; "
            f"Réf. bail : {occupant.numero_contrat or '—'}",
            meta_style
        ))
        story.append(Spacer(1, 0.4*cm))

        # ── Parties et logement ──
        # NB: des chaînes brutes dans les cellules d'une Table ne sont JAMAIS
        # retournées à la ligne — un nom de logement/label un peu long déborde
        # alors directement sur la cellule voisine. On enveloppe donc chaque
        # cellule dans un Paragraph, qui respecte lui la largeur de colonne.
        story.append(Paragraph("Informations générales", h2_style))
        label_style = ParagraphStyle('label', parent=styles['Normal'], fontSize=9.5, textColor=muted, fontName='Helvetica-Bold', leading=12)
        value_style = ParagraphStyle('value', parent=styles['Normal'], fontSize=9.5, textColor=ink, leading=12)

        def _cell(text, style):
            return Paragraph(text, style)

        infos_rows = [
            [_cell("Bailleur", label_style), _cell(proprio_nom, value_style),
             _cell("Locataire", label_style), _cell(occupant.nom_complet, value_style)],
            [_cell("Logement", label_style), _cell(logement.nom if logement else '—', value_style),
             _cell("Compartiment", label_style), _cell(comp.nom if comp else '—', value_style)],
            [_cell("État général constaté", label_style), _cell(edl.get_etat_general_display(), value_style),
             _cell("Clés remises", label_style), _cell(str(edl.cles_remises), value_style)],
        ]
        infos_table = Table(infos_rows, colWidths=[3.2*cm, 5.3*cm, 3.2*cm, 5.3*cm])
        infos_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        story.append(infos_table)
        story.append(Spacer(1, 0.4*cm))

        # ── Détail pièce par pièce ──
        champs = edl.champs_details or {}
        if champs:
            story.append(Paragraph("Détail par pièce", h2_style))
            detail_header_style = ParagraphStyle('detail_header', parent=styles['Normal'], fontSize=9.5, textColor=colors.white, fontName='Helvetica-Bold', leading=12)
            detail_cell_style   = ParagraphStyle('detail_cell', parent=styles['Normal'], fontSize=9.5, textColor=ink, leading=12)
            detail_rows = [[
                Paragraph("Pièce", detail_header_style),
                Paragraph("Élément", detail_header_style),
                Paragraph("État constaté", detail_header_style),
            ]]
            for piece, elements in champs.items():
                if not isinstance(elements, dict):
                    continue
                for element, etat in elements.items():
                    detail_rows.append([
                        Paragraph(str(piece), detail_cell_style),
                        Paragraph(str(element), detail_cell_style),
                        Paragraph(str(etat), detail_cell_style),
                    ])
            if len(detail_rows) > 1:
                detail_table = Table(detail_rows, colWidths=[4.5*cm, 6*cm, 6.5*cm], repeatRows=1)
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), accent),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9.5),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 5),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
                ]))
                story.append(detail_table)
                story.append(Spacer(1, 0.4*cm))

        # ── Observations ──
        story.append(Paragraph("Observations", h2_style))
        story.append(Paragraph(edl.observations.replace('\n', '<br/>') if edl.observations else "Aucune observation particulière.", body_style))
        story.append(Spacer(1, 0.8*cm))

        # ── Signatures ──
        # NB: Paragraph n'interprète jamais un "\n" littéral comme saut de ligne —
        # on utilise donc une vraie Table à 2 lignes avec rowHeights explicite
        # pour l'espace de signature (déjà appris lors du contrat de bail PDF).
        sign_style = ParagraphStyle('sign', parent=styles['Normal'], fontSize=9.5, textColor=muted)
        sign_rows = [
            [Paragraph("Le Bailleur (ou son représentant)", sign_style), Paragraph("Le Locataire", sign_style)],
            ["", ""],
        ]
        sign_table = Table(sign_rows, colWidths=[7.5*cm, 7.5*cm], rowHeights=[0.6*cm, 2.2*cm])
        sign_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 1), (0, 1), 0.8, ink),
            ('LINEABOVE', (1, 1), (1, 1), 0.8, ink),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('TOPPADDING', (0, 1), (-1, 1), 4),
        ]))
        story.append(sign_table)

        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="etat_des_lieux_{edl.id}.pdf"'
        return response


# ── NOTIFICATIONS & RAPPELS D'ÉCHÉANCES ───────────

class NotificationsDashboardView(APIView):
    """Calcule en temps réel, pour l'utilisateur connecté, les 4 catégories
    d'alertes : baux arrivant à expiration, loyers en retard, anniversaires
    de bail (révision/renouvellement) et compartiments vacants depuis
    longtemps. Rien n'est stocké en base — tout est recalculé à chaque appel."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mes_logements = Logement.objects.filter(proprietaire=request.user)
        today = date.today()

        # 1. Baux arrivant à expiration dans les 60 jours (ou déjà expirés)
        baux_expirants = []
        occupants_echeance = Occupant.objects.filter(
            actif=True, logement__in=mes_logements,
            date_fin_contrat__isnull=False,
            date_fin_contrat__lte=today + timedelta(days=60),
        ).select_related('compartiment', 'logement').order_by('date_fin_contrat')
        for o in occupants_echeance:
            jours = (o.date_fin_contrat - today).days
            baux_expirants.append({
                'occupant_id': o.id, 'nom': o.nom_complet, 'telephone': o.telephone,
                'compartiment': o.compartiment.nom if o.compartiment else '—',
                'logement': o.logement.nom if o.logement else '—',
                'date_fin_contrat': str(o.date_fin_contrat),
                'jours_restants': jours,
                'expire': jours < 0,
            })

        # 2. Loyers en retard — même logique de statut que le Dashboard.
        loyers_en_retard = []
        occupants_retard = Occupant.objects.filter(
            actif=True, logement__in=mes_logements, statut='En retard'
        ).select_related('compartiment', 'logement').order_by('date_prochain_paiement')
        for o in occupants_retard:
            loyers_en_retard.append({
                'occupant_id': o.id, 'nom': o.nom_complet, 'telephone': o.telephone,
                'compartiment': o.compartiment.nom if o.compartiment else '—',
                'logement': o.logement.nom if o.logement else '—',
                'depuis': str(o.date_prochain_paiement),
                'mois_retard': _mois_retard(o.date_prochain_paiement),
            })

        # 3. Anniversaires de bail (révision de loyer / renouvellement) dans
        #    les 30 prochains jours — calculé depuis date_debut_contrat, pas
        #    stocké, pour rester toujours à jour même si le bail est ancien.
        renouvellements = []
        occupants_actifs = Occupant.objects.filter(
            actif=True, logement__in=mes_logements, date_debut_contrat__isnull=False
        ).select_related('compartiment', 'logement')
        for o in occupants_actifs:
            annees_ecoulees = relativedelta(today, o.date_debut_contrat).years
            prochaine = o.date_debut_contrat + relativedelta(years=max(annees_ecoulees, 1))
            if prochaine < today:
                prochaine += relativedelta(years=1)
            jours = (prochaine - today).days
            if 0 <= jours <= 30:
                renouvellements.append({
                    'occupant_id': o.id, 'nom': o.nom_complet, 'telephone': o.telephone,
                    'compartiment': o.compartiment.nom if o.compartiment else '—',
                    'logement': o.logement.nom if o.logement else '—',
                    'date_anniversaire': str(prochaine),
                    'jours_restants': jours,
                })

        # 4. Compartiments vacants depuis plus de 30 jours.
        compartiments_vacants = []
        libres = Compartiment.objects.filter(logement__in=mes_logements, statut='LIBRE').select_related('logement')
        for c in libres:
            dernier_depart = (
                HistoriqueOccupation.objects.filter(compartiment=c, date_sortie__isnull=False)
                .order_by('-date_sortie').values_list('date_sortie', flat=True).first()
            )
            if dernier_depart:
                baseline = dernier_depart
            elif c.date_creation:
                baseline = c.date_creation.date()
            else:
                continue  # aucune référence temporelle disponible — on ignore plutôt que de deviner
            jours_vacant = (today - baseline).days
            if jours_vacant > 30:
                compartiments_vacants.append({
                    'compartiment_id': c.id, 'nom': c.nom, 'type': c.type,
                    'logement_id': c.logement_id, 'logement': c.logement.nom,
                    'depuis': str(baseline), 'jours_vacants': jours_vacant,
                })

        return Response({
            'baux_expirants':         baux_expirants,
            'loyers_en_retard':       loyers_en_retard,
            'renouvellements':        renouvellements,
            'compartiments_vacants':  compartiments_vacants,
            'total': (
                len(baux_expirants) + len(loyers_en_retard) +
                len(renouvellements) + len(compartiments_vacants)
            ),
        })


# ═══════════════════════════════════════════════════════════════════
# ADMINISTRATION (super admin uniquement — accès cross-tenant délibéré)
# ═══════════════════════════════════════════════════════════════════
# Tout le reste de cette API filtre STRICTEMENT par request.user. Les vues
# ci-dessous sont la SEULE exception volontaire : elles voient les données de
# TOUS les utilisateurs. IsAdminUser (= request.user.is_staff) est donc
# systématique et non négociable sur chacune d'entre elles.

class AdminStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        today = date.today()
        mois, annee = today.month, today.year
        return Response({
            'total_users':          User.objects.count(),
            'active_users':         User.objects.filter(is_active=True).count(),
            'verified_users':       Profile.objects.filter(is_verified=True).count(),
            'total_logements':      Logement.objects.count(),
            'total_occupants':      Occupant.objects.filter(actif=True).count(),
            'total_paiements_mois': float(
                Paiement.objects.filter(date_paiement__month=mois, date_paiement__year=annee)
                .aggregate(t=Sum('montant_verse'))['t'] or 0
            ),
            'total_depenses_mois': float(
                Depense.objects.filter(date__month=mois, date__year=annee)
                .aggregate(t=Sum('montant'))['t'] or 0
            ),
        })


class AdminUsersListView(generics.ListAPIView):
    serializer_class    = AdminUserSerializer
    permission_classes  = [IsAdminUser]
    pagination_class    = StandardResultsSetPagination

    def get_queryset(self):
        qs = User.objects.select_related('profile').annotate(
            nb_logements=Count('logements')
        ).order_by('-date_joined')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(email__icontains=search)
        return qs


class AdminUserToggleActiveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id):
        target = get_object_or_404(User, id=user_id)
        va_desactiver = target.is_active  # is_active==True -> ce post() va le faire passer à False

        # Deux garde-fous : jamais désactiver un Super Admin, jamais se
        # désactiver soi-même — SimpleJWT revalide is_active à CHAQUE requête
        # (pas seulement à l'émission du token), donc une auto-désactivation
        # verrouillerait l'admin hors de son propre compte instantanément.
        if va_desactiver and target.is_superuser:
            return Response({'error': 'Impossible de désactiver un compte Super Admin.'}, status=400)
        if va_desactiver and target.id == request.user.id:
            return Response({'error': 'Vous ne pouvez pas désactiver votre propre compte.'}, status=400)

        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        log_activity(
            target, 'ACCOUNT_ACTIVATED' if target.is_active else 'ACCOUNT_DEACTIVATED',
            description=f"{target.email} (par admin {request.user.email})"
        )
        qs = User.objects.select_related('profile').annotate(nb_logements=Count('logements')).get(pk=target.pk)
        return Response(AdminUserSerializer(qs).data)


class AdminUserResetPasswordView(APIView):
    """Déclenche le MÊME flux que 'mot de passe oublié' — aucune nouvelle
    logique d'email, juste initié par un admin plutôt que par l'utilisateur."""
    permission_classes = [IsAdminUser]

    def post(self, request, user_id):
        target = get_object_or_404(User, id=user_id)
        try:
            envoyer_email_reset_password(target, make_password_reset_token(target))
        except Exception as e:
            logger.error("Échec de l'envoi de l'email de réinitialisation (admin) à %s : %s", target.email, e, exc_info=True)
            return Response({'error': "Échec de l'envoi de l'email."}, status=500)
        return Response({'message': f"Email de réinitialisation envoyé à {target.email}."})


# ── Logements (admin) ─────────────────────────────

class AdminLogementListCreateView(generics.ListCreateAPIView):
    queryset           = Logement.objects.all().select_related('proprietaire').order_by('-date_creation')
    serializer_class    = AdminLogementSerializer
    permission_classes  = [IsAdminUser]
    pagination_class    = StandardResultsSetPagination


class AdminLogementDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Logement.objects.all()
    serializer_class    = AdminLogementSerializer
    permission_classes  = [IsAdminUser]


class AdminCompartimentsByLogementView(generics.ListAPIView):
    """Équivalent cross-tenant de CompartimentsByLogementView — nécessaire
    pour le sélecteur en cascade propriétaire→logement→compartiment du
    formulaire Occupant admin (l'admin n'est jamais propriétaire du logement
    qu'il consulte, donc la vue "tenant" filtrée par request.user 404 systématiquement)."""
    serializer_class   = CompartimentSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return Compartiment.objects.filter(logement_id=self.kwargs['logement_id'])


# ── Occupants (admin) ─────────────────────────────
# PAS de generics DRF ici, volontairement : logement est TOUJOURS dérivé de
# compartiment côté serveur, jamais accepté tel quel du client — sinon un
# admin pourrait combiner, via deux champs indépendants, un logement et un
# compartiment appartenant à deux propriétaires différents (rien dans
# OccupantSerializer.validate() ne détecte cette incohérence).

class AdminOccupantListCreateView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Occupant.objects.filter(actif=True).select_related(
            'compartiment', 'logement', 'proprietaire'
        ).order_by('-date_creation')
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(OccupantSerializer(page, many=True).data)

    def post(self, request):
        data = request.data.copy()
        compartiment_id = data.get('compartiment')
        if not compartiment_id:
            return Response({'compartiment': ['Ce champ est requis.']}, status=400)
        compartiment = get_object_or_404(Compartiment, id=compartiment_id)
        data['logement'] = compartiment.logement_id

        s = OccupantSerializer(data=data)
        if s.is_valid():
            occupant = s.save()
            return Response(OccupantSerializer(occupant).data, status=201)
        return Response(s.errors, status=400)


class AdminOccupantDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, occupant_id):
        return Response(OccupantSerializer(get_object_or_404(Occupant, id=occupant_id)).data)

    def put(self, request, occupant_id):
        occupant = get_object_or_404(Occupant, id=occupant_id)
        data = request.data.copy()
        compartiment_id = data.get('compartiment', occupant.compartiment_id)
        if compartiment_id:
            compartiment = get_object_or_404(Compartiment, id=compartiment_id)
            data['logement'] = compartiment.logement_id
        s = OccupantSerializer(occupant, data=data, partial=True)
        if s.is_valid():
            s.save()
            return Response(s.data)
        return Response(s.errors, status=400)

    def delete(self, request, occupant_id):
        get_object_or_404(Occupant, id=occupant_id).delete()
        return Response(status=204)


# ── Paiements (admin) ─────────────────────────────

class AdminPaiementListCreateView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Paiement.objects.all().select_related('occupant').order_by('-date_paiement')
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(PaiementSerializer(page, many=True).data)

    def post(self, request):
        s = PaiementSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class AdminPaiementDetailView(APIView):
    """Volontairement PAS de PUT — même limitation que PaiementDetailView
    "tenant" : Paiement.save() recalcule sans condition date_prochain_paiement
    et statut de l'occupant à partir de LA PÉRIODE DE CE PAIEMENT PRÉCIS ;
    éditer un ancien encaissement écraserait silencieusement une échéance
    calculée depuis des paiements plus récents."""
    permission_classes = [IsAdminUser]

    def get(self, request, paiement_id):
        return Response(PaiementSerializer(get_object_or_404(Paiement, id=paiement_id)).data)

    def delete(self, request, paiement_id):
        get_object_or_404(Paiement, id=paiement_id).delete()
        return Response(status=204)


# ── Dépenses (admin) ──────────────────────────────

class AdminDepenseListCreateView(generics.ListCreateAPIView):
    queryset           = Depense.objects.all().select_related('logement').order_by('-date')
    serializer_class    = DepenseSerializer
    permission_classes  = [IsAdminUser]
    pagination_class    = StandardResultsSetPagination


class AdminDepenseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Depense.objects.all()
    serializer_class    = DepenseSerializer
    permission_classes  = [IsAdminUser]


# ── États des lieux (admin) ───────────────────────

class AdminEtatDesLieuxListCreateView(generics.ListCreateAPIView):
    queryset           = EtatDesLieux.objects.all().select_related('occupant', 'logement', 'compartiment').order_by('-date_realisation')
    serializer_class    = EtatDesLieuxSerializer
    permission_classes  = [IsAdminUser]
    pagination_class    = StandardResultsSetPagination
    # Piège à ne pas réintroduire : ne JAMAIS surcharger perform_create() pour
    # passer proprietaire=request.user ici (contrairement à la vue "tenant").
    # EtatDesLieux.save() dérive déjà proprietaire/logement/compartiment
    # depuis occupant tout seul — le faire ici réassignerait le document à
    # l'admin au lieu du vrai bailleur.


class AdminEtatDesLieuxDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = EtatDesLieux.objects.all()
    serializer_class    = EtatDesLieuxSerializer
    permission_classes  = [IsAdminUser]


# ── Journal d'activité (admin) ────────────────────

class AdminActivityLogListView(generics.ListAPIView):
    queryset           = ActivityLog.objects.all().select_related('user')
    serializer_class    = ActivityLogSerializer
    permission_classes  = [IsAdminUser]
    pagination_class    = StandardResultsSetPagination