import traceback
import base64
import json
import geojson
import re
import hashlib
import uuid
from six.moves.urllib.parse import urlparse
from wsgiref.util import FileWrapper
from django.db import connection, transaction
from django.db.models import Q, Min
from django.http import HttpResponse
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from rest_framework import viewsets, serializers, status, generics, views
from rest_framework.decorators import action as detail_route, renderer_classes
from rest_framework.decorators import action as list_route
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timedelta, date
from collections import OrderedDict
from django.core.cache import cache
from ledger_api_client import utils as ledger_api_utils
import os
##
from ledger_api_client.ledger_models import EmailUserRO as EmailUser
from ledger_api_client.ledger_models import Address
from ledger_api_client.ledger_models import Invoice
from ledger_api_client.ledger_models import Basket
from ledger_api_client.country_models import Country
from django.shortcuts import render, get_object_or_404, redirect

##
#from ledger.accounts.models import EmailUser, Address
#from ledger.address.models import Country
#from ledger.payments.models import Invoice
from parkstay import doctopdf
from parkstay import utils
from parkstay.image_utils import get_image_content_file
from parkstay import property_cache 
from parkstay import models
from parkstay.helpers import can_view_campground
from parkstay import utils_cache
from parkstay import models as parkstay_models
from parkstay.models import (Campground,
                             District,
                             Contact,
                             CampsiteBooking,
                             Campsite,
                             CampsiteClass,
                             CampsiteRate,
                             Booking,
                             BookingInvoice,
                             CampgroundBookingRange,
                             CampsiteBookingRange,
                             CampsiteStayHistory,
                             CampgroundStayHistory,
                             PromoArea,
                             Park,
                             Feature,
                             Region,
                             Rate,
                             CampgroundPriceHistory,
                             CampsiteClassPriceHistory,
                             ClosureReason,
                             PriceReason,
                             MaximumStayReason,
                             DiscountReason,
                             ParkEntryRate,
                             Places,
                             CampgroundImage
                             )

from parkstay.serialisers import (CampsiteBookingSerialiser,
                                  CampsiteSerialiser,
                                  ContactSerializer,
                                  DistrictSerializer,
                                  CampgroundMapSerializer,
                                  CampgroundMapFilterSerializer,
                                  CampgroundSerializer,
                                  CampgroundDatatableSerializer,
                                  CampgroundCampsiteFilterSerializer,
                                  CampsiteBookingSerializer,
                                  PromoAreaSerializer,
                                  ParkSerializer,
                                  FeatureSerializer,
                                  RegionSerializer,
                                  CampsiteClassSerializer,
                                  BookingSerializer,
                                  CampgroundBookingRangeSerializer,
                                  CampsiteBookingRangeSerializer,
                                  CampsiteRateSerializer,
                                  CampsiteRateReadonlySerializer,
                                  CampsiteStayHistorySerializer,
                                  CampgroundStayHistorySerializer,
                                  RateSerializer,
                                  RateDetailSerializer,
                                  CampgroundPriceHistorySerializer,
                                  CampsiteClassPriceHistorySerializer,
                                  CampgroundImageSerializer,
                                  ExistingCampgroundImageSerializer,
                                  ClosureReasonSerializer,
                                  PriceReasonSerializer,
                                  MaximumStayReasonSerializer,
                                  DiscountReasonSerializer,
                                  BulkPricingSerializer,
                                  UsersSerializer,
                                  ParkEntryRateSerializer,
                                  ReportSerializer,
                                  BookingSettlementReportSerializer,
                                  CountrySerializer,
                                  UserSerializer,
                                  UserAddressSerializer,
                                  ContactSerializer as UserContactSerializer,
                                  PersonalSerializer,
                                  PhoneSerializer,
                                  OracleSerializer,
                                  BookingHistorySerializer
                                  )
from parkstay.helpers import is_officer
from parkstay import reports
from parkstay import pdf
from parkstay.perms import PaymentCallbackPermission, OfficerPermission, OfficerOrReadOnlyPermission
from parkstay.sanitisation import check_plain_text
from parkstay import emails
from parkstay import booking_availability
from parkstay import context_processors

# API Views
class CampsiteBookingViewSet(viewsets.ModelViewSet):
    queryset = CampsiteBooking.objects.all()
    serializer_class = CampsiteBookingSerialiser
    permission_classes = [OfficerPermission]


class DistrictViewSet(viewsets.ModelViewSet):
    queryset = District.objects.all()
    serializer_class = DistrictSerializer
    permission_classes = [OfficerOrReadOnlyPermission]


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [OfficerPermission]


class CampsiteViewSet(viewsets.ModelViewSet):
    queryset = Campsite.objects.all()
    serializer_class = CampsiteSerialiser
    permission_classes = [OfficerPermission]

    def list(self, request, format=None):
        queryset = self.get_queryset()
        formatted = bool(request.GET.get("formatted", False))
        serializer = self.get_serializer(queryset, formatted=formatted, many=True, method='get')
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        formatted = bool(request.GET.get("formatted", False))
        serializer = self.get_serializer(instance, formatted=formatted, method='get')
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)

            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def create(self, request, *args, **kwargs):
        try:
            http_status = status.HTTP_200_OK
            number = request.data.pop('number')

            # campground_temp = request.data.get('campground')
            # campsite_temp = request.data.get('campsite_class')
            #
            # data = {
            #
            # }

            serializer = self.get_serializer(data=request.data, method='post')
            serializer.is_valid(raise_exception=True)

            if number > 1:
                data = dict(serializer.validated_data)
                campsites = Campsite.bulk_create(number, data)
                res = self.get_serializer(campsites, many=True)
            else:
                if number == 1 and serializer.validated_data['name'] == 'default':
                    latest = 0
                    current_campsites = Campsite.objects.filter(campground=serializer.validated_data.get('campground'))
                    cs_numbers = [int(c.name) for c in current_campsites if c.name.isdigit()]
                    if cs_numbers:
                        latest = max(cs_numbers)
                    if len(str(latest + 1)) == 1:
                        name = '0{}'.format(latest + 1)
                    else:
                        name = str(latest + 1)
                    serializer.validated_data['name'] = name
                instance = serializer.save()
                res = self.get_serializer(instance)

            return Response(res.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def close_campsites(self, closure_data, campsites):        
        for campsite in campsites:
            closure_data['campsite'] = campsite
            try:
                serializer = CampsiteBookingRangeSerializer(data=closure_data, method='post')
                serializer.is_valid(raise_exception=True)
                instance = Campsite.objects.get(pk=campsite)
                instance.close(dict(serializer.validated_data))
            except Exception as e:
                print (e)
                raise

    @list_route(methods=['post'], detail=False)
    def bulk_close(self, request, format='json', pk=None):
        with transaction.atomic():
            try:
                http_status = status.HTTP_200_OK
                closure_data = request.data.copy()        
                campsites = closure_data.pop('campsites[]')
                self.close_campsites(closure_data, campsites)
                return Response('All selected campsites closed')
            except serializers.ValidationError:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))
            except Exception as e:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))

    @detail_route(methods=['get'], detail=True)
    def status_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            # Check what status is required
            closures = bool(request.GET.get("closures", False))
            if closures:
                serializer = CampsiteBookingRangeSerializer(self.get_object().booking_ranges.filter(~Q(status=0)).order_by('-range_start'), many=True)
            else:
                serializer = CampsiteBookingRangeSerializer(self.get_object().booking_ranges, many=True)
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def stay_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            serializer = CampsiteStayHistorySerializer(self.get_object().stay_history, many=True, context={'request': request}, method='get')
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def price_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            price_history = self.get_object().rates.all().order_by('-date_start')
            serializer = CampsiteRateReadonlySerializer(price_history, many=True, context={'request': request})
            res = serializer.data
            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def current_price(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            start_date = request.GET.get('arrival', False)
            end_date = request.GET.get('departure', False)
            res = []
            if start_date and end_date:
                res = utils.get_campsite_current_rate(request, self.get_object().id, start_date, end_date)
            else:
                res.append({
                    "error": "Arrival and departure dates are required",
                    "success": False
                })

            return Response(res, status=http_status)
        except serializers.ValidationError:
            traceback.print_exc()
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @csrf_exempt
    @list_route(methods=['post'], detail=False)
    def current_price_list(self, request, format='json', pk=None):
        with transaction.atomic():
            try:
                http_status = status.HTTP_200_OK
                rate_data = request.data.copy()
                campsites = rate_data.pop('campsites')
                start_date = rate_data.pop('arrival')
                end_date = rate_data.pop('departure')
                res = utils.get_campsites_current_rate(self.request, campsites, start_date, end_date)

                return Response(res, status=http_status)
            except serializers.ValidationError:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))
            except Exception as e:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))


class CampsiteStayHistoryViewSet(viewsets.ModelViewSet):
    queryset = CampsiteStayHistory.objects.all()
    serializer_class = CampsiteStayHistorySerializer
    permission_classes = [OfficerPermission]

    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            if instance.range_end and not serializer.validated_data.get('range_end'):
                instance.range_end = None
            self.perform_update(serializer)

            return Response(serializer.data)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))


class CampgroundStayHistoryViewSet(viewsets.ModelViewSet):
    queryset = CampgroundStayHistory.objects.all()
    serializer_class = CampgroundStayHistorySerializer
    permission_classes = [OfficerPermission]

    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            if instance.range_end and not serializer.validated_data.get('range_end'):
                instance.range_end = None
            self.perform_update(serializer)

            return Response(serializer.data)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))


class CampgroundMapViewSet(viewsets.ReadOnlyModelViewSet):
    #queryset = Campground.objects.exclude(campground_type=3).annotate(Min('campsites__rates__rate__adult'))

    #Changed to speed up the loading of icons in map

    queryset = Campground.objects.filter(campground_type=9)[:1]
    #queryset = []
    serializer_class = CampgroundMapSerializer
    permission_classes = []
    def get_queryset(self):
        """ allow rest api to filter by submissions """
        #queryset = Prpk.objects.all().order_by('begin')
        #highway = self.request.query_params.get('highway', None)
        #if highway is not None:
        #    queryset = queryset.filter(highway=highway)
        queryset = cache.get('CampgroundMapViewSet')
        if queryset is None:
            queryset = Campground.objects.exclude(campground_type=3)
            cache.set('CampgroundMapViewSet', queryset, 3600)
        return queryset

    #def list(self, request, *args, **kwargs):
    #    
    #    serializer = self.get_serializer(queryset, many=True)
    #    return Response(serializer.data)

class CampgroundMapFilterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Campground.objects.exclude(campground_type=3)
    serializer_class = CampgroundMapFilterSerializer
    permission_classes = []

    def list(self, request, *args, **kwargs):
        data = {
            "arrival": request.GET.get('arrival', None),
            "departure": request.GET.get('departure', None),
            "num_adult": request.GET.get('num_adult', 0),
            "num_concession": request.GET.get('num_concession', 0),
            "num_child": request.GET.get('num_child', 0),
            "num_infant": request.GET.get('num_infant', 0),
            "gear_type": request.GET.get('gear_type', 'all')
        }

        #data_hash = hashlib.sha224(b"D {}".format(request.GET.get('arrival', None))).hexdigest()
        data_hash = hashlib.md5(str(data).encode('utf-8')).hexdigest()
        dumped_data = cache.get('CampgroundMapFilterViewSet'+data_hash)
        dumped_data = None
        if dumped_data is None:
            serializer = CampgroundCampsiteFilterSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            scrubbed = serializer.validated_data
            context = {}
            # filter to the campsites by gear allowed (if specified), else show the lot
            if scrubbed['gear_type'] != 'all':
                context = {scrubbed['gear_type']: True}
            # if a date range is set, filter out campgrounds that are unavailable for the whole stretch
            if scrubbed['arrival'] and scrubbed['departure'] and (scrubbed['arrival'] < scrubbed['departure']):
                sites = Campsite.objects.filter(**context)
                ground_ids = utils.get_open_campgrounds(sites, scrubbed['arrival'], scrubbed['departure'])

            else:  # show all of the campgrounds with campsites
                ground_ids = set((x[0] for x in Campsite.objects.filter(**context).values_list('campground')))
                # we need to be tricky here. for the default search (all, no timestamps),
                # we want to include all of the "campgrounds" that don't have any campsites in the model! (e.g. third party)
                if scrubbed['gear_type'] == 'all':
                    ground_ids.update((x[0] for x in Campground.objects.filter(campsites__isnull=True).values_list('id')))

            # Filter out for the max period
            today = date.today()
            if scrubbed['arrival']:
                start_date = scrubbed['arrival']
            else:
                start_date = today
            if scrubbed['departure']:
                end_date = scrubbed['departure']
            else:
                end_date = today + timedelta(days=1)

            temp_queryset = Campground.objects.filter(id__in=ground_ids).order_by('name')
            queryset = []
            for q in temp_queryset:
                # Get the current stay history
                stay_history = CampgroundStayHistory.objects.filter(
                    Q(range_start__lte=start_date, range_end__gte=start_date) |  # filter start date is within period
                    Q(range_start__lte=end_date, range_end__gte=end_date) |  # filter end date is within period
                    Q(Q(range_start__gt=start_date, range_end__lt=end_date) & Q(range_end__gt=today)),  # filter start date is before and end date after period
                    campground=q
                )
                if stay_history:
                    max_days = min([x.max_days for x in stay_history])
                else:
                    max_days = settings.PS_MAX_BOOKING_LENGTH
                if (end_date - start_date).days <= max_days:
                    queryset.append(q)
            serializer = self.get_serializer(queryset, many=True)
            dumped_data = serializer.data
            cache.set('CampgroundMapFilterViewSet'+data_hash, dumped_data, 3600)
        return Response(dumped_data)


@require_http_methods(['GET'])
def search_suggest(request, *args, **kwargs):
    dumped_data = "[]"
    if os.path.isfile(settings.DATA_STORE+"/search_suggest.json"):
        f = open(settings.DATA_STORE+"/search_suggest.json", "r")
        dumped_data = f.read()
    else:
        dumped_data = search_suggest_data() 
        f = open(settings.DATA_STORE+"/search_suggest.json", "w")
        f.write(dumped_data)
        f.close()

    #dumped_data = search_suggest_data()
    return HttpResponse(dumped_data, content_type='application/json')

def search_suggest_data():
    entries = []
    for x in Campground.objects.filter(wkb_geometry__isnull=False).exclude(campground_type=3).values_list('id', 'name', 'wkb_geometry','zoom_level'):
        entries.append(geojson.Point((x[2].x, x[2].y), properties={'type': 'Campground', 'id': x[0], 'name': x[1], 'zoom_level': x[3]}))
    for x in Park.objects.filter(wkb_geometry__isnull=False).values_list('id', 'name', 'wkb_geometry','zoom_level'):
        entries.append(geojson.Point((x[2].x, x[2].y), properties={'type': 'Park', 'id': x[0], 'name': x[1], 'zoom_level': x[3]}))
    for x in PromoArea.objects.filter(wkb_geometry__isnull=False).values_list('id', 'name', 'wkb_geometry','zoom_level'):
        entries.append(geojson.Point((x[2].x, x[2].y), properties={'type': 'PromoArea', 'id': x[0], 'name': x[1], 'zoom_level': x[3]}))
    return geojson.dumps(geojson.FeatureCollection(entries))


def complete_booking(request, booking_hash, booking_id):
    #booking_hash=request.GET.get('booking_hash',None)
    #booking_id = request.GET.get('booking_id', None)
    jsondata={"status": "error completing booking"}
    if booking_hash:
           try: 
                booking = Booking.objects.get(id=booking_id,booking_hash=booking_hash)
                basket = Basket.objects.filter(status='Submitted', booking_reference=settings.BOOKING_PREFIX+'-'+str(booking.id)).order_by('-id')[:1]
                if basket.count() > 0:
                    pass
                else:
                    raise ValidationError('Error unable to find basket')

                utils.bind_booking(booking, basket)
                jsondata={"status": "success"}
           except Exception as e:
               print ("EXCEPTION")
               print (e)
               jsondata={"status": "error binding"}
    response = HttpResponse(json.dumps(jsondata), content_type='application/json')
    return response


class CampgroundViewSet(viewsets.ModelViewSet):
    queryset = Campground.objects.all()
    serializer_class = CampgroundSerializer
    permission_classes = [OfficerPermission]

    @list_route(methods=['GET', ], detail=False)
    @renderer_classes((JSONRenderer,))
    def datatable_list(self, request, format=None):
        queryset = cache.get('campgrounds_dt')
        if queryset is None:
            queryset = self.get_queryset()
            cache.set('campgrounds_dt', queryset, 3600)
        qs = [c for c in queryset.all() if can_view_campground(request.user, c)]
        serializer = CampgroundDatatableSerializer(qs, many=True)
        data = serializer.data
        return Response(data)

    @renderer_classes((JSONRenderer,))
    def list(self, request, format=None):

        queryset = cache.get('campgrounds')
        formatted = bool(request.GET.get("formatted", False))
        if queryset is None:
            queryset = self.get_queryset()
            cache.set('campgrounds', queryset, 3600)
        qs = [c for c in queryset.all() if can_view_campground(request.user, c)]
        serializer = self.get_serializer(qs, formatted=formatted, many=True, method='get')
        data = serializer.data
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        formatted = bool(request.GET.get("formatted", False))
        serializer = self.get_serializer(instance, formatted=formatted, method='get')
        return Response(serializer.data)

    def strip_b64_header(self, content):
        if ';base64,' in content:
            header, base64_data = content.split(';base64,')
            return base64_data
        return content

    def create(self, request, format=None):
        try:
            images_data = None
            http_status = status.HTTP_200_OK
            if "images" in request.data:
                images_data = request.data.pop("images")
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            # Get and Validate campground images
            initial_image_serializers = [CampgroundImageSerializer(data=image) for image in images_data] if images_data else []
            image_serializers = []
            if initial_image_serializers:

                for image_serializer in initial_image_serializers:
                    result = urlparse(image_serializer.initial_data['image'])
                    if not (result.scheme == 'http' or result.scheme == 'https') and not result.netloc:
                        image_serializers.append(image_serializer)

                if image_serializers:
                    for image_serializer in image_serializers:
                        image_serializer.initial_data["campground"] = instance.id
                        image_serializer.initial_data["image"] = get_image_content_file(image_serializer.initial_data["image"])

                    for image_serializer in image_serializers:
                        image_serializer.is_valid(raise_exception=True)

                    for image_serializer in image_serializers:
                        image_serializer.save()

            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def update(self, request, *args, **kwargs):
        try:
            images_data = None
            http_status = status.HTTP_200_OK
            instance = self.get_object()
            if "images" in request.data:
                images_data = request.data.pop("images")
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            # Get and Validate campground images
            initial_image_serializers = [CampgroundImageSerializer(data=image) for image in images_data] if images_data else []
            image_serializers, existing_image_serializers = [], []
            # Get campgrounds current images
            current_images = instance.images.all()
            if initial_image_serializers:

                for image_serializer in initial_image_serializers:
                    result = urlparse(image_serializer.initial_data['image'])
                    if not (result.scheme == 'http' or result.scheme == 'https') and not result.netloc:
                        image_serializers.append(image_serializer)
                    else:
                        data = {
                            'id': image_serializer.initial_data['id'],
                            'image': image_serializer.initial_data['image'],
                            'campground': instance.id
                        }
                        existing_image_serializers.append(ExistingCampgroundImageSerializer(data=data))

                # Dealing with existing images
                images_id_list = []
                for image_serializer in existing_image_serializers:
                    image_serializer.is_valid(raise_exception=True)
                    images_id_list.append(image_serializer.validated_data['id'])

                # Get current object images and check if any has been removed
                for img in current_images:
                    if img.id not in images_id_list:
                        img.delete()

                # Creating new Images
                if image_serializers:
                    for image_serializer in image_serializers:
                        image_serializer.initial_data["campground"] = instance.id
                        image_serializer.initial_data["image"] = get_image_content_file(image_serializer.initial_data["image"])

                    for image_serializer in image_serializers:
                        image_serializer.is_valid(raise_exception=True)

                    for image_serializer in image_serializers:
                        image_serializer.save()
            else:
                if current_images:
                    current_images.delete()

            self.perform_update(serializer)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def close_campgrounds(self, closure_data, campgrounds):
        for campground in campgrounds:
            closure_data['campground'] = campground
            try:
                serializer = CampgroundBookingRangeSerializer(data=closure_data, method="post")
                serializer.is_valid(raise_exception=True)
                instance = Campground.objects.get(pk=campground)
                instance.close(dict(serializer.validated_data))
            except Exception as e:
                raise

    @list_route(methods=['post'], detail=False)
    def bulk_close(self, request, format='json', pk=None):
        print ("CLOSE BULK")
        with transaction.atomic():
            try:
                http_status = status.HTTP_200_OK
                closure_data = request.data.copy()
                campgrounds = closure_data.pop('campgrounds[]')
                self.close_campgrounds(closure_data, campgrounds)
                cache.delete('campgrounds_dt')
                return Response('All Selected Campgrounds Closed')
            except serializers.ValidationError:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))
            except Exception as e:
                print(traceback.print_exc())
                raise serializers.ValidationError(str(e[0]))

    @detail_route(methods=['post'], detail=True)
    def addPrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            rate = None
            serializer = RateDetailSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rate_id = serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=serializer.validated_data['adult'], concession=serializer.validated_data['concession'], child=serializer.validated_data['child'], infant=serializer.validated_data['infant'])[0]
            if rate:
                booking_policy_obj = models.BookingPolicy.objects.get(id=request.data['booking_policy'])
                serializer.validated_data['rate'] = rate
                data = {
                    'rate': rate,
                    'date_start': serializer.validated_data['period_start'],
                    'reason': PriceReason.objects.get(pk=serializer.validated_data['reason']),
                    'details': serializer.validated_data.get('details', None),
                    'booking_policy': booking_policy_obj,
                    'update_level': 0
                }
                self.get_object().createCampsitePriceHistory(data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.format_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.format_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['post'],detail=True)
    def updatePrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            original_data = request.data.pop('original')
            original_serializer = CampgroundPriceHistorySerializer(data=original_data, method='post')
            original_serializer.is_valid(raise_exception=True)

            serializer = RateDetailSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rate_id = serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=serializer.validated_data['adult'], concession=serializer.validated_data['concession'], child=serializer.validated_data['child'], infant=serializer.validated_data['infant'])[0]
            if rate:
                booking_policy_obj = models.BookingPolicy.objects.get(id=request.data['booking_policy'])
                serializer.validated_data['rate'] = rate
                new_data = {
                    'rate': rate,
                    'date_start': serializer.validated_data['period_start'],
                    'reason': PriceReason.objects.get(pk=serializer.validated_data['reason']),
                    'details': serializer.validated_data.get('details', None),
                    'booking_policy': booking_policy_obj,
                    'update_level': 0
                }
                self.get_object().updatePriceHistory(dict(original_serializer.validated_data), new_data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['post'], detail=True)
    def deletePrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            serializer = CampgroundPriceHistorySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            self.get_object().deletePriceHistory(serializer.validated_data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def status_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            # Check what status is required
            closures = bool(request.GET.get("closures", False))
            if closures:
                serializer = CampgroundBookingRangeSerializer(self.get_object().booking_ranges.filter(~Q(status=0)).order_by('-range_start'), many=True)
            else:
                serializer = CampgroundBookingRangeSerializer(self.get_object().booking_ranges, many=True)
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def campsites(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            serializer = CampsiteSerialiser(self.get_object().campsites, many=True, context={'request': request, 'status': None})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def price_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id).order_by('-date_start')
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def stay_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            start = request.GET.get("start", False)
            end = request.GET.get("end", False)
            serializer = None
            if (start) or (end):
                start = datetime.strptime(start, "%Y-%m-%d").date()
                end = datetime.strptime(end, "%Y-%m-%d").date()
                queryset = CampgroundStayHistory.objects.filter(range_end__range=(start, end), range_start__range=(start, end)).order_by("range_start")[:5]
                serializer = CampgroundStayHistorySerializer(queryset, many=True, context={'request': request}, method='get')
            else:
                serializer = CampgroundStayHistorySerializer(self.get_object().stay_history.all().order_by('-range_start'), many=True, context={'request': request}, method='get')
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    def try_parsing_date(self, text):
        for fmt in ('%Y/%m/%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        raise serializers.ValidationError('no valid date format found')

    @detail_route(methods=['get'], detail=True)
    def available_campsites(self, request, format='json', pk=None):
        try:
            start_date = self.try_parsing_date(request.GET.get('arrival')).date()
            end_date = self.try_parsing_date(request.GET.get('departure')).date()
            campsite_qs = Campsite.objects.filter(campground_id=self.get_object().id)
            http_status = status.HTTP_200_OK
            available = utils.get_available_campsites_list(campsite_qs, request, start_date, end_date)

            return Response(available, status=http_status)
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def available_campsites_booking(self, request, format='json', pk=None):
        try:
            start_date = self.try_parsing_date(request.GET.get('arrival')).date()
            end_date = self.try_parsing_date(request.GET.get('departure')).date()
            booking_id = request.GET.get('booking', None)
            if not booking_id:
                raise serializers.ValidationError('Booking has not been defined')
            try:
                booking = Booking.objects.get(id=booking_id)
            except BaseException:
                raise serializers.ValiadationError('The booking could not be retrieved')
            campsite_qs = Campsite.objects.filter(campground_id=self.get_object().id)
            http_status = status.HTTP_200_OK
            available = utils.get_available_campsites_list_booking(campsite_qs, request, start_date, end_date, booking)

            return Response(available, status=http_status)
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['get'], detail=True)
    def available_campsite_classes(self, request, format='json', pk=None):
        try:
            start_date = datetime.strptime(request.GET.get('arrival'), '%Y/%m/%d').date()
            end_date = datetime.strptime(request.GET.get('departure'), '%Y/%m/%d').date()
            http_status = status.HTTP_200_OK
            available = utils.get_available_campsitetypes(self.get_object().id, start_date, end_date, _list=False)
            available_serializers = []
            for k, v in available.items():
                s = CampsiteClassSerializer(CampsiteClass.objects.get(id=k), context={'request': request}, method='get').data
                s['campsites'] = [c_id for c_id, stat in v.items() if stat != 'closed & booked' and stat != 'booked' and stat != 'closed']
                counts = {'open': 0, 'closed': 0, 'booked': 0, 'closed & booked': 0}
                for c_id, stat in v.items():
                    counts[stat] += 1
                s['status'] = ', '.join(['{} {}'.format(stat, type) for type, stat in counts.items() if stat])
                available_serializers.append(s)
            available_serializers.sort(key=lambda x: x['name'])
            data = available_serializers

            return Response(data, status=http_status)
        except serializers.ValidationError:
            traceback.print_exc()
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            traceback.print_exc()
            raise serializers.ValidationError(str(e))


from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
  def default(self, obj):
    if isinstance(obj, Decimal):
      return str(obj)
    return json.JSONEncoder.default(self, obj)
#class BaseAvailabilityViewSet2(viewsets.ReadOnlyModelViewSet):
#    queryset = Campground.objects.all()
#    serializer_class = CampgroundSerializer

#def get_campground(campground_id):
#
#     cg_hash = {}
#     #ground = Campground.objects.filter(id=campground_id).values('id','name','park_id','ratis_id','contact_id','campground_type','promo_area','site_type','address','description','additional_info','area_activities','driving_directions','fees','othertransport','key','price_level','info_url','long_description','wkb_geometry','zoom_level','check_in','check_out','max_advance_booking','oracle_code','campground_map')
#     cached_data = cache.get('api.get_campground('+campground_id+')')
#     if cached_data is None: 
#         ground = Campground.objects.get(id=campground_id)
#         if ground:
#                cg_hash['id'] = ground.id
#                cg_hash['name'] = ground.name
#                cg_hash['campground_type'] = ground.campground_type
#                cg_hash['site_type'] = ground.site_type
#                cg_hash['long_description']  = ground.long_description
#                cg_hash['campground_map_url'] = ''
#                cg_hash['campground_map'] = ''
#
#                if ground.campground_map:
#                   cg_hash['campground_map_url'] = ground.campground_map.url
#                   cg_hash['campground_map'] = {'path': ground.campground_map.path}
#                cache.set('api.get_campground('+campground_id+')', json.dumps(cg_hash),  86400)
#     else:
#         cg_hash = json.loads(cached_data)
#     return cg_hash

def campground_availabilty_view(request,  *args, **kwargs):
    from pathlib import Path
    site_obj = {'campground': {}, 'campground_available': {}, 'available_cg': []}
    start_date_string = request.GET.get('arrival','2022/03/01')
    end_date_string = request.GET.get('departure','2022/04/07')
    if start_date_string == '' or end_date_string == '':
        return HttpResponse(json.dumps(site_obj), content_type='application/json')
    start_date = datetime.strptime(start_date_string, "%Y/%m/%d").date()
    end_date = datetime.strptime(end_date_string, "%Y/%m/%d").date()
    # one_eighty_days_active = False
    date_diff = end_date - start_date
    booking_days = date_diff.days # + 1
    past_180_days = False

    # crd_count = cache.get('CampgroundReleaseDateActiveCount')
    # if crd_count is None:    
    #     today = date.today()    
    #     crd_count = models.CampgroundReleaseDate.objects.filter(active=True, booking_open_date__lte=today).count()
    #     cache.set('CampgroundReleaseDateActiveCount', crd_count,  120)

    # if int(crd_count) == 0:
    #     today = date.today()
    #     rolling_180_days = today + timedelta(days=180)
    #     print ("CC")
    #     print (start_date)
    #     if start_date > rolling_180_days:
    #         past_180_days = True
            
        

        # astimezone(pytz.timezone('Australia/Perth'))
        # one_eighty_days_active = True

    #attributes_data_file = settings.BASE_DIR+"/datasets/campground-attributes.json"

    #try:
    #   f = open(attributes_data_file, "r")
    #   datajsonstring = f.read()
    #   attributes_obj = json.loads(datajsonstring)
    #except:
    #   fileopened = False
    #   attributes_obj = {}
    #   print ("Error in attributes json file")
    #
    #print (attributes_obj)

    HTTP_REFERER_VALID = False
    HTTP_REFERER = request.META.get('HTTP_REFERER', None)
    if HTTP_REFERER:
        for aru in settings.ACCEPTED_REFERER_URL:
            if HTTP_REFERER.startswith(aru):
                HTTP_REFERER_VALID  = True            
        if HTTP_REFERER_VALID is True:                
            pass
        else:
            messages.error(request, "A error occured accessing the system,  please try again")
            print ("HTTP_REFERER not allowed : "+ str(HTTP_REFERER))
            return HttpResponse(json.dumps(site_obj), content_type='application/json')     
    else:
        messages.error(request, "A error occured accessing the system,  please try again")
        print ("HTTP_REFERER not allowed : "+ str(HTTP_REFERER))
        return HttpResponse(json.dumps(site_obj), content_type='application/json')

    #available_campsites_obj = {}
    campgrounds = utils_cache.all_campgrounds()
    for c in campgrounds:
        site_obj['campground_available'][c['id']] = {}
        site_obj['campground_available'][c['id']]['sites'] = []

        if c['campground_type'] == 0:
           campsites = utils_cache.all_campground_campsites(c['id'])
           #campsite = Campsite.objects.filter(campground_id=c['id'])
           for cs in campsites:
               cs_id = cs['id']
               site_obj['campground_available'][c['id']]['sites'].append(cs_id)
           site_obj['campground_available'][c['id']]['total_available'] = len(site_obj['campground_available'][c['id']]['sites'])
           site_obj['campground_available'][c['id']]['total_bookable'] = len(site_obj['campground_available'][c['id']]['sites'])

    daily_calender = {}
    for day in range(0, booking_days):
        nextday = start_date + timedelta(days=day)
        nextday_string = nextday.strftime('%Y-%m-%d')
        #print (nextday_string)
        data_file = settings.BASE_DIR+"/datasets/daily/"+str(nextday_string)+"-availablity.json"
        fileopened = True
        if os.path.isfile(data_file):
             f = open(data_file, "r")
             datajsonstring = f.read()
             try:
                daily_calender = json.loads(datajsonstring)
             except:
                fileopened = False
                daily_calender = {}
                print ("Error in json file")
                pass
        else:
            fileopened = False
            daily_calender = {}
        if fileopened is False:
           for c in campgrounds:
               site_obj['campground_available'][c['id']]['sites'] = []
               site_obj['campground_available'][c['id']]['total_bookable'] = len(site_obj['campground_available'][c['id']]['sites'])

        for dc in daily_calender:
             campground_ids = list(daily_calender[dc].keys())
             

             for cid in campground_ids:
                #  campground_release_date = utils.get_release_date_for_campground(cid) 
                 campground_info = utils_cache.get_campground(cid) 
                 
                 campsite_ids = list(daily_calender[dc][cid].keys())
                 past_180_days = False                    
                 if campground_info["campground"]['release_date'] is None:
                    today = date.today()
                    rolling_180_days = today + timedelta(days=180)
                    if start_date > rolling_180_days:
                        past_180_days = True    
                                      
                 for csid in campsite_ids:
                    ## add feature properties check here: ##
                    #if cid in attributes_obj['campgrounds']:
                    #     if csid in attributes_obj['campgrounds'][cid]['campsites']:
                    #           pass
                    #
                    

                    if booking_days > 28:
                        site_obj['campground_available'][int(cid)]['sites'] = []
                        site_obj['campground_available'][int(cid)]['total_available'] = 0
                        site_obj['campground_available'][int(cid)]['total_bookable'] = 0                        

                    
                     ########################################
                    if past_180_days is True:                      
                        site_obj['campground_available'][int(cid)]['sites'] = []
                        site_obj['campground_available'][int(cid)]['total_available'] = 0
                        site_obj['campground_available'][int(cid)]['total_bookable'] = 0
                    else:                        
                        if daily_calender[dc][cid][csid][nextday_string] == 'available':
                            pass
                        else:
                            if int(csid) in site_obj['campground_available'][int(cid)]['sites']:
                                site_obj['campground_available'][int(cid)]['sites'].remove(int(csid))
                 site_obj['campground_available'][int(cid)]['total_bookable'] = len(site_obj['campground_available'][int(cid)]['sites'])

    for c in campgrounds:
        if c['campground_type'] == 0:
            if len(site_obj['campground_available'][c['id']]['sites']) > 0:
                site_obj['available_cg'].append({'id' : int(c['id'])})
        elif c['campground_type'] == 1:
            site_obj['available_cg'].append({'id': int(c['id'])})
        elif c['campground_type'] == 2:
            site_obj['available_cg'].append({'id' : int(c['id'])})

    return HttpResponse(json.dumps(site_obj), content_type='application/json')

def campground_availabilty_view2(request,  *args, **kwargs):
    from pathlib import Path
    site_obj = {'campground': {}, 'campground_available': []}
    start_date_string = request.GET.get('arrival','2022/03/01')
    end_date_string = request.GET.get('departure','2022/03/07')
    start_date = datetime.strptime(start_date_string, "%Y/%m/%d").date()
    end_date = datetime.strptime(end_date_string, "%Y/%m/%d").date()

    date_diff = end_date - start_date

    booking_days = date_diff.days + 1
   
    #campgrounds = Campground.objects.all_campgrounds()
    campgrounds = utils_cache.all_campgrounds()
    #filter(id=139)#[:20]
    for cg in campgrounds:
            cg_id = cg['id']
        #with open(settings.BASE_DIR+'/datasets/'+str(cg.id)+'-campground-availablity.json', 'r') as f:
            #data = f.read()
            data = Path(settings.BASE_DIR+'/datasets/'+str(cg_id)+'-campground-availablity.json').read_text()

            campground_calendar = json.loads(data)
            campsite_ids = campground_calendar['campsite_ids']
            site_obj['campground'][cg_id] = {}
            site_obj['campground'][cg_id]['total_sites'] = len(campsite_ids)
            site_obj['campground'][cg_id]['campsites_available'] = campsite_ids
            for day in range(0, booking_days):
                  nextday = start_date + timedelta(days=day)
                  nextday_string = nextday.strftime('%Y-%m-%d')
                  for cs in campsite_ids:
                      if 'campsites' in campground_calendar:
                           if str(cs) in campground_calendar['campsites']:
                                 if nextday_string in campground_calendar['campsites'][str(cs)]:
                                     if campground_calendar['campsites'][str(cs)][nextday_string] != 'available':
                                           if cs in site_obj['campground'][cg_id]['campsites_available']:
                                                site_obj['campground'][cg_id]['campsites_available'].remove(cs)

            site_obj['campground'][cg_id]['total_available'] = len(site_obj['campground'][cg_id]['campsites_available'])
            if site_obj['campground'][cg_id]['total_available'] > 0:
                site_obj['campground_available'].append({'id' :cg_id})
            del site_obj['campground'][cg_id]['campsites_available']
    return HttpResponse(json.dumps(site_obj), content_type='application/json')

def campsite_availablity_view(request,  *args, **kwargs):

    """Fetch full campsite availability for a campground."""
    # check if the user has an ongoing booking
    result = {}

    HTTP_REFERER_VALID = False
    HTTP_REFERER = request.META.get('HTTP_REFERER', None)
    if HTTP_REFERER:
        for aru in settings.ACCEPTED_REFERER_URL:
            print (aru)
            if HTTP_REFERER.startswith(aru):
                HTTP_REFERER_VALID  = True            
        if HTTP_REFERER_VALID is True:                
            pass
        else:
            messages.error(request, "A error occured accessing the system,  please try again")
            print ("HTTP_REFERER not allowed : "+ str(HTTP_REFERER))
            return HttpResponse(geojson.dumps(result,cls=DecimalEncoder), content_type='application/json', status=500)
               
    else:
        messages.error(request, "A error occured accessing the system,  please try again")
        print ("HTTP_REFERER not allowed : "+ str(HTTP_REFERER))
        return HttpResponse(geojson.dumps(result,cls=DecimalEncoder), content_type='application/json',status=500) 

    user_logged_in = None
    today = date.today()
    if request.user.is_authenticated:
           user_logged_in = request.user

    ongoing_booking = None
    if 'ps_booking' in request.session:
        if Booking.objects.filter(pk=request.session['ps_booking']).count() > 0:
            ongoing_booking = Booking.objects.get(pk=request.session['ps_booking']) if 'ps_booking' in request.session else None
        else:
            del request.session['ps_booking']
    
    campground_id = kwargs.get('campground_id', None)
    change_booking_id = request.GET.get('change_booking_id', None)

    # change booking data
    current_booking_campsite_id = None
    current_booking_campsite_class_id = None
    change_booking_qs = []
    if change_booking_id is not None:
        change_booking_qs = models.CampsiteBooking.objects.filter(booking_id=change_booking_id)
    for cb in change_booking_qs:
          current_booking_campsite_id = cb.campsite_id 
          if cb.campsite.campsite_class:
              current_booking_campsite_class_id = cb.campsite.campsite_class.id

    
    show_all = False
    # convert GET parameters to objects
    #ground = Campground.objects.get(id=campground_id)
    ground = booking_availability.get_campground(campground_id)
    # Validate parameters
    data = {
        "arrival": request.GET.get('arrival'),
        "departure": request.GET.get('departure'),
        "num_adult": request.GET.get('num_adult', 0),
        "num_concession": request.GET.get('num_concession', 0),
        "num_child": request.GET.get('num_child', 0),
        "num_infant": request.GET.get('num_infant', 0),
        "gear_type": request.GET.get('gear_type', 'all')
    }

    serializer = CampgroundCampsiteFilterSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    start_date = serializer.validated_data['arrival']
    end_date = serializer.validated_data['departure']
    num_adult = serializer.validated_data['num_adult']
    num_concession = serializer.validated_data['num_concession']
    num_child = serializer.validated_data['num_child']
    num_infant = serializer.validated_data['num_infant']
    gear_type = serializer.validated_data['gear_type']

    
    # get a length of the stay (in days), capped if necessary to the request maximum
    length = max(0, (end_date - start_date).days)

    if ground['campground_type'] != 0  and ground['campground_type'] != 1:
        return HttpResponse(geojson.dumps(
            {'error': 'Campground doesn\'t support online bookings'}
        ,cls=DecimalEncoder), content_type='application/json', status=400)

    # if campground doesn't support online bookings, abort!
    if ground['campground_type'] == 1:
        result = booking_availability.not_bookable_online(ongoing_booking,ground,start_date,end_date,num_adult,num_concession,num_child,num_infant,gear_type)
        return HttpResponse(geojson.dumps(
            result
        ,cls=DecimalEncoder), content_type='application/json')


    # fetch all the campsites and applicable rates for the campground
    context = {}
    #sites_qs = Campsite.objects.filter(campground=ground).filter(**context)
    sites_array = []
    sites_qs = booking_availability.get_campsites_for_campground(ground,gear_type)
    
    for s in sites_qs:
        sites_array.append({'pk': s['id'], 'data': s})
    
    # fetch rate map
    rates = {
        siteid: {
            date: num_adult * info['adult'] + num_concession * info['concession'] + num_child * info['child'] + num_infant * info['infant']
            for date, info in dates.items()
        } for siteid, dates in booking_availability.get_visit_rates(ground['id'],sites_array, start_date, end_date).items()
    }
   
    # fetch availability map
    availability = booking_availability.get_campsite_availability(ground['id'],sites_array, start_date, end_date, user_logged_in, change_booking_id)
    
    # create our result object, which will be returned as JSON
    result = {
        'id': ground['id'],
        'name': ground['name'],
        'site_type': ground['site_type'],
        'long_description': ground['long_description'],
        'map': ground['campground_map_url'] if ground['campground_map'] else None,
        'ongoing_booking': True if ongoing_booking else False,
        'ongoing_booking_id': ongoing_booking.id if ongoing_booking else None,
        'arrival': start_date.strftime('%Y/%m/%d'),
        'days': length,
        'adults': 1,
        'children': 0,
        'maxAdults': 30,
        'maxChildren': 30,
        'sites': [],
        'classes': {},
        'current_booking_campsite_id': current_booking_campsite_id,
        'current_booking_campsite_class_id': current_booking_campsite_class_id,
        'result' : True,
        'release_time_friendly' : ground['release_time_friendly'],
        'release_date' : ground['release_date'],
        'booking_open_date' : ground['booking_open_date']
        
    }


    # check if date if max advance booking date and after opentime
    stop = today + timedelta(days=ground['max_advance_booking'])  
    booking_time_open = True
    if start_date == stop:
        nowtime = datetime.now()
        nowdatetime_string = nowtime.strftime("%Y-%m-%d")
        campground_opentime = datetime.strptime(nowdatetime_string+' '+ground["release_time"], '%Y-%m-%d %H:%M:%S')
        
        if nowtime >= campground_opentime:
            booking_time_open = True
        else:
            booking_time_open = False
 
    result['booking_time_open'] = booking_time_open

    # group results by campsite class
    if ground['site_type'] in (1, 2):
        
        # from our campsite queryset, generate a distinct list of campsite classes
        classes = []
        classes_added =[]
        for x in sites_qs:
            if x['campsite_class_id'] in classes_added:
                pass
            else:
                classes.append({'pk': x['id'], 'campsite_class_id': x['campsite_class_id'], 'campsite_class__name': x['campsite_class__name'], 'tent': x['tent'] , 'campervan': x['campervan'], 'caravan': x['caravan'], 'features': x['features'], 'short_description': x['short_description'], 'min_people': x['min_people'], 'max_people': x['max_people'], 'max_vehicles': x['max_vehicles']})
                classes_added.append(x['campsite_class_id'])
        #classes = [x for x in sites_qs.distinct('campsite_class__name').order_by('campsite_class__name').values_list('pk', 'campsite_class', 'campsite_class__name', 'tent', 'campervan', 'caravan')]
        classes_map = {}
        bookings_map = {}

        # create a rough mapping of rates to campsite classes
        # (it doesn't matter if this isn't a perfect match, the correct
        # pricing will show up on the booking page)
        rates_map = {}

        class_sites_map = {}
        for s in sites_qs:
            if s['campsite_class_id'] not in class_sites_map:
                class_sites_map[s['campsite_class_id']] = set()
                rates_map[s['campsite_class_id']] = rates[s['id']]

            class_sites_map[s['campsite_class_id']].add(s['id'])

        # make an entry under sites for each campsite class
        for c in classes:
            rate = rates_map[c['campsite_class_id']]
            site = {
                'name': c['campsite_class__name'],
                'id': c['pk'],
                'type': c['campsite_class_id'],
                'price': '${}'.format(sum(rate.values())) if not show_all else False,
                'availability': [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], None, [0, 0, 0],(start_date + timedelta(days=i)).strftime('%Y-%m-%d')] for i in range(length)],
                'breakdown': OrderedDict(),
                'gearType': {
                    'tent': c['tent'],
                    'campervan': c['campervan'],
                    'caravan': c['caravan']
                },
                'features': c['features'],
                'min_people': c['min_people'],
                'max_people': c['max_people'],
                'max_vehicles': c['max_vehicles'],
                'description': x['description'],
                'short_description': c['short_description']
            }
            result['sites'].append(site)
            classes_map[c['campsite_class_id']] = site

        # make a map of class IDs to site IDs
        for s in sites_qs:
            rate = rates_map[s['campsite_class_id']]
            classes_map[s['campsite_class_id']]['breakdown'][s['name']] = [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], None] for i in range(length)]
        # store number of campsites in each class
        class_sizes = {k: len(v) for k, v in class_sites_map.items()}

        for s in sites_qs:
            # get campsite class key
            key = s['campsite_class_id']
            # if there's not a free run of slots
            if (not all([v[0] == 'open' for k, v in availability[s['id']].items()])) or show_all:
                # clear the campsite from the campsite class map
                if s['id'] in class_sites_map[key]:
                    class_sites_map[key].remove(s['id'])

                # update the days that are non-open
                for offset, stat, closure_reason in [((k - start_date).days, v[0], v[1]) for k, v in availability[s['id']].items() if v[0] != 'open']:
                    # update the per-site availability

                    classes_map[key]['breakdown'][s['name']][offset][0] = False
                    classes_map[key]['breakdown'][s['name']][offset][1] = stat if show_all else 'Unavailable'
                    classes_map[key]['breakdown'][s['name']][offset][3] = closure_reason if show_all else None

                    # update the class availability status
                    if stat == 'booked':
                        book_offset = 0
                    elif stat == 'closed':
                        book_offset = 1
                    else:
                        book_offset = 2

                    classes_map[key]['availability'][offset][4][book_offset] += 1
                    # if the number of booked entries equals the size of the class, it's fully booked
                    if classes_map[key]['availability'][offset][4][0] == class_sizes[key]:
                        classes_map[key]['availability'][offset][1] = 'Booked'
                    # if the number of closed entries equals the size of the class, it's closed (admin) or unavailable (user)
                    elif classes_map[key]['availability'][offset][4][1] == class_sizes[key]:
                        classes_map[key]['availability'][offset][1] = 'Closed' if show_all else 'Unavailable'
                        classes_map[key]['availability'][offset][3] = closure_reason if show_all else None
                    elif classes_map[key]['availability'][offset][4][2] == class_sizes[key]:
                        classes_map[key]['availability'][offset][1] = 'Closures/Bookings' if show_all else 'Unavailable'
                        classes_map[key]['availability'][offset][3] = closure_reason if show_all else None
                    # if all of the entries are closed, it's unavailable (user)
                    elif not show_all and (classes_map[key]['availability'][offset][4][0] + classes_map[key]['availability'][offset][4][1] == class_sizes[key]):
                        classes_map[key]['availability'][offset][1] = 'Unavailable'
                    # for admin view, we show some text even if there are slots available.
                    elif show_all:
                        # check if there are any booked or closed entries and change the message accordingly
                        test_bk = classes_map[key]['availability'][offset][4][0] > 0
                        test_cl = classes_map[key]['availability'][offset][4][1] > 0
                        test_clbk = classes_map[key]['availability'][offset][4][2] > 0
                        if test_clbk or (test_bk and test_cl):
                            classes_map[key]['availability'][offset][1] = 'Closures/Bookings'
                            if classes_map[key]['availability'][offset][3] is None:
                                classes_map[key]['availability'][offset][3] = closure_reason
                        elif test_bk:
                            classes_map[key]['availability'][offset][1] = 'Some Booked'
                        elif test_cl:
                            classes_map[key]['availability'][offset][1] = 'Some Closed'
                            if classes_map[key]['availability'][offset][3] is None:
                                classes_map[key]['availability'][offset][3] = closure_reason
                        elif test_clbk:
                            classes_map[key]['availability'][offset][1] = 'Closures/Bookings'
                            if classes_map[key]['availability'][offset][3] is None:
                                classes_map[key]['availability'][offset][3] = closure_reason

                    # tentatively flag campsite class as unavailable
                    classes_map[key]['availability'][offset][0] = False
                    classes_map[key]['price'] = False

        # convert breakdowns to a flat list
        for klass in classes_map.values():
            klass['breakdown'] = [{'name': k, 'availability': v} for k, v in klass['breakdown'].items()]

        # any campsites remaining in the class sites map have zero bookings!
        # check if there's any left for each class, and if so return that as the target
        for k, v in class_sites_map.items():
            if v:
                rate = rates_map[k]
                # if the number of sites is less than the warning limit, add a notification
                if len(v) <= settings.PS_CAMPSITE_COUNT_WARNING:
                    classes_map[k].update({
                        'warning': 'Only {} left!'.format(len(v))
                    })

                classes_map[k].update({
                    'site_left': str(len(v))
                })



                classes_map[k].update({
                    'id': v.pop(),
                    'price': '${}'.format(sum(rate.values())),
                    'availability': [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], [0, 0],None,(start_date + timedelta(days=i)).strftime('%Y-%m-%d')] for i in range(length)],
                    'breakdown': []
                })


        return HttpResponse(geojson.dumps( result ,cls=DecimalEncoder), content_type='application/json')


        #return Response(result)

    # don't group by class, list individual sites
    else:
        #sites_qs = sites_qs.order_by('name')

        # from our campsite queryset, generate a digest for each site
        sites_map = OrderedDict([(s['name'], (s['id'], s['campsite_class_id'], rates[s['id']], s['tent'], s['campervan'], s['caravan'])) for s in sites_qs])
        bookings_map = {}
        print ("SITES NOW")
        # make an entry under sites for each site
        #for k, v in sites_map.items():
        for si in sites_qs:
            site = {
                'name': si['name'],
                'id': si['id'],
                'type': ground['campground_type'],
                'class': si['campsite_class_id'],
                'price': '${}'.format(sum(rates[si['id']].values())) if not show_all else False,
                'availability': [[True, '${}'.format(rates[si['id']][start_date + timedelta(days=i)]), rates[si['id']][start_date + timedelta(days=i)], None,None,(start_date + timedelta(days=i)).strftime('%Y-%m-%d')] for i in range(length)],
                'gearType': {
                    'tent': si['tent'],
                    'campervan': si['campervan'],
                    'caravan': si['caravan'],
                    'vehicle': si['vehicle'],
                    'motorcycle': si['motorcycle'],
                    'trailer' : si['trailer']
                },
                'features': si['features'],
                'min_people': si['min_people'],
                'max_people': si['max_people'],
                'max_vehicles': si['max_vehicles'],
                'description': si['description'],
                'short_description': si['short_description'],
                
            }
            result['sites'].append(site)
            bookings_map[si['name']] = site
            if si['campsite_class_id'] not in result['classes']:
                result['classes'][si['campsite_class_id']] = si['campsite_class__name'] 

        # update results based on availability map
        for s in sites_qs:
            # if there's not a free run of slots
            if (not all([v[0] == 'open' for k, v in availability[s['id']].items()])) or show_all:
                # update the days that are non-open
                for offset, stat, closure_reason in [((k - start_date).days, v[0], v[1]) for k, v in availability[s['id']].items() if v[0] != 'open']:
                    bookings_map[s['name']]['availability'][offset][0] = False
                    if stat == 'closed':
                        bookings_map[s['name']]['availability'][offset][1] = 'Closed' if show_all else 'Unavailable'
                        bookings_map[s['name']]['availability'][offset][3] = closure_reason if show_all else None
                    elif stat == 'closed & booked':
                        bookings_map[s['name']]['availability'][offset][1] = 'Closed & Booked' if show_all else 'Unavailable'
                        bookings_map[s['name']]['availability'][offset][3] = closure_reason if show_all else None
                    elif stat == 'booked':
                        bookings_map[s['name']]['availability'][offset][1] = 'Booked' if show_all else 'Unavailable'
                    else:
                        bookings_map[s['name']]['availability'][offset][1] = 'Unavailable'

                    bookings_map[s['name']]['price'] = False
        return HttpResponse(geojson.dumps(
            result 
        ,cls=DecimalEncoder), content_type='application/json')


        #return Response(result)


class BaseAvailabilityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Campground.objects.all()
    serializer_class = CampgroundSerializer

    def retrieve(self, request, pk=None, ratis_id=None, format=None, show_all=False):
        """Fetch full campsite availability for a campground."""
        # convert GET parameters to objects
        ground = self.get_object()
        print (ground.site_type)
        # check if the user has an ongoing booking
        ongoing_booking = Booking.objects.get(pk=request.session['ps_booking']) if 'ps_booking' in request.session else None
        # Validate parameters
        data = {
            "arrival": request.GET.get('arrival'),
            "departure": request.GET.get('departure'),
            "num_adult": request.GET.get('num_adult', 0),
            "num_concession": request.GET.get('num_concession', 0),
            "num_child": request.GET.get('num_child', 0),
            "num_infant": request.GET.get('num_infant', 0),
            "gear_type": request.GET.get('gear_type', 'all')
        }
        serializer = CampgroundCampsiteFilterSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        start_date = serializer.validated_data['arrival']
        end_date = serializer.validated_data['departure']
        num_adult = serializer.validated_data['num_adult']
        num_concession = serializer.validated_data['num_concession']
        num_child = serializer.validated_data['num_child']
        num_infant = serializer.validated_data['num_infant']
        gear_type = serializer.validated_data['gear_type']

        # get a length of the stay (in days), capped if necessary to the request maximum
        length = max(0, (end_date - start_date).days)

        # if campground doesn't support online bookings, abort!
        if ground.campground_type == 1:
            context = {}
            if gear_type != 'all':
                context[gear_type] = True
            sites_qs = Campsite.objects.filter(campground=ground).filter(**context)

            rates = {
                siteid: {
                    date: num_adult * info['adult'] + num_concession * info['concession'] + num_child * info[
                        'child'] + num_infant * info['infant']
                    for date, info in dates.items()
                } for siteid, dates in utils.get_visit_rates(sites_qs, start_date, end_date).items()
            }

            availability = utils.get_campsite_availability(sites_qs, start_date, end_date)

            # Added campground_type to enable offline booking more info in frontend
            result = {
                'id': ground.id,
                'name': ground.name,
                'long_description': ground.long_description,

                'campground_type': ground.campground_type,

                'map': ground.campground_map.url if ground.campground_map else None,
                'ongoing_booking': True if ongoing_booking else False,
                'ongoing_booking_id': ongoing_booking.id if ongoing_booking else None,
                'arrival': start_date.strftime('%Y/%m/%d'),
                'days': length,
                'adults': 1,
                'children': 0,
                'maxAdults': 30,
                'maxChildren': 30,
                 'sites': [],
                 'classes': {},

            }

            return Response(result)

        if ground.campground_type != 0  and ground.campground_type != 1:
            return Response({'error': 'Campground doesn\'t support online bookings'}, status=400)

        # # get a length of the stay (in days), capped if necessary to the request maximum
        # length = max(0, (end_date - start_date).days)

        # fetch all the campsites and applicable rates for the campground
        context = {}
        if gear_type != 'all':
            context[gear_type] = True
        sites_qs = Campsite.objects.filter(campground=ground).filter(**context)

        # fetch rate map
        rates = {
            siteid: {
                date: num_adult * info['adult'] + num_concession * info['concession'] + num_child * info['child'] + num_infant * info['infant']
                for date, info in dates.items()
            } for siteid, dates in utils.get_visit_rates(sites_qs, start_date, end_date).items()
        }

        # fetch availability map
        availability = utils.get_campsite_availability(sites_qs, start_date, end_date)

        # create our result object, which will be returned as JSON
        result = {
            'id': ground.id,
            'name': ground.name,
            'long_description': ground.long_description,
            'map': ground.campground_map.url if ground.campground_map else None,
            'ongoing_booking': True if ongoing_booking else False,
            'ongoing_booking_id': ongoing_booking.id if ongoing_booking else None,
            'arrival': start_date.strftime('%Y/%m/%d'),
            'days': length,
            'adults': 1,
            'children': 0,
            'maxAdults': 30,
            'maxChildren': 30,
            'sites': [],
            'classes': {},
        }

        # group results by campsite class
        if ground.site_type in (1, 2):
            # from our campsite queryset, generate a distinct list of campsite classes
            classes = [x for x in sites_qs.distinct('campsite_class__name').order_by('campsite_class__name').values_list('pk', 'campsite_class', 'campsite_class__name', 'tent', 'campervan', 'caravan')]
            classes_map = {}
            bookings_map = {}

            # create a rough mapping of rates to campsite classes
            # (it doesn't matter if this isn't a perfect match, the correct
            # pricing will show up on the booking page)
            rates_map = {}

            class_sites_map = {}
            for s in sites_qs:
                if s.campsite_class.pk not in class_sites_map:
                    class_sites_map[s.campsite_class.pk] = set()
                    rates_map[s.campsite_class.pk] = rates[s.pk]

                class_sites_map[s.campsite_class.pk].add(s.pk)
            print ("OLD CLASS")
            # make an entry under sites for each campsite class
            for c in classes:
                print (c)
                rate = rates_map[c[1]]
                site = {
                    'name': c[2],
                    'id': None,
                    'type': c[1],
                    'price': '${}'.format(sum(rate.values())) if not show_all else False,
                    'availability': [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], None, [0, 0, 0]] for i in range(length)],
                    'breakdown': OrderedDict(),
                    'gearType': {
                        'tent': c[3],
                        'campervan': c[4],
                        'caravan': c[5]
                    }
                }
                result['sites'].append(site)
                classes_map[c[1]] = site

            # make a map of class IDs to site IDs
            for s in sites_qs:
                rate = rates_map[s.campsite_class.pk]
                classes_map[s.campsite_class.pk]['breakdown'][s.name] = [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], None] for i in range(length)]
            # store number of campsites in each class
            class_sizes = {k: len(v) for k, v in class_sites_map.items()}

            # update results based on availability map
            for s in sites_qs:
                # get campsite class key
                key = s.campsite_class.pk
                # if there's not a free run of slots
                if (not all([v[0] == 'open' for k, v in availability[s.pk].items()])) or show_all:
                    # clear the campsite from the campsite class map
                    if s.pk in class_sites_map[key]:
                        class_sites_map[key].remove(s.pk)

                    # update the days that are non-open
                    for offset, stat, closure_reason in [((k - start_date).days, v[0], v[1]) for k, v in availability[s.pk].items() if v[0] != 'open']:
                        # update the per-site availability
                        classes_map[key]['breakdown'][s.name][offset][0] = False
                        classes_map[key]['breakdown'][s.name][offset][1] = stat if show_all else 'Unavailable'
                        classes_map[key]['breakdown'][s.name][offset][3] = closure_reason if show_all else None

                        # update the class availability status
                        if stat == 'booked':
                            book_offset = 0
                        elif stat == 'closed':
                            book_offset = 1
                        else:
                            book_offset = 2

                        classes_map[key]['availability'][offset][4][book_offset] += 1
                        # if the number of booked entries equals the size of the class, it's fully booked
                        if classes_map[key]['availability'][offset][4][0] == class_sizes[key]:
                            classes_map[key]['availability'][offset][1] = 'Booked'
                        # if the number of closed entries equals the size of the class, it's closed (admin) or unavailable (user)
                        elif classes_map[key]['availability'][offset][4][1] == class_sizes[key]:
                            classes_map[key]['availability'][offset][1] = 'Closed' if show_all else 'Unavailable'
                            classes_map[key]['availability'][offset][3] = closure_reason if show_all else None
                        elif classes_map[key]['availability'][offset][4][2] == class_sizes[key]:
                            classes_map[key]['availability'][offset][1] = 'Closures/Bookings' if show_all else 'Unavailable'
                            classes_map[key]['availability'][offset][3] = closure_reason if show_all else None
                        # if all of the entries are closed, it's unavailable (user)
                        elif not show_all and (classes_map[key]['availability'][offset][4][0] + classes_map[key]['availability'][offset][4][1] == class_sizes[key]):
                            classes_map[key]['availability'][offset][1] = 'Unavailable'
                        # for admin view, we show some text even if there are slots available.
                        elif show_all:
                            # check if there are any booked or closed entries and change the message accordingly
                            test_bk = classes_map[key]['availability'][offset][4][0] > 0
                            test_cl = classes_map[key]['availability'][offset][4][1] > 0
                            test_clbk = classes_map[key]['availability'][offset][4][2] > 0
                            if test_clbk or (test_bk and test_cl):
                                classes_map[key]['availability'][offset][1] = 'Closures/Bookings'
                                if classes_map[key]['availability'][offset][3] is None:
                                    classes_map[key]['availability'][offset][3] = closure_reason
                            elif test_bk:
                                classes_map[key]['availability'][offset][1] = 'Some Booked'
                            elif test_cl:
                                classes_map[key]['availability'][offset][1] = 'Some Closed'
                                if classes_map[key]['availability'][offset][3] is None:
                                    classes_map[key]['availability'][offset][3] = closure_reason
                            elif test_clbk:
                                classes_map[key]['availability'][offset][1] = 'Closures/Bookings'
                                if classes_map[key]['availability'][offset][3] is None:
                                    classes_map[key]['availability'][offset][3] = closure_reason

                        # tentatively flag campsite class as unavailable
                        classes_map[key]['availability'][offset][0] = False
                        classes_map[key]['price'] = False

            # convert breakdowns to a flat list
            for klass in classes_map.values():
                klass['breakdown'] = [{'name': k, 'availability': v} for k, v in klass['breakdown'].items()]

            # any campsites remaining in the class sites map have zero bookings!
            # check if there's any left for each class, and if so return that as the target
            for k, v in class_sites_map.items():
                if v:
                    rate = rates_map[k]
                    # if the number of sites is less than the warning limit, add a notification
                    if len(v) <= settings.PS_CAMPSITE_COUNT_WARNING:
                        classes_map[k].update({
                            'warning': 'Only {} left!'.format(len(v))
                        })

                    classes_map[k].update({
                        'id': v.pop(),
                        'price': '${}'.format(sum(rate.values())),
                        'availability': [[True, '${}'.format(rate[start_date + timedelta(days=i)]), rate[start_date + timedelta(days=i)], [0, 0]] for i in range(length)],
                        'breakdown': []
                    })

            return Response(result)

        # don't group by class, list individual sites
        else:
            sites_qs = sites_qs.order_by('name')

            # from our campsite queryset, generate a digest for each site
            sites_map = OrderedDict([(s.name, (s.pk, s.campsite_class, rates[s.pk], s.tent, s.campervan, s.caravan)) for s in sites_qs])
            bookings_map = {}

            # make an entry under sites for each site
            for k, v in sites_map.items():
                site = {
                    'name': k,
                    'id': v[0],
                    'type': ground.campground_type,
                    'class': v[1].pk,
                    'price': '${}'.format(sum(v[2].values())) if not show_all else False,
                    'availability': [[True, '${}'.format(v[2][start_date + timedelta(days=i)]), v[2][start_date + timedelta(days=i)], None] for i in range(length)],
                    'gearType': {
                        'tent': v[3],
                        'campervan': v[4],
                        'caravan': v[5]
                    }
                }
                result['sites'].append(site)
                bookings_map[k] = site
                if v[1].pk not in result['classes']:
                    result['classes'][v[1].pk] = v[1].name

            # update results based on availability map
            for s in sites_qs:
                # if there's not a free run of slots
                if (not all([v[0] == 'open' for k, v in availability[s.pk].items()])) or show_all:
                    # update the days that are non-open
                    for offset, stat, closure_reason in [((k - start_date).days, v[0], v[1]) for k, v in availability[s.pk].items() if v[0] != 'open']:
                        bookings_map[s.name]['availability'][offset][0] = False
                        if stat == 'closed':
                            bookings_map[s.name]['availability'][offset][1] = 'Closed' if show_all else 'Unavailable'
                            bookings_map[s.name]['availability'][offset][3] = closure_reason if show_all else None
                        elif stat == 'closed & booked':
                            bookings_map[s.name]['availability'][offset][1] = 'Closed & Booked' if show_all else 'Unavailable'
                            bookings_map[s.name]['availability'][offset][3] = closure_reason if show_all else None
                        elif stat == 'booked':
                            bookings_map[s.name]['availability'][offset][1] = 'Booked' if show_all else 'Unavailable'
                        else:
                            bookings_map[s.name]['availability'][offset][1] = 'Unavailable'

                        bookings_map[s.name]['price'] = False

            return Response(result)


class AvailabilityViewSet(BaseAvailabilityViewSet):
    permission_classes = []


class AvailabilityRatisViewSet(BaseAvailabilityViewSet):
    permission_classes = []
    lookup_field = 'ratis_id'


class AvailabilityAdminViewSet(BaseAvailabilityViewSet):
    permission_classes = [OfficerPermission]

    def retrieve(self, request, *args, **kwargs):
        return super(AvailabilityAdminViewSet, self).retrieve(request, *args, show_all=True, **kwargs)


def refund_transaction_callback(invoice_ref,bpoint_tid):
      print ('refund call back '+invoice_ref)
      bi = BookingInvoice.objects.filter(invoice_reference=invoice_ref) 
      for i in bi:
         i.booking.save()
     
def invoice_callback(invoice_ref):
      print ('invoice call back '+invoice_ref)
      bi = BookingInvoice.objects.filter(invoice_reference=invoice_ref)
      for i in bi:
         i.booking.save()

def peak_periods(request, *args, **kwargs):
    #pg =parkstay_models.PeakGroup.objects.get(id=25)
    #parkstay_models.PeakPeriod.objects.create(start_date='2022-01-01', end_date='2022-01-30', active=True,peak_group=pg)

    if request.user.is_authenticated:
         if request.user.is_staff is True:
               peakgroup_id = request.GET.get('peakgroup_id',None)
               item_list = []
               item_obj = parkstay_models.PeakPeriod.objects.filter(peak_group_id=peakgroup_id).order_by('start_date')
               for i in item_obj:
                   item_list.append({'id': i.id, 'start_date': i.start_date.strftime("%d/%m/%Y"),'end_date': i.end_date.strftime("%d/%m/%Y"), 'active': i.active, 'created' : i.created.strftime("%d/%m/%Y, %H:%M:%S")})
               dumped_data = json.dumps(item_list)
         else:
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}
                  dumped_data = json.dumps(res)
    else:
         status = 501
         res = {"status": status, "message" : "Unauthorised"}
         dumped_data = json.dumps(res)
    return HttpResponse(dumped_data, content_type='application/json')


def save_peak_period(request,*args, **kwargs):
    status = 503
    try:

         if request.user.is_authenticated:
             if request.user.is_staff is True:
                  data = json.load(request)
                  payload = data.get('payload')
                  action = payload['action']
                  period_id = payload['period_id']
                  peakgroup_id =  payload['peakgroup_id']
                  start_date = payload['start_date']
                  end_date = payload['end_date']
                  active = payload['active'] 
                  period_status_boolean = False
                  if action == 'delete':
                     start_date_dt = ''
                     end_date_dt = ''
                  else:
                     start_date_dt = datetime.strptime(start_date, '%d/%m/%Y').date()
                     end_date_dt = datetime.strptime(end_date, '%d/%m/%Y').date()

                  if active == 'true':
                      period_status_boolean = True
                  
                  PeakPeriod=None
                  peakgroup = parkstay_models.PeakGroup.objects.get(id=int(peakgroup_id))
                  if action == 'save': 
                      PeakPeriod = parkstay_models.PeakPeriod.objects.get(id=int(period_id))
                      start_date_conflict = parkstay_models.PeakPeriod.objects.filter(peak_group=peakgroup,start_date__lte=start_date_dt, end_date__gte=start_date_dt).exclude(id=int(period_id)).count()
                      end_date_conflict = parkstay_models.PeakPeriod.objects.filter(peak_group=peakgroup,start_date__gte=end_date_dt, end_date__lte=end_date_dt).exclude(id=int(period_id)).count()
                  elif action == 'delete':
                      parkstay_models.PeakPeriod.objects.filter(id=int(period_id)).delete()
                      start_date_conflict = 0
                      end_date_conflict = 0
                  else:
                      start_date_conflict = parkstay_models.PeakPeriod.objects.filter(peak_group=peakgroup,start_date__lte=start_date_dt, end_date__gte=start_date_dt).count()
                      end_date_conflict = parkstay_models.PeakPeriod.objects.filter(peak_group=peakgroup,start_date__gte=end_date_dt, end_date__lte=end_date_dt).count()

                  if start_date_dt > end_date_dt:
                       raise ValidationError("Start date is greater than end date.")

                  if start_date_conflict > 0 and end_date_conflict > 0:
                        raise ValidationError("Both start and end date conflict with another date range")
 
                  if start_date_conflict > 0:
                        raise ValidationError("Start date conflict with another date range")
        
                  if end_date_conflict > 0:
                        raise ValidationError("End date conflict with another date range")

                  if action == 'create':
                     peakgroup = parkstay_models.PeakGroup.objects.get(id=int(peakgroup_id))
                     PeakPeriod = parkstay_models.PeakPeriod.objects.create(peak_group=peakgroup, start_date=start_date_dt,end_date=end_date_dt,active=period_status_boolean)


                  if action == 'save':
                     PeakPeriod.start_date = start_date_dt 
                     PeakPeriod.end_date = end_date_dt
                     PeakPeriod.active = period_status_boolean
                     PeakPeriod.save()

                  status = 200
                  res = {"status": status, "message" : "Success"}
             else:        
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}

         else:
              status = 501
              res = {"status": status, "message" : "Unauthorised"}
    except Exception as e:
         status = 503
         res = {
                "status": status, "message": str(e)
         }

    return HttpResponse(json.dumps(res), content_type='application/json', status=status)

def peak_groups(request, *args, **kwargs):

    if request.user.is_authenticated:
         if request.user.is_staff is True:
              dumped_data = cache.get('PeakPeriodGroups')
              if dumped_data is None:
                  item_list = []
                  item_obj = parkstay_models.PeakGroup.objects.all().order_by('id')
                  for i in item_obj:
                      item_list.append({'id': i.id, 'name': i.name,'active': i.active})

                  dumped_data = geojson.dumps(item_list)
                  cache.set('PeakPeriodGroups', dumped_data,  3600)
         else:
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}
                  dumped_data = json.dumps(res)
    else:
         status = 501
         res = {"status": status, "message" : "Unauthorised"}
         dumped_data = json.dumps(res)

    return HttpResponse(dumped_data, content_type='application/json')


def save_peak_group(request,*args, **kwargs):
    #print (request.POST)
    #print (request.POST.get('group_name',None))
    #import time
    #time.sleep(2.4)
    status = 503

    try:
         if request.user.is_authenticated:
             if request.user.is_staff is True:
                   data = json.load(request)
                   payload = data.get('payload')
                   action = payload['action']
                   group_id = None

                   if action == 'save' or action == 'delete':
                        group_id = payload['group_id']
                       
                   group_name = payload['group_name']
                   peak_status = payload['peak_status']
                   peak_status_boolean = False

                   if peak_status == 'true':
                       peak_status_boolean = True

                   if action == 'save':
                        pg = parkstay_models.PeakGroup.objects.get(id=int(group_id))
                        pg.name=group_name
                        pg.active=peak_status_boolean
                        pg.save()
                   elif action == 'delete':
                        parkstay_models.PeakGroup.objects.filter(id=int(group_id)).delete()
                        cache.delete('PeakPeriodGroups')
                   else: 
                        parkstay_models.PeakGroup.objects.create(name=group_name,active=peak_status_boolean)
                   status = 200
                   res = {"status": status, "message" : "Success"}

             else:
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}
         else:
              status = 501
              res = {"status": status, "message" : "Unauthorised"}


    except Exception as e:
         status = 503
         res = {
                "status": status, "message": str(e)
         }

    return HttpResponse(json.dumps(res), content_type='application/json', status=status)


def bulk_refund(request, *args, **kwargs):

    if request.user.is_authenticated:
         if request.user.is_staff is True:
            parkstay_officers = ledger_api_utils.user_in_system_group(request.session['user_obj']['user_id'],'Parkstay Officers')        
        
            if (request.user.is_staff and parkstay_officers) or request.user.is_superuser:             
                dumped_data = cache.get('BulkRefundCancel')
                dumped_data = None
                if dumped_data is None:
                    item_list = []
                    item_obj = parkstay_models.BulkRefundCancel.objects.all().order_by('-id')
                    for i in item_obj:
                        item_list.append({'id': i.id, 'bulk_name': i.bulk_name,'bulk_status': i.bulk_status,'paused': i.paused, 'created_by': i.created_by, 'created': i.created.strftime("%d/%m/%Y, %H:%M:%S")})                      

                    dumped_data = geojson.dumps(item_list)
                    cache.set('BulkRefundCancel', dumped_data,  3600)
         else:
                status = 501
                res = {"status": status, "message" : "Unauthorised"}
                dumped_data = json.dumps(res)
    else:
         status = 501
         res = {"status": status, "message" : "Unauthorised"}
         dumped_data = json.dumps(res)

    return HttpResponse(dumped_data, content_type='application/json')

def save_bulk_refund_period(request,*args, **kwargs):
    #print (request.POST)
    #print (request.POST.get('group_name',None))
    #import time
    #time.sleep(2.4)
    status = 503

    try:
            if request.user.is_authenticated:
                if request.user.is_staff is True:
                    data = json.load(request)
                    payload = data.get('payload')
                    action = payload['action']
                    group_id = None

                    if action == 'save' or action == 'delete':
                        group_id = payload['group_id']
                        
                    bulk_id = payload['bulk_id']
                    bulk_name = payload['bulk_name']
                    bulk_refund_cancel_list = payload['bulk_refund_cancel_list']
                    cancel_booking = payload['cancel_booking']
                    email_for_booking = payload['email_for_booking']
                    refund_type= payload['refund_type']
                    
                #    peak_status_boolean = False

                #    if peak_status == 'true':
                #        peak_status_boolean = True

                #    if action == 'save':
                #         pg = parkstay_models.PeakGroup.objects.get(id=int(group_id))
                #         pg.name=group_name
                #         pg.active=peak_status_boolean
                #         pg.save()
                #    elif action == 'delete':
                #         parkstay_models.PeakGroup.objects.filter(id=int(group_id)).delete()
                #         cache.delete('PeakPeriodGroups')
                #    else: 
                    bulk_obj = parkstay_models.BulkRefundCancel.objects.create(bulk_name=bulk_name,bulk_status=0, created_by=request.user.id)
                    bulk_refund_cancel_list_array = bulk_refund_cancel_list.splitlines()
                    for brc in bulk_refund_cancel_list_array:
                        print (brc)
                        print (len(brc))
                        if len(brc) > 1:
                            parkstay_models.BulkRefundCancelList.objects.create(bulk_refund_cancel=bulk_obj,
                                                                booking_reference=brc,
                                                                refund_type=refund_type,
                                                                cancel_type=cancel_booking,
                                                                email_type=email_for_booking
                                                                )


                        


                    status = 200
                    res = {"status": status, "message" : "Success"}

                else:
                    status = 501
                    res = {"status": status, "message" : "Unauthorised"}
            else:
                status = 501
                res = {"status": status, "message" : "Unauthorised"}


    except Exception as e:
         status = 503
         res = {
                "status": status, "message": str(e)
         }

    return HttpResponse(json.dumps(res), content_type='application/json', status=status)
    
def booking_policy(request, *args, **kwargs):
    #parkstay_models.BookingPolicy.objects.create(policy_name='Test 3',policy_type=1, amount='0.00', peak_group_id=25)
    if request.user.is_authenticated:
         if request.user.is_staff is True:
              dumped_data = cache.get('BookingPolicy')
              if dumped_data is None:
                  bpo_array = []
                  for bpo in parkstay_models.BookingPolicy.BOOKING_POLICY:
                      bpo_list = list(bpo)
                      bpo_array.append({"id": bpo_list[0], "name": bpo_list[1]})
                  item_options = {'policy_types': bpo_array, 'dataitems': []} 
                  item_list = []

                  item_obj = parkstay_models.BookingPolicy.objects.all().order_by('id')
                  for i in item_obj:
                      peak_group_id = None
                      if i.peak_group:
                          peak_group_id = i.peak_group.id

                      item_list.append({'id': i.id, 'no_policy': i.no_policy, 'policy_name' : i.policy_name, 'policy_type' : i.policy_type, 'active': i.active, 'amount':  str(i.amount), 'grace_time': i.grace_time, 'peak_policy_enabled': i.peak_policy_enabled, 'peak_policy_type': i.peak_policy_type, 'peak_group': peak_group_id, 'peak_amount': str(i.peak_amount), 'peak_grace_time': i.peak_grace_time, 'active': i.active, 'arrival_limit_enabled': i.arrival_limit_enabled, 'arrival_time' : i.arrival_time, 'peak_arrival_limit_enabled': i.peak_arrival_limit_enabled, 'peak_arrival_time' : i.peak_arrival_time })
                  item_options['dataitems'] = item_list
                  
                  dumped_data = geojson.dumps(item_options)
                  cache.set('BookingPolicy', dumped_data,  3600)
         else:
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}
                  dumped_data = json.dumps(res)
    else:
         status = 501
         res = {"status": status, "message" : "Unauthorised"}
         dumped_data = json.dumps(res)

    return HttpResponse(dumped_data, content_type='application/json')

def save_booking_policy(request,*args, **kwargs):
    status = 503

    try:
         if request.user.is_authenticated:
             if request.user.is_staff is True:
                   data = json.load(request)
                   payload = data.get('payload')
                   action = payload['action']
                   no_policy = payload['no_policy']
                   policy_id = payload['policy_id']
                   policyname = payload['policyname']
                   policytype = payload['policytype']
                   policyamount = payload['policyamount']
                   policygracetime = payload['policygracetime']

                   #peakpolicyenabled = payload['peakpolicyenabled']
                   peakpolicytype = payload['peakpolicytype']
                   peakpolicygroup = payload['peakpolicygroup']
                   peakpolicyamont = payload['peakpolicyamont']
                   peakpolicygracetime = payload['peakpolicygracetime']

                   policyarrivalenabled = payload['policyarrivalenabled']
                   policyarrivaltime = payload['policyarrivaltime']
                   peakpolicyarrivalenabled = payload['peakpolicyarrivalenabled']
                   peakpolicyarrivaltime = payload['peakpolicyarrivaltime']


                   policyactive = False
                   peak_policy_enabled = False
                   no_policy_enabled = False
                   policy_arrival_enabled = False
                   peak_policy_arrival_enabled = False

                   if no_policy == 'true':
                        no_policy_enabled = True

                   if payload['policyactive'] == 'true':
                        policyactive = True 
                   if payload['peakpolicyenabled'] == 'true':
                        peak_policy_enabled = True
 
                   if payload['policyarrivalenabled'] == 'true':
                        policy_arrival_enabled = True
                   
                   if payload['peakpolicyarrivalenabled'] == 'true':
                        peak_policy_arrival_enabled = True

                   if peakpolicyamont == '':
                       peakpolicyamont = '0.00'
                   if policyamount == '':
                       policyamount = '0.00'
                   if peakpolicygracetime == '':
                       peakpolicygracetime = 0

                   if action == 'save':
                       bookingpolicy = parkstay_models.BookingPolicy.objects.get(id=policy_id)
                       bookingpolicy.no_policy = no_policy_enabled
                       bookingpolicy.policy_name = policyname
                       bookingpolicy.policy_type = policytype
                       bookingpolicy.amount = policyamount
                       bookingpolicy.grace_time = policygracetime 
                       bookingpolicy.peak_policy_enabled = peak_policy_enabled

                       bookingpolicy.arrival_limit_enabled = policy_arrival_enabled
                       bookingpolicy.arrival_time = policyarrivaltime
                       bookingpolicy.peak_arrival_limit_enabled = peak_policy_arrival_enabled
                       bookingpolicy.peak_arrival_time = peakpolicyarrivaltime

                       if peak_policy_enabled is True:
                           bookingpolicy.peak_policy_type= peakpolicytype
                           ppg=None
                           if peakpolicygroup:
                               ppg= parkstay_models.PeakGroup.objects.get(id=peakpolicygroup)
                           bookingpolicy.peak_group = ppg
                           bookingpolicy.peak_amount = peakpolicyamont 
                           bookingpolicy.peak_grace_time = peakpolicygracetime 
                       bookingpolicy.active = policyactive
                       bookingpolicy.save()
                   if action == 'delete':
                       print ("DELETING")
                       parkstay_models.BookingPolicy.objects.filter(id=int(policy_id)).delete()
                       cache.delete('BookingPolicy')
                   if action == 'create': 
                       ppg=None
                       if peakpolicygroup: 
                          ppg= parkstay_models.PeakGroup.objects.get(id=peakpolicygroup)

                       parkstay_models.BookingPolicy.objects.create(no_policy=no_policy_enabled,
                                                                    policy_name=policyname,
                                                                    policy_type=policytype,
                                                                    amount=policyamount,
                                                                    grace_time=policygracetime,
                                                                    peak_policy_enabled=peak_policy_enabled,
                                                                    peak_policy_type=peakpolicytype,
                                                                    peak_group=ppg,
                                                                    peak_amount=peakpolicyamont,
                                                                    peak_grace_time=peakpolicygracetime,
                                                                    active=policyactive,
                                                                    arrival_limit_enabled=policy_arrival_enabled,
                                                                    arrival_time=policyarrivaltime,
                                                                    peak_arrival_limit_enabled=peak_policy_arrival_enabled,
                                                                    peak_arrival_time=peakpolicyarrivaltime
                                                                    )





                   #if action == 'save' or action == 'delete':
                   #     group_id = payload['group_id']

                   #group_name = payload['group_name']
                   #peak_status = payload['peak_status']
                   #peak_status_boolean = False

                   #if peak_status == 'true':
                   #    peak_status_boolean = True

                   #if action == 'save':
                   #     pg = parkstay_models.PeakGroup.objects.get(id=int(group_id))
                   #     pg.name=group_name
                   #     pg.active=peak_status_boolean
                   #     pg.save()
                   #elif action == 'delete':
                   #     parkstay_models.PeakGroup.objects.filter(id=int(group_id)).delete()
                   #     cache.delete('PeakPeriodGroups')
                   #else:
                   #     parkstay_models.PeakGroup.objects.create(name=group_name,active=peak_status_boolean)
                   status = 200
                   res = {"status": status, "message" : "Success"}

             else:
                  status = 501
                  res = {"status": status, "message" : "Unauthorised"}
         else:
              status = 501
              res = {"status": status, "message" : "Unauthorised"}


    except Exception as e:
         status = 503
         res = {
                "status": status, "message": str(e)
         }

    return HttpResponse(json.dumps(res), content_type='application/json', status=status)

def test_server_api(request, *args, **kwargs):
     response = HttpResponse("TESTING API RESPONSE TIMES")
     return response

def campground_map_view(request, *args, **kwargs):
    dumped_data = "[]"
    if os.path.isfile(settings.DATA_STORE+"/campground_map.json"):
        f = open(settings.DATA_STORE+"/campground_map.json", "r")
        dumped_data = f.read()
    else:
        dumped_data = campground_map_data()
        f = open(settings.DATA_STORE+"/campground_map.json", "w")
        f.write(dumped_data)
        f.close()
    return HttpResponse(dumped_data, content_type='application/json')

#def campground_map_view(request, *args, **kwargs):
#    dumped_data = campground_map_data() 
#    return HttpResponse(dumped_data, content_type='application/json')

def campground_map_data():
     from django.core import serializers
     dumped_data = cache.get('CampgroundMapViewSet')
     dumped_data = None
     if dumped_data is None:
         print ("Recreating Campground Cache")
         campground_array = {"type": "FeatureCollection", "features": []}
         features = Feature.objects.all()
         f_obj = {}
         campsite_features_obj = {}
         region_obj = {}
         district_obj = {}
         parks_obj = {}
         campsites_obj = {}
         cgimages_obj = {}
         for f in features:
              image = None
              if f.image:
                  image = f.image.path
              f_obj[f.id] = {'id': f.id, 'name': f.name, 'description': f.description, 'image': image, 'type': f.type}

         queryset_campground_images = CampgroundImage.objects.all() #.values('id','image','campground_id')
         for im in queryset_campground_images:
             if im.campground.id in cgimages_obj:
                 cgimages_obj[im.campground.id].append({'image' : im.image.url})
             else:
                 cgimages_obj[im.campground.id] = []
                 cgimages_obj[im.campground.id].append({'image' : im.image.url})

         queryset = Campground.objects.exclude(campground_type=3).values('id','campground_type','description','info_url','name','wkb_geometry','park_id','max_advance_booking')
         queryset_features = Campground.objects.exclude(campground_type=3).values('id','features')

         queryset_regions = Region.objects.all().values('id','name','abbreviation','ratis_id')
         queryset_districts = District.objects.all().values('id','name','abbreviation','region_id','ratis_id')
         queryset_parks = Park.objects.all().values('id','name','district_id','ratis_id','entry_fee_required','wkb_geometry')
         queryset_campsites = Campsite.objects.all().values('id','campground_id','name','wkb_geometry','tent','campervan','caravan','min_people','max_people','max_vehicles','description')
         queryset_campsite_features = Campsite.objects.all().values('id','features')

         for qr in queryset_regions:
             region_obj[qr['id']] = {'id': qr['id'], 'name': qr['name'], 'abbreviation': qr['abbreviation'], 'ratis_id': qr['ratis_id']} 
         for dr in queryset_districts:
             region = {}
             if dr['region_id']:
                 region = region_obj[dr['region_id']]
             district_obj[dr['id']] = {'id': dr['id'], 'name': dr['name'], 'abbreviation': dr['abbreviation'], 'ratis_id': dr['ratis_id'],'region': region}
         for qp in queryset_parks:
             district = {}
             if qp['district_id'] in district_obj:
                 district = district_obj[qp['district_id']]
             parks_obj[qp['id']] = {'id': qp['id'], 'name': qp['name'], 'district': district, 'entry_fee_required': qp['entry_fee_required']} 

         
         for cf in queryset_campsite_features:
             if cf['id'] in campsite_features_obj:
                pass
             else:
                campsite_features_obj[cf['id']] = []

             # append
             if cf['features']: 
                  campsite_features_obj[cf['id']].append(f_obj[cf['features']])

         for cs in queryset_campsites: 
             campsite_features = []
             if cs['id'] in campsite_features_obj:
                 campsite_features = campsite_features_obj[cs['id']]
             campsites_obj[cs['id']] = {'id': cs['id'], 'campground_id': cs['campground_id'], 'name': cs['name'], 'tent': cs['tent'], 'campervan': cs['campervan'], 'caravan': cs['caravan'], 'max_people': cs['max_people'], 'max_vehicles': cs['max_vehicles'], 'description': cs['description'],'features': campsite_features}

         #print (campsites_obj)
         #queryset1 = Campground.objects.exclude(campground_type=3)
         #queryset_obj = serializers.serialize('json', queryset1)
         #serializer_camp = CampgroundMapSerializer(data=queryset1, many=True)
         #serializer_camp.is_valid()
         #dumped_data = geojson.dumps(serializer_camp.data)
         #cache.set('CampgroundMapViewSet', dumped_data,  3600)

         for c in queryset:
             row = {}
             row['type'] = "Feature"
             row['id'] = c['id']
             row['geometry'] = {}
             if c['wkb_geometry']:
                 row['geometry'] = {"type": "Point", "coordinates": [c['wkb_geometry'][0],c['wkb_geometry'][1]]} 
             row['properties'] = {}
             row['properties']['campground_type'] = c['campground_type']
             row['properties']['max_advance_booking'] = c['max_advance_booking']
             row['properties']['description'] = c['description']
             # Features start
             row['properties']['features'] = []
             for qf in queryset_features:
                 if qf['id'] == c['id']:
                      if qf['features'] in f_obj:
                          row['properties']['features'].append(f_obj[qf['features']])
             # Features end
             if 'images' not in row['properties']:
                row['properties']['images'] = []
             if c['id'] in cgimages_obj:
                  row['properties']['images'] = cgimages_obj[c['id']]

             row['properties']['info_url'] = c['info_url']
             row['properties']['name'] = c['name']

             row['properties']['park'] = {}
             if c['park_id'] in parks_obj:
                  row['properties']['park'] = parks_obj[c['park_id']]
             row['properties']['price_hint'] = None 
             row['properties']['campsites'] = []
             for cs in campsites_obj:
                 if campsites_obj[cs]['campground_id'] == c['id']:
                     row['properties']['campsites'].append(campsites_obj[cs])
             campground_array['features'].append(row)

         dumped_data = json.dumps(campground_array)
         cache.set('CampgroundMapViewSet', dumped_data,  3600)
     return dumped_data
     #return HttpResponse(dumped_data, content_type='application/json')


def places(request, *args, **kwargs):
    dumped_data = "[]"
    if os.path.isfile(settings.DATA_STORE+"/places.json"):
        f = open(settings.DATA_STORE+"/places.json", "r")
        dumped_data = f.read()
    else:
        dumped_data = places_data()
        f = open(settings.DATA_STORE+"/places.json", "w")
        f.write(dumped_data)
        f.close()
    return HttpResponse(dumped_data, content_type='application/json')

def places_data():
    places_list = []
    places_obj = Places.objects.all()
    for p in places_obj:
        gps = None
        if p.wkb_geometry:
             gps = [p.wkb_geometry[0], p.wkb_geometry[1]]
        places_list.append({'id': p.id, 'name': p.name, 'gps': gps, 'zoom_level': p.zoom_level})
    dumped_data = geojson.dumps(places_list) 
    return dumped_data 

def get_booking_vehicle_info(request, *args, **kwargs):
    booking_id = kwargs.get('booking_id')
    today = date.today()
    booking_vehicle_list = []
    booking_data = Booking.objects.filter(id=booking_id, is_canceled=False)
    if booking_data.count() > 0:
        booking = booking_data[0]
        if booking.customer.id == request.user.id or request.user.is_staff is True:
              if booking.departure > today:
                  booking_vehicle_obj = parkstay_models.BookingVehicleRego.objects.filter(booking_id=booking_id)
                  for bv in booking_vehicle_obj:
                      booking_vehicle_list.append({'id': bv.id, 'rego': bv.rego, 'type': bv.type, 'hire_car': bv.hire_car, 'entry_fee': bv.entry_fee, 'park_entry_fee' : bv.park_entry_fee})

                  dumped_data = geojson.dumps(booking_vehicle_list)
                  return HttpResponse(dumped_data, content_type='application/json')
              response = HttpResponse(json.dumps({'message' : 'error booking registration not found'}), content_type='application/json', status=500)
              return response

    response = HttpResponse(json.dumps({'message' : 'Permission Denied'}), content_type='application/json', status=500)
    return response

def booking_vehicle_update(request, *args, **kwargs):

    payload = None
    try:
       today = date.today()
       booking_id = kwargs.get('booking_id')
       data = json.load(request)
       payload = data.get('payload')

       booking_id = payload['booking_id']
       booking_data = Booking.objects.filter(id=booking_id, is_canceled=False)
       if booking_data.count() > 0:
           booking = booking_data[0]
           if booking.customer.id == request.user.id or request.user.is_staff is True:
                   if booking.departure > today:
                        for bv in payload:
                            if bv[0:7] == 'bvrego-':
                                check_plain_text(payload[bv])
                        for bv in payload:
                            if bv[0:7] == 'bvrego-':
                                bvrego_split = bv.split("-")
                                bv_id = bvrego_split[1]
                                bvr_obj = parkstay_models.BookingVehicleRego.objects.filter(id=int(bv_id))
                                if bvr_obj.count() > 0:
                                      bvr = bvr_obj[0]
                                bvr.rego = payload[bv]
                                bvr.save()
                        dumped_data = json.dumps({'status': 'success'})
                        return HttpResponse(dumped_data, content_type='application/json')
                   response = HttpResponse(json.dumps({'message' : 'error booking registration not found'}), content_type='application/json', status=500)
                   return response

       response = HttpResponse(json.dumps({'message' : 'Permission Denied'}), content_type='application/json', status=500)
       return response


    except Exception as e:
        if hasattr(e, 'error_dict'):
            error = repr(e.error_dict)
        else:
            error = {'error': str(e)}
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': error,
        }), status=400, content_type='application/json')

    try:
         print ("")
         dumped_data = geojson.dumps({})
         return HttpResponse(dumped_data, content_type='application/json')
    except ValidationError as e:
        if hasattr(e, 'error_dict'):
            error = repr(e.error_dict)
        else:
            error = {'error': str(e)}
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': error,
        }), status=400, content_type='application/json')


def booking_updates(request, *args, **kwargs):

    data = json.load(request)
    payload = data.get('payload')
    #print (payload)

    try: 
         if 'ps_booking' in request.session:
             booking_id = request.session['ps_booking']
             booking = parkstay_models.Booking.objects.get(id=int(booking_id))
             campsite = booking.campsites.all()[0].campsite if booking else None

             vehicles = payload['vehicles']
             for v in vehicles:
                 check_plain_text(v[1])
             price_override = payload['price_override']
             price_override_admin = payload['price_override_admin']

             #parkstay_models.AdditionalBooking.objects.filter(booking=booking, identifier="vehicles").delete()
             entry_fees = parkstay_models.ParkEntryRate.objects.filter(Q(period_start__lte = booking.arrival), Q(period_end__gte=booking.arrival)|Q(period_end__isnull=True)).order_by('-period_start').first() if (booking and campsite.campground.park.entry_fee_required) else None

             entry_fee_required = campsite.campground.park.entry_fee_required
             #parkstay_models.BookingVehicleRego.objects.filter(booking=booking).delete()

             vehicle_entry_fee = '0.00'
             gst_entry_fee = True
             if entry_fees:
                if entry_fees.gst is False:
                    gst_entry_fee = False
             for v in vehicles:
                 concession = False
                 if v[5] == True:
                     concession = True

                 #if v[2] is True:
                 vehicle_type=''
                 if v[0] == 0 or v[0] == 3:
                     if entry_fee_required:
                         vehicle_entry_fee = entry_fees.vehicle
                         if concession is True:
                              vehicle_entry_fee = entry_fees.concession 
                     vehicle_type='vehicle'
                 if v[0] == 2:
                     if entry_fee_required:
                         vehicle_entry_fee = entry_fees.motorbike
                     vehicle_type='motorbike'
                 if v[0] == 3:
                     if entry_fee_required:
                         vehicle_entry_fee = entry_fees.campervan
                         if concession is True:
                             vehicle_entry_fee = entry_fees.concession
                     vehicle_type='campervan'
                 if v[0] == 4:
                     if entry_fee_required:
                         vehicle_entry_fee = entry_fees.trailer
                     vehicle_type='trailer'
                 if v[0] == 5:
                     if entry_fee_required:
                         vehicle_entry_fee = entry_fees.caravan 
                     vehicle_type='caravan'
                     
                 entry_fee = False
                 if v[2] == True:
                     entry_fee = True
                 hire_care = False
                 if v[4] == True:
                     hire_care = True

                 bvr = parkstay_models.BookingVehicleRego.objects.get(id=v[3], booking=booking)
                 bvr.booking=booking
                 bvr.rego=v[1]
                 bvr.type=vehicle_type
                 bvr.entry_fee=entry_fee
                 bvr.hire_car=hire_care
                 bvr.concession=concession
                 bvr.save()
                 if bvr.additional_booking_id:
                       if entry_fee is False or entry_fee_required is False:
                          parkstay_models.AdditionalBooking.objects.filter(id=bvr.additional_booking_id).delete()
                          bvr.additional_booking_id = None
                          bvr.save()
                       else:
                          ab_obj = parkstay_models.AdditionalBooking.objects.filter(id=bvr.additional_booking_id)
                          if ab_obj.count() > 0:
                                 ab = ab_obj[0]
                                 concession_text = ""
                                 if concession is True:
                                         concession_text = " (Concession driver) "

                                 if hire_care is True and len(v[1]) == 0:
                                      ab.fee_description = "Park Entry Fee for 'Registration to be confirmed before arrival'"+concession_text
                                 else:
                                      ab.fee_description = "Park Entry Fee for "+v[1]+concession_text
                                 ab.amount = vehicle_entry_fee
                                 ab.gst = gst_entry_fee
                                 ab.save() 
                 else:
                         if entry_fee is True and entry_fee_required is True:
                             vh = v[1]
                             if hire_care is True and len(vh) == 0:
                                  vh = "'Registration to be confirmed before arrival'"

                             ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                                          fee_description="Park Entry Fee for "+vh,
                                                                          amount=vehicle_entry_fee,
                                                                          gst=gst_entry_fee,
                                                                          identifier="vehicles",
                                                                          oracle_code=booking.campground.park.oracle_code
                                                                      )
                             bvr.additional_booking_id=ab.id
                             bvr.save()


             if price_override:
                 if request.user.is_authenticated:
                     if request.user.is_staff is True:
                          if parkstay_models.ParkstayPermission.objects.filter(email=request.user.email,permission_group=1).count() > 0:
                                    dr = parkstay_models.DiscountReason.objects.filter(id=int(price_override_admin['override_reason_selection']))
                                    if dr.count() > 0:
                                        booking.override_reason = dr[0]
                                        booking.override_reason_info = price_override_admin['override_reason_details']
                                        booking.save()
                                        parkstay_models.AdditionalBooking.objects.filter(booking=booking, identifier='priceoverride').delete()
                                        ab_or = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                             fee_description=booking.override_reason.text+" - "+booking.override_reason_info,
                                                             amount='0.00',
                                                             identifier="priceoverride",
                                                             oracle_code=booking.campground.oracle_code
                                                            )


                                    for po in price_override:
                                        if po[0:31] == 'price-override-campsites-adult-':
                                               po_split = po.split("-")
                                               priceoverride_campsite_additional_booking_id = po_split[4]
                                               csb = parkstay_models.CampsiteBooking.objects.get(id=priceoverride_campsite_additional_booking_id)
                                               csb.amount_adult = price_override['price-override-campsites-adult-'+priceoverride_campsite_additional_booking_id]
                                               csb.amount_child = price_override['price-override-campsites-child-'+priceoverride_campsite_additional_booking_id]
                                               csb.amount_infant = price_override['price-override-campsites-infant-'+priceoverride_campsite_additional_booking_id]
                                               csb.amount_concession = price_override['price-override-campsites-concession-'+priceoverride_campsite_additional_booking_id]
                                               csb.save()
                                        if po[0:21] == 'price-override-other-':
                                               po_split = po.split("-")
                                               priceoverride_campsite_additional_booking_id = po_split[3]
                                               if parkstay_models.AdditionalBooking.objects.filter(id=priceoverride_campsite_additional_booking_id).count() > 0:
                                                  ab = parkstay_models.AdditionalBooking.objects.get(id=priceoverride_campsite_additional_booking_id)
                                                  ab.amount = price_override[po]
                                                  ab.save()


         dumped_data = geojson.dumps({})
         return HttpResponse(dumped_data, content_type='application/json')
    except ValidationError as e:
        if hasattr(e, 'error_dict'):
            error = repr(e.error_dict)
        else:
            error = {'error': str(e)}
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': error,
        }), status=400, content_type='application/json')



def get_booking_pricing(request, *args, **kwargs):
    booking_id = None
    booking_information = {'campsite_booking': [], 'additional_booking': [], 'booking_vehicle' : [], 'booking': {}, 'old_campsite_booking': [], 'old_additional_booking': [], 'old_booking_vehicle': [], 'override_details': {'override_reason_info': '', 'override_reason' : None} }

    if 'ps_booking' in request.session:
         booking_id = request.session['ps_booking']
         booking = parkstay_models.Booking.objects.get(id=int(booking_id))

         booking_information['booking']['id'] = booking.id
         booking_information['booking']['cost_total'] = str(booking.cost_total)
         if booking.override_reason:
             booking_information['override_details']['override_reason'] = booking.override_reason.id
             booking_information['override_details']['override_reason_info'] = booking.override_reason_info

         old_campsite_booking = []
         old_additional_booking = []
         old_booking_vehicle_rego = []

         if booking.old_booking:
             old_campsite_booking = CampsiteBooking.objects.filter(booking_id=booking.old_booking)
             old_additional_booking = parkstay_models.AdditionalBooking.objects.filter(booking_id=booking.old_booking, identifier='vehicles')
             old_booking_vehicle_rego = parkstay_models.BookingVehicleRego.objects.filter(booking_id=booking.old_booking)

         campsite_booking = CampsiteBooking.objects.filter(booking=booking)
         additional_booking = parkstay_models.AdditionalBooking.objects.filter(booking=booking)
         booking_vehicle_rego = parkstay_models.BookingVehicleRego.objects.filter(booking=booking)

         # old
         for cb in old_campsite_booking:
             row = {}
             row['id'] = cb.id
             row['date'] = cb.date.strftime("%d/%m/%Y")
             row['booking_policy_id'] = cb.booking_policy.id

             item_name = ''
             if cb.campsite.campground:
                 item_name = item_name + cb.campsite.campground.name
             if cb.campsite:
                 item_name = item_name + " "+cb.campsite.name
             if cb.campsite.campsite_class:
                 item_name = item_name + " "+cb.campsite.campsite_class.name

             row['item_name'] = item_name
             row['amount_adult'] = str(cb.amount_adult)
             row['amount_infant'] = str(cb.amount_infant)
             row['amount_child'] = str(cb.amount_child)
             row['amount_concession'] = str(cb.amount_concession)
             booking_information['old_campsite_booking'].append(row)

         for ab in old_additional_booking:
             row = {}
             row['id'] = ab.id
             row['amount'] = str(ab.amount)
             row['item_name'] = ab.fee_description
             booking_information['old_additional_booking'].append(row)

         for bv in old_booking_vehicle_rego:
             row = {}
             row['id'] = bv.id
             row['rego'] = bv.rego
             row['type'] = bv.type
             row['entry_fee'] = bv.entry_fee
             row['hire_car'] = bv.hire_car
             row['park_entry_fee'] = bv.park_entry_fee
             row['concession'] = bv.concession
             booking_information['old_booking_vehicle'].append(row)


         # new 
         for cb in campsite_booking:
             row = {}
             row['id'] = cb.id
             row['date'] = cb.date.strftime("%d/%m/%Y")
             row['booking_policy_id'] = None
             if cb.booking_policy:
                 row['booking_policy_id'] = cb.booking_policy.id

             item_name = ''
             if cb.campsite.campground:
                 item_name = item_name + cb.campsite.campground.name
             if cb.campsite:
                 item_name = item_name + " "+cb.campsite.name
             if cb.campsite.campsite_class:
                 item_name = item_name + " "+cb.campsite.campsite_class.name

             row['item_name'] = item_name 
             row['amount_adult'] = str(cb.amount_adult)
             row['amount_infant'] = str(cb.amount_infant)
             row['amount_child'] = str(cb.amount_child)
             row['amount_concession'] = str(cb.amount_concession)
             booking_information['campsite_booking'].append(row)

         for ab in additional_booking:
             row = {}
             row['id'] = ab.id
             row['amount'] = str(ab.amount)
             row['item_name'] = ab.fee_description
             booking_information['additional_booking'].append(row)


         for bv in booking_vehicle_rego:
             row = {}
             row['id'] = bv.id
             row['rego'] = bv.rego
             row['type'] = bv.type
             row['entry_fee'] = bv.entry_fee
             row['hire_car'] = bv.hire_car
             row['concession'] = bv.concession
             row['park_entry_fee'] = bv.park_entry_fee
             booking_information['booking_vehicle'].append(row)


    dumped_data = geojson.dumps(booking_information)
    return HttpResponse(dumped_data, content_type='application/json')

def get_date_diff_in_days(request, *args, **kwargs):
    arrival_date = request.GET.get('arrival_date',None)
    # Define the custom date (format: YYYY-MM-DD)
    if arrival_date is None:
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': 'arrival_date parameter is required.'
        }), content_type='application/json', status=400)
    custom_date = datetime.strptime(arrival_date, "%Y/%m/%d")

    # Get the current date
    current_date = datetime.now()

    # Calculate the difference in days
    days_difference = abs((custom_date - current_date).days)

    # Print the result
    
    return HttpResponse(geojson.dumps({
        'status': 'success',
        'days_difference': days_difference
    }), content_type='application/json', status=200)

@csrf_exempt
@require_http_methods(['POST'])
def create_booking(request, *args, **kwargs):
    context_p = context_processors.parkstay_url(request)
    change_booking_id = request.POST.get('change_booking_id',None)
    date_override = request.POST.get('date_override',"false")
    public_site_closure = utils.public_site_closure()    
    if public_site_closure["status"] == 200:        
        if request.user.is_authenticated:            
            parkstay_officers = ledger_api_utils.user_in_system_group(request.session['user_obj']['user_id'],'Parkstay Officers')
            if parkstay_officers is True:                
                pass
            else:
                return HttpResponse(geojson.dumps({
                    'status': 'error',
                    'msg': 'The system is currently closed for bookings.',            
                }), status=400, content_type='application/json')
        else:                         
            return HttpResponse(geojson.dumps({
                'status': 'error',
                'msg': 'The system is currently closed for bookings.',            
            }), status=400, content_type='application/json')


    try:
        for name in ('selecttype', 'multiplesites', 'multiplesites_class_totals'):
            check_plain_text(request.POST.get(name, ''))
    except ValidationError as e:
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': e.messages[0],
        }), status=400, content_type='application/json')

    try:
        inprogress_booking = utils.get_session_booking(request.session)
        print ("INPROGRESS BOOKING")
        print (inprogress_booking)

        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': 'You have an in-progress booking.',
            'inprogress_booking': True
        }), status=400, content_type='application/json')

        # only ever delete a booking object if it's marked as temporary
                
    except Exception as e:
        pass


    today = timezone.now().date()
    if change_booking_id == '':
         change_booking_id = None
    else:
        if int(change_booking_id) > 0:
            change_booking_id = int(change_booking_id) 
        else:
            change_booking_id = None

    """Create a temporary booking and link it to the current session"""
    data = {
        'arrival': request.POST.get('arrival'),
        'departure': request.POST.get('departure'),
        'num_adult': request.POST.get('num_adult', 0),
        'num_concession': request.POST.get('num_concession', 0),
        'num_child': request.POST.get('num_child', 0),
        'num_infant': request.POST.get('num_infant', 0),

        'num_vehicle' : request.POST.get('num_vehicle',0),
        'num_campervan' : request.POST.get('num_campervan',0),
        'num_caravan' : request.POST.get('num_caravan',0),
        'num_motorcycle' : request.POST.get('num_motorcycle',0),
        'num_trailer' : request.POST.get('num_trailer',0),
        'postcode' : request.POST.get('postcode'),
        'campground': request.POST.get('campground', 0),
        'campsite_class': request.POST.get('campsite_class', 0),
        'campsite': request.POST.get('campsite', 0),
        'old_booking': change_booking_id,
        'created_by': request.user.id
    }

    serializer = CampsiteBookingSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    campground = serializer.validated_data['campground']
    campsite_class = serializer.validated_data['campsite_class']
    campsite = serializer.validated_data['campsite']
    start_date = serializer.validated_data['arrival']
    end_date = serializer.validated_data['departure']
    num_adult = serializer.validated_data['num_adult']
    num_concession = serializer.validated_data['num_concession']
    num_child = serializer.validated_data['num_child']
    num_infant = serializer.validated_data['num_infant']

    num_vehicle = serializer.validated_data['num_vehicle']
    num_campervan = serializer.validated_data['num_campervan']
    num_caravan = serializer.validated_data['num_caravan']
    num_motorcycle = serializer.validated_data['num_motorcycle']
    num_trailer = serializer.validated_data['num_trailer']
    old_booking = serializer.validated_data['old_booking']
    # postcode = serializer.validated_data['postcode']

    multiplesites_class_totals = {}
    selecttype = None
    if context_p['PARKSTAY_PERMISSIONS']['p0'] is True:
       selecttype = request.POST.get('selecttype',None)
       multiplesites = json.loads(request.POST.get('multiplesites', "[]"))
       multiplesites_class_totals = json.loads(request.POST.get('multiplesites_class_totals', "{}"))
    else:
       selecttype = 'single'
       multiplesites = []
       multiplesites_class_totals = {}

    parkstay_officers = False
    if 'user_obj' in request.session:
        parkstay_officers = ledger_api_utils.user_in_system_group(request.session['user_obj']['user_id'],'Parkstay Officers')       


    if 'ps_booking' in request.session:
        # Delete booking and start again
        booking_id = request.session['ps_booking']
        if Booking.objects.filter(id=booking_id, booking_type=3).count() > 0:
              Booking.objects.get(id=booking_id).delete()
        request.session['ps_booking'] = None

        # if there's already a booking in the current session, send bounce signal
        #messages.success(request, 'Booking already in progress, complete this first!')
        #return HttpResponse(geojson.dumps({
        #    'status': 'success',
        #    'msg': 'Booking already in progress.',
        #    'pk': request.session['ps_booking']
        #}), content_type='application/json')

    if old_booking:
        if Booking.objects.filter(id=old_booking).exclude(booking_type=3).count() > 0:
            old_booking_obj = Booking.objects.get(id=old_booking)
            total_days_departure_old_booking = old_booking_obj.departure - today
            total_days_departure_new_booking = end_date - today
            max_advance_booking = old_booking_obj.campground.max_advance_booking
            release_date = None
            release_period = utils.get_release_date_for_campground(old_booking_obj.campground.id)
            if release_period:
                release_date = release_period['release_date']                
                if release_date:
                    
                    release_date_difference = release_date - today
                    max_advance_booking = release_date_difference.days

            if old_booking_obj.arrival > today:
                if old_booking_obj.departure >= today:
                    # if  parkstay_officers is True:
                    if parkstay_officers is True and date_override == 'true':
                        print ("Date Override Permissions Activated")                                              
                    else:
                        if end_date == today:
                            error = {"status": "error", 'msg': {"title": "Change not permitted", "error" :"<div style='text-align:center'>Departure date can not be the same as today date.</div>"} }
                            return HttpResponse(json.dumps(error), status=400, content_type='application/json')                    

                        if total_days_departure_old_booking.days > max_advance_booking:
                            if total_days_departure_new_booking.days > total_days_departure_old_booking.days:
                                error = {"status": "error", 'msg': {"title": "Change not permitted", "error" :"<div style='text-align:left'>Changes that add dates not currently available to others are not permitted. <br><br>You may:<br><ul><li>change to an earlier or later arrival and/or to an earlier departure.</li><li>cancel the booking</li></ul></div>"} }
                                return HttpResponse(json.dumps(error), status=400, content_type='application/json')                    

                        # old_end_date = old_booking_obj.departure.strftime("%Y-%m-%d")
                        # if old_end_date != end_date.strftime("%Y-%m-%d"):
                        #     error = {"status": "error", 'msg': {"error" :"The departure date for a booking can not be changed. "+str(total_days.days)+"  Please contact the campground operator for more inforamtion."} }
                        #     return HttpResponse(json.dumps(error), status=400, content_type='application/json')                    
                

            if old_booking_obj.arrival <= today:
                if old_booking_obj.departure >= today:
                    if  parkstay_officers is True:
                            # context['parkstay_officers_change_arrival'] = True
                            pass
                    else:
                            if end_date == today:
                                error = {"status": "error", 'msg': {"title": "Change not permitted", "error" :"<div style='text-align:center'>Departure date can not be the same as today date.</div>"} }
                                return HttpResponse(json.dumps(error), status=400, content_type='application/json')

                            old_start_date = old_booking_obj.arrival.strftime("%Y-%m-%d")
                            if old_start_date != start_date.strftime("%Y-%m-%d"):
                                error = {"status": "error", 'msg': {"error" :"The arrival date can not be changed once a booking has started."} }
                                return HttpResponse(json.dumps(error), status=400, content_type='application/json')
     
                            pass

    # for a manually-specified campsite, do a sanity check
    # ensure that the campground supports per-site bookings and bomb out if it doesn't
    if campsite:
        campsite_obj = Campsite.objects.prefetch_related('campground').get(pk=campsite)
        if campsite_obj.campground.site_type != 0:
            if context_p['PARKSTAY_PERMISSIONS']['p0'] is True:
                pass
            else:
                return HttpResponse(geojson.dumps({
                    'status': 'error',
                    'msg': 'Campground doesn\'t support per-site bookings.'
                }), status=400, content_type='application/json')
    # for the rest, check that both campsite_class and campground are provided
    elif len(multiplesites_class_totals) > 0:
        pass
    elif (not campsite_class) or (not campground):
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': 'Must specify campsite_class and campground.'
        }), status=400, content_type='application/json')

    # try to create a temporary booking
    try:
        if campsite:
            booking = None
            if selecttype == 'multiple':
                cs_obj = Campsite.objects.filter(id__in=multiplesites)
            else:
                cs_obj = Campsite.objects.filter(id=campsite)

            booking = utils.create_booking_by_site(request,
                cs_obj, start_date, end_date,
                num_adult, num_concession,
                num_child, num_infant, num_vehicle, num_campervan, num_motorcycle, num_trailer,num_caravan, 0, None, None, None, False, None, None, False, False, False, old_booking 
            )

            booking.created_by = request.user.id
            booking.save()
        else:
            if selecttype == 'multiple':
                 pass 
            else:
                 multiplesites_class_totals[campsite_class] = 1
             
            booking = utils.create_booking_by_class(request,
                campground, multiplesites_class_totals,
                start_date, end_date,
                num_adult, num_concession,
                num_child, num_infant,
                num_vehicle, num_motorcycle, num_campervan, 
                num_trailer,num_caravan, old_booking
            )

            booking.created_by = request.user.id
            booking.save()

        booking.details['selecttype'] = selecttype 
        booking.details['multiplesites_class_totals'] = multiplesites_class_totals
        booking.booking_hash = hashlib.sha256(str(booking.pk).encode('utf-8')).hexdigest()
        booking.save()
        park_entry_fee_required = booking.campground.park.entry_fee_required
        booking_campsite = booking.campsites.all()[0].campsite if booking else None
        parkstay_models.AdditionalBooking.objects.filter(booking=booking, identifier="vehicles").delete()
        entry_fees = parkstay_models.ParkEntryRate.objects.filter(Q(period_start__lte = booking.arrival), Q(period_end__gte=booking.arrival)|Q(period_end__isnull=True)).order_by('-period_start').first() if (booking and booking_campsite.campground.park.entry_fee_required) else None

        old_bvr_array = []
        old_bvr_array = {0 : {},1: {},2:{},3:{},4:{},5:{}}
        if booking.old_booking:
             old_bvr_count = {'vehicle': 0, 'motorcycle': 0, 'campervan': 0, 'trailer': 0, 'caravan': 0}
             old_bvr = parkstay_models.BookingVehicleRego.objects.filter(booking_id=booking.old_booking)
             for t in old_bvr:
                 if t.type == 'vehicle':
                     old_bvr_array[0][old_bvr_count['vehicle']] = {'rego': t.rego, 'park_entry_fee': t.park_entry_fee,'entry_fee': t.entry_fee, 'concession': t.concession, 'hire_car': t.hire_car}
                     old_bvr_count['vehicle'] = old_bvr_count['vehicle'] + 1
                 if t.type == 'motorbike': 
                     old_bvr_array[2][old_bvr_count['motorcycle']]  = {'rego': t.rego, 'park_entry_fee': t.park_entry_fee,'entry_fee': t.entry_fee, 'concession': t.concession, 'hire_car': t.hire_car}
                     old_bvr_count['motorcycle'] = old_bvr_count['motorcycle'] + 1
                 if t.type == 'campervan':
                     old_bvr_array[3][old_bvr_count['campervan']] = {'rego': t.rego, 'park_entry_fee': t.park_entry_fee,'entry_fee': t.entry_fee, 'concession': t.concession, 'hire_car': t.hire_car}
                     old_bvr_count['campervan'] = old_bvr_count['campervan'] + 1
                 if t.type == 'trailer': 
                     old_bvr_array[4][old_bvr_count['trailer']] = {'rego': t.rego, 'park_entry_fee': t.park_entry_fee,'entry_fee': t.entry_fee, 'concession': t.concession, 'hire_car': t.hire_car}
                     old_bvr_count['trailer'] = old_bvr_count['trailer'] + 1
                 if t.type == 'caravan':
                     old_bvr_array[5][old_bvr_count['caravan']] =  {'rego': t.rego, 'park_entry_fee': t.park_entry_fee,'entry_fee': t.entry_fee, 'concession': t.concession, 'hire_car': t.hire_car}
                     old_bvr_count['caravan'] = old_bvr_count['caravan'] + 1
        entry_fee_required = booking_campsite.campground.park.entry_fee_required

        parkstay_models.BookingVehicleRego.objects.filter(booking=booking).delete()
        for i in range(0, num_vehicle):
            rego_text = ''
            entry_fee = True
            concession = False
            hire_car = False
            if i in  old_bvr_array[0]:
                rego_text = old_bvr_array[0][i]['rego']
                entry_fee = old_bvr_array[0][i]['entry_fee'] 
                concession = old_bvr_array[0][i]['concession']
                hire_car = old_bvr_array[0][i]['hire_car']
            entry_fee_amount = '0.00'
            concession_text = ""
            if entry_fee_required:
                   entry_fee_amount = entry_fees.vehicle
                   concession_text = ""
                   if concession is True:
                        entry_fee_amount = entry_fees.concession
                        concession_text = " (Concession driver)"

            fee_description = ''
            if hire_car is True and len(rego_text) == 0:
                  fee_description = "Park Entry Fee for 'Registration to be confirmed before arrival'"+concession_text
            else:
                  fee_description = "Park Entry Fee for "+rego_text+concession_text

            if park_entry_fee_required is False:
                entry_fee = False

            bvr = parkstay_models.BookingVehicleRego.objects.create(booking=booking,rego=rego_text, type='vehicle',entry_fee=entry_fee, concession=concession, hire_car=hire_car)

            if entry_fee_required is True:
                if entry_fee is False: #and entry_fee_required is False:
                    pass
                else:
                    ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                            fee_description=fee_description,
                                                            amount=entry_fee_amount,
                                                            gst=entry_fees.gst,
                                                            identifier="vehicles",
                                                            oracle_code=booking.campground.park.oracle_code
                                                         )

                    bvr.additional_booking_id =ab.id
                    bvr.save()

        for i in range(0, num_campervan):
            rego_text = ''
            entry_fee = True
            if i in  old_bvr_array[3]:
                 rego_text = old_bvr_array[3][i]['rego']
                 entry_fee = old_bvr_array[3][i]['entry_fee']

            entry_fee_amount = '0.00'
            if entry_fee_required:
                entry_fee_amount = entry_fees.campervan

            bvr = parkstay_models.BookingVehicleRego.objects.create(booking=booking,rego=rego_text, type='campervan',entry_fee=entry_fee)
            if entry_fee_required is True:
                if entry_fee is False: #and entry_fee_required is False:
                    pass
                else:
                    ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                                 fee_description="Park Entry Fee for "+rego_text,
                                                                 amount=entry_fee_amount,
                                                                 identifier="vehicles",
                                                                 oracle_code=booking.campground.park.oracle_code
                                                                )
                    bvr.additional_booking_id =ab.id
                    bvr.save()

        for i in range(0, num_motorcycle):
            rego_text = ''
            entry_fee = True 
            if i in  old_bvr_array[2]:
                 rego_text = old_bvr_array[2][i]['rego']
                 entry_fee = old_bvr_array[2][i]['entry_fee']
            
            entry_fee_amount = '0.00'
            if entry_fee_required:
                entry_fee_amount = entry_fees.motorbike

            bvr = parkstay_models.BookingVehicleRego.objects.create(booking=booking,rego=rego_text, type='motorbike',entry_fee=entry_fee)
            if entry_fee_required is True:
                if entry_fee is False: #and entry_fee_required is False:
                    pass
                else:
                    ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                                 fee_description="Park Entry Fee for "+rego_text,
                                                                 amount=entry_fee_amount,
                                                                 identifier="vehicles",
                                                                 oracle_code=booking.campground.park.oracle_code
                                                                )
                    bvr.additional_booking_id =ab.id
                    bvr.save()

        for i in range(0, num_trailer):
            rego_text = ''
            entry_fee = False
            if i in  old_bvr_array[4]:
                rego_text = old_bvr_array[4][i]['rego']
                entry_fee = old_bvr_array[4][i]['entry_fee']

            entry_fee_amount = '0.00'
            if entry_fee_required:
                entry_fee_amount = entry_fees.trailer

            # prepopulate entry_fee and park fee@#@@@@@@@@@@@@@@@@@@@@
            bvr = parkstay_models.BookingVehicleRego.objects.create(booking=booking,rego=rego_text, type='trailer',entry_fee=entry_fee)
            if entry_fee_required is True:
                if entry_fee is False: #and entry_fee_required is False:
                    pass
                else:
                    ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                                     fee_description="Park Entry Fee for "+rego_text,
                                                                     amount=entry_fee_amount,
                                                                     identifier="vehicles",
                                                                     oracle_code=booking.campground.park.oracle_code
                                                                    )
                    bvr.additional_booking_id = ab.id
                    bvr.save()

        for i in range(0, num_caravan):
            rego_text = ''
            entry_fee = False
            if i in  old_bvr_array[5]:
                rego_text = old_bvr_array[5][i]['rego']
                entry_fee = old_bvr_array[5][i]['entry_fee']

            entry_fee_amount = '0.00'
            if entry_fee_required:
                entry_fee_amount = entry_fees.caravan

            bvr = parkstay_models.BookingVehicleRego.objects.create(booking=booking,rego=rego_text, type='caravan',entry_fee=entry_fee)
            if entry_fee_required is True:
                if entry_fee is False: #and entry_fee_required is False:
                    pass
                else:
                    ab = parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                                                     fee_description="Park Entry Fee for Caravan",
                                                                     amount=entry_fee_amount,
                                                                     identifier="vehicles",
                                                                     oracle_code=booking.campground.park.oracle_code
                                                                    )
                    bvr.additional_booking_id =ab.id
                    bvr.save()




        # add cancellation fees if change booking
        cancellation_data = []
        if booking.old_booking:
            cancellation_data =  utils.booking_change_fees(booking)

            parkstay_models.AdditionalBooking.objects.create(booking=booking,
                                              fee_description="Cancellation Fee",
                                              amount=cancellation_data['cancellation_fee'],
                                              identifier='cancellation_fee',
                                              oracle_code=booking.campsite_oracle_code
                                            )

    except ValidationError as e:
        if hasattr(e, 'error_dict'):
            error = repr(e.error_dict)
        else:
            error = {'error': str(e)}
        return HttpResponse(geojson.dumps({
            'status': 'error',
            'msg': error,
        }), status=400, content_type='application/json')

    # add the booking to the current session
    request.session['ps_booking'] = booking.pk
    checkouthash = hashlib.sha256(str(booking.pk).encode('utf-8')).hexdigest()
    request.session['checkouthash'] = checkouthash

    return HttpResponse(geojson.dumps({
        'status': 'success',
        'pk': booking.pk
    }), content_type='application/json')


@require_http_methods(['GET'])
def get_confirmation(request, *args, **kwargs):
    # fetch booking for ID
    booking_id = kwargs.get('booking_id', None)
    if (booking_id is None):
        return HttpResponse('Booking ID not specified', status=400)

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return HttpResponse('Booking unavailable', status=403)

    # check permissions
    if not ((request.user == booking.customer) or is_officer(request.user) or (booking.id == request.session.get('ps_last_booking', None))):
        return HttpResponse('Booking unavailable', status=403)

    # check payment status
    if (not is_officer(request.user)) and (not booking.paid):
        return HttpResponse('Booking unavailable', status=403)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="confirmation-'+settings.BOOKING_PREFIX+'{}.pdf"'.format(booking_id)

    #pdf.create_confirmation(response, booking)
    response.content = doctopdf.create_confirmation(booking)

    return response


class PromoAreaViewSet(viewsets.ModelViewSet):
    queryset = PromoArea.objects.all()
    serializer_class = PromoAreaSerializer
    permission_classes = [OfficerPermission]


class ParkViewSet(viewsets.ModelViewSet):
    queryset = Park.objects.all()
    serializer_class = ParkSerializer
    permission_classes = [OfficerPermission]

    def list(self, request, *args, **kwargs):
        data = cache.get('parks')
        if data is None:
            queryset = self.get_queryset()
            serializer = self.get_serializer(queryset, many=True)
            data = serializer.data
            cache.set('parks', data, 3600)
        return Response(data)

    @list_route(methods=['get'], detail=False)
    def price_history(self, request, format='json', pk=None):
        http_status = status.HTTP_200_OK
        try:
            price_history = ParkEntryRate.objects.all().order_by('-period_start')
            serializer = ParkEntryRateSerializer(price_history, many=True, context={'request': request}, method='get')
            res = serializer.data
        except Exception as e:
            res = {
                "Error": str(e)
            }

        return Response(res, status=http_status)

    @detail_route(methods=['get'], detail=True)
    def current_price(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            start_date = request.GET.get('arrival', False)
            res = []
            if start_date:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                price_history = ParkEntryRate.objects.filter(period_start__lte=start_date).order_by('-period_start')
                if price_history:
                    serializer = ParkEntryRateSerializer(price_history, many=True, context={'request': request})
                    res = serializer.data[0]

        except Exception as e:
            res = {
                "Error": str(e)
            }
        return Response(res, status=http_status)

    @list_route(methods=['post'], detail=False)
    def add_price(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            serializer = ParkEntryRateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            res = serializer.data
            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except Exception as e:
            raise serializers.ValidationError(str(e))


class FeatureViewSet(viewsets.ModelViewSet):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [OfficerPermission]


class ParkEntryRateViewSet(viewsets.ModelViewSet):
    queryset = ParkEntryRate.objects.all()
    serializer_class = ParkEntryRateSerializer
    permission_classes = [OfficerPermission]


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [OfficerOrReadOnlyPermission]


class CampsiteClassViewSet(viewsets.ModelViewSet):
    queryset = CampsiteClass.objects.all()
    serializer_class = CampsiteClassSerializer
    permission_classes = [OfficerPermission]

    def list(self, request, *args, **kwargs):
        active_only = bool(request.GET.get('active_only', False))
        if active_only:
            queryset = CampsiteClass.objects.filter(deleted=False)
        else:
            queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True, method='get')
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, method='get')
        return Response(serializer.data)

    @detail_route(methods=['get'], detail=True)
    def price_history(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            price_history = CampsiteClassPriceHistory.objects.filter(id=self.get_object().id).order_by('-date_start')
            # Format list
            open_ranges, formatted_list, fixed_list = [], [], []
            for p in price_history:
                if p.date_end is None:
                    open_ranges.append(p)
                else:
                    formatted_list.append(p)

            for outer in open_ranges:
                for inner in open_ranges:
                    if inner.date_start > outer.date_start and inner.rate_id == outer.rate_id:
                        open_ranges.remove(inner)

            fixed_list = formatted_list + open_ranges
            fixed_list.sort(key=lambda x: x.date_start)
            serializer = CampsiteClassPriceHistorySerializer(fixed_list, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['post'], detail=True)
    def addPrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            rate = None
            serializer = RateDetailSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rate_id = serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=serializer.validated_data['adult'], concession=serializer.validated_data['concession'], child=serializer.validated_data['child'], infant=serializer.validated_data['infant'])[0]
            if rate:
                serializer.validated_data['rate'] = rate
                data = {
                    'rate': rate,
                    'date_start': serializer.validated_data['period_start'],
                    'reason': PriceReason.objects.get(pk=serializer.validated_data['reason']),
                    'details': serializer.validated_data.get('details', None),
                    'update_level': 1
                }
                self.get_object().createCampsitePriceHistory(data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['post'], detail=True)
    def updatePrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            original_data = request.data.pop('original')

            original_serializer = CampgroundPriceHistorySerializer(data=original_data)
            original_serializer.is_valid(raise_exception=True)

            serializer = RateDetailSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rate_id = serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=serializer.validated_data['adult'], concession=serializer.validated_data['concession'], child=serializer.validated_data['child'], infant=serializer.validated_data['infant'])[0]
            if rate:
                serializer.validated_data['rate'] = rate
                new_data = {
                    'rate': rate,
                    'date_start': serializer.validated_data['period_start'],
                    'reason': PriceReason.objects.get(pk=serializer.validated_data['reason']),
                    'details': serializer.validated_data.get('details', None),
                    'update_level': 1
                }
                self.get_object().updatePriceHistory(dict(original_serializer.validated_data), new_data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['post'], detail=True)
    def deletePrice(self, request, format='json', pk=None):
        try:
            http_status = status.HTTP_200_OK
            serializer = CampgroundPriceHistorySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            self.get_object().deletePriceHistory(serializer.validated_data)
            price_history = CampgroundPriceHistory.objects.filter(id=self.get_object().id)
            serializer = CampgroundPriceHistorySerializer(price_history, many=True, context={'request': request})
            res = serializer.data

            return Response(res, status=http_status)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.none()
    serializer_class = BookingSerializer
    permission_classes = [OfficerPermission,]

    def list(self, request, *args, **kwargs):
        try:
            SORTABLE_COLS = ['id', 'campground_name', 'campground_site_type',  'arrival', 'departure']
            #print("MLINE 1.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            search = request.GET.get('search[value]')
            draw = request.GET.get('draw') if request.GET.get('draw') else 1
            start = request.GET.get('start') if request.GET.get('draw') else 0
            length = request.GET.get('length') if request.GET.get('draw') else 'all'
            arrival = str(datetime.strptime(request.GET.get('arrival'), '%d/%m/%Y')) if request.GET.get('arrival') else ''
            arrival_date = datetime.strptime(request.GET.get('arrival'), '%d/%m/%Y') if request.GET.get('arrival') else ''
            departure = str(datetime.strptime(request.GET.get('departure'), '%d/%m/%Y')) if request.GET.get('departure') else ''
            departure_date = datetime.strptime(request.GET.get('departure'), '%d/%m/%Y') if request.GET.get('departure') else ''
            campground = request.GET.get('campground')
            region = request.GET.get('region')
            park = request.GET.get('park')
            canceled = request.GET.get('canceled', None)
            refund_status = request.GET.get('refund_status', None)
            sort_column= request.GET.get('sort_column', 'id')
            sort_direction = request.GET.get('sort_direction', 'asc')
            sort_filter = None
            sorting_fields = ['campground__name', 'campground__park__district__region__name','id']
            if sort_column:
                sorting_fields = []
                if sort_column in SORTABLE_COLS:
                    if sort_column in ['campground_site_type', 'campground_name', 'arrival', 'departure']:
                        sorting_fields = ['campground__park__district__region__name','id']
                    
                    if sort_column == 'campground_site_type':
                        sort_column = 'property_cache__first_campsite_list2__0__name'
                    elif sort_column == 'campground_name':
                        sort_column = 'campground__name'

                    sort_filter = sort_column if sort_direction == 'asc' else '-' + sort_column
                    sorting_fields.insert(0, sort_filter)

            #print("MLINE 2.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            campground_groups = models.CampgroundGroup.objects.filter(members__in=[request.user.id])
            
            if canceled:
                canceled = True if canceled.lower() in ['yes', 'true', 't', '1'] else False
            #print ("MLINE 2.20", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            booking_query = Q(is_canceled=canceled)
            if len(campground_groups) == 0:
                # Return no results as not part of any permission group
                return Response(OrderedDict([
                    ('recordsTotal', 0),
                    ('recordsFiltered', 0),
                    ('results', [])
                ]), status=status.HTTP_200_OK)

                
            # Filter Campground based on permissions
            cg_query = Q()
            for cg in campground_groups:
                 c = cg.campgrounds.all()
                 for d in c:
                     cg_query |= Q(campground__id=d.id)
            booking_query &= Q(cg_query)

            ########################################
            if campground:
                booking_query &= Q(campground__id=campground)
            if region:
                booking_query &= Q(campground__park__district__region__id=region)
            if park:
                booking_query &= Q(campground__park__id=park)
            if arrival:
                 booking_query &= Q(departure__gt=arrival_date)
            if departure:
                  booking_query &= Q(arrival__lte=departure_date)
            if refund_status:
                  if refund_status != 'All':
                      booking_query &= Q(property_cache__refund_status=refund_status)
            if search or refund_status:
                if search[:2] == settings.BOOKING_PREFIX:
                    bid = search.replace(settings.BOOKING_PREFIX,"")
                    booking_query &= Q(id=int(bid))
                elif search != '':
                    pass
                    search_only_digit = re.sub('[^0-9]','', search)
                    search_only_words = re.sub('[^a-z|A-Z]','', search)
                    booking_query_search = Q()
                    if search_only_digit:
                        if search_only_words:
                          pass
                        else:
                          booking_query_search |= Q(id=int(search_only_digit))
                    booking_query_search |= Q(campground__name__icontains=search)
                    booking_query_search |= Q(campground__park__district__region__name__icontains=search)
                    booking_query_search |= Q(details__first_name__icontains=search ) 
                    booking_query_search |= Q(details__last_name__icontains=search )
                    booking_query_search |= Q(legacy_name__icontains=search)
                    booking_query_search |= Q(details__phone__contains=search)
                    #booking_query_search |= Q(customer__first_name__icontains=search)
                    #booking_query_search |= Q(customer__last_name__icontains=search)
                 
                    #if refund_status and canceled == 't':
                    booking_query &= Q(booking_query_search)
                    #sqlsearch = ' lower(parkstay_campground.name) LIKE lower(%(wildSearch)s)\
                    #or lower(parkstay_region.name) LIKE lower(%(wildSearch)s)\
                    #or lower(parkstay_booking.details->>\'first_name\') LIKE lower(%(wildSearch)s)\
                    #or lower(parkstay_booking.details->>\'last_name\') LIKE lower(%(wildSearch)s)\
                    #or lower(parkstay_booking.legacy_name) LIKE lower(%(wildSearch)s)\
                    #or lower(parkstay_booking.legacy_name) LIKE lower(%(wildSearch)s)'
                    #sqlParams['wildSearch'] = '%{}%'.format(search)
                    #if search.isdigit:
                    #    sqlsearch += ' or CAST (parkstay_booking.id as TEXT) like %(upperSearch)s'
                    #    sqlParams['upperSearch'] = '{}%'.format(search)

            recordsTotal = Booking.objects.all().count()
            filteredresultscount = Booking.objects.filter(booking_query).exclude(booking_type=3).count()
            #print (str(booking_query))
            lu = Booking.objects.all().values('updated').order_by('-updated')
            sorting_string = ','.join(sorting_fields)
            data_hash = hashlib.md5(str(str(booking_query)+':'+str(start)+':'+str(length)+":"+str(filteredresultscount)+':'+str(lu[0]['updated'])+':'+sorting_string).encode('utf-8')).hexdigest()
            jsonresults = cache.get('BookingViewSet'+data_hash)
            #bookings = None
            recordsFiltered = 0 
            jsonresults =None
            if jsonresults is None:
                bookings = Booking.objects.filter(booking_query).exclude(booking_type=3).order_by(*sorting_fields)
                if length == 'all':
                    bookings = bookings.values('id','arrival','departure','campground__id','booking_type','is_canceled','departure','created','customer__id','campground__name','canceled_by_id','campground__park__district__region__name','property_cache','send_invoice','cost_total','override_price','cancellation_reason','details','override_reason__text','override_reason_info','cancelation_time','property_cache_stale')
                else:
                    bookings = bookings.values('id','arrival','departure','campground__id','booking_type','is_canceled','departure','created','customer__id','campground__name','customer_id','canceled_by_id','campground__park__district__region__name','property_cache','send_invoice','cost_total','override_price','cancellation_reason','details','override_reason__text','override_reason_info','cancelation_time','property_cache_stale')[int(start):int(start)+int(length)]

                recordsFiltered = filteredresultscount
                filteredResults = []
                rowcount = 0
                for b in bookings:
                      editable = False
                      today = datetime.now().date()
                      discount = float('0.00')
                      if b['override_price']:
                         discount = float(b['cost_total']) - float(b['override_price'])
                        
                      if today <= b['departure']:
                          if not b['is_canceled']:
                              editable = True
                      if b['property_cache_stale'] is True:
                           property_cache.update_property_cache(b['id'])
                           bk = Booking.objects.get(id=b['id'])
                           pc = bk.property_cache
                           b['property_cache'] = pc

                      pc = b['property_cache']


                      try:
                            print (b['property_cache']['cache_version'])
                      except:
                            property_cache.update_property_cache(b['id'])
                            bk = Booking.objects.get(id=b['id'])
                            pc = bk.property_cache
                            b['property_cache'] = pc
                            cache.delete('BookingViewSet'+data_hash)
                      
                      if len(b['property_cache']) == 0 or 'cache_version' in b['property_cache']:
                            if 'cache_version' in b['property_cache']:
                                 if b['property_cache']['cache_version'] != settings.BOOKING_PROPERTY_CACHE_VERSION:
                                    property_cache.update_property_cache(b['id'])
                                    bk = Booking.objects.get(id=b['id'])
                                    pc = bk.property_cache
                                    b['property_cache'] = pc
                                    cache.delete('BookingViewSet'+data_hash)
                                 else:
                                      pass

                            else:
                                property_cache.update_property_cache(b['id'])
                                bk = Booking.objects.get(id=b['id'])
                                pc = bk.property_cache
                                b['property_cache'] = pc 
                                cache.delete('BookingViewSet'+data_hash)
                      row = {}
                      row['id'] = b['id']
                      row['arrival'] = str(b['arrival'])
                      row['departure'] = str(b['departure'])
                      #row['email'] = "CUSTOMER EMAIL" #b['customer__email']
                      row['created'] = str(b['created'])
                      row['campground_name'] = b['campground__name']
                      row['campground_region'] = b['campground__park__district__region__name']
                      row['editable'] = editable
                      row['status'] = b['property_cache']['status']
                      row['booking_type'] = b['booking_type']
                      row['has_history'] = b['property_cache']['has_history']
                      row['cost_total'] = float(b['cost_total'])
                      row['amount_paid'] = b['property_cache']['amount_paid']
                      ############### FIX FROM REAL DATA #######################
                      row['vehicle_payment_status'] =  []
                      if "vehicles" in b['property_cache']:
                          row['vehicle_payment_status'] = b['property_cache']['vehicles']

                      #row['vehicle_payment_status'] =  [{'Fee': False, 'Rego' : "1OT1KH", 'Type': "Vehicle", 'original_type' : "vehicle"}] #"Paid" #b['property_cache']['vehicle_payment_status']
                      ##########################################################
                      row['refund_status'] = b['property_cache']['refund_status'] 
                      row['is_canceled'] = 'Yes' if b['is_canceled'] else 'No'
                      row['cancelation_reason'] = b['cancellation_reason']
                      row['canceled_by'] = ''
                      row['cancelation_time'] = ''
                      if row['is_canceled'] == 'Yes':
                          row['canceled_by'] = "Cancelled By" #utils.clean_none_to_empty(b['canceled_by__first_name'])+' '+utils.clean_none_to_empty(b['canceled_by__last_name'])
                          row['cancelation_time'] = str(b['cancelation_time'])
                      row['paid'] = b['property_cache']['paid']  
                      row['invoices'] = b['property_cache']['invoices']
                      row['active_invoices'] = b['property_cache']['active_invoices']
                      row['guests'] = b['property_cache']['guests']
                      row['campsite_names'] = b['property_cache']['campsite_name_list'] #booking.campsite_name_list
                      row['regos'] = b['property_cache']['regos'] #[{r.type: r.rego} for r in booking.regos.all()]
                      row['firstname'] = b['details'].get('first_name','')
                      row['lastname'] = b['details'].get('last_name','')
                      row['override_reason'] = b['override_reason__text']
                      row['override_reason_info'] = b['override_reason_info']
                      row['send_invoice'] = b['send_invoice'] 
                      #if booking.override_price is not None and booking.override_price >= 0:
                      row['discount'] = discount
                      row['customer_account_phone'] = ''
                      row['customer_account_mobile'] = ''
                      row['customer_booking_phone'] = b['details'].get('phone','') 
                      row['email'] = ''
                      if b['property_cache']['customer_email'] is not None:
                           row['email'] = b['property_cache']['customer_email']
                      if b['property_cache']['customer_phone_number'] is not None:
                          row['phone'] = b['property_cache']['customer_phone_number'] 
                          row['customer_account_phone'] = b['property_cache']['customer_phone_number']
                      elif b['property_cache']['customer_mobile_number'] is not None:
                          row['phone'] = b['property_cache']['customer_mobile_number']
                          row['customer_account_mobile'] = b['property_cache']['customer_mobile_number']
                      else:
                          row['phone'] = ''

                      first_campsite_list = b['property_cache']['first_campsite_list2']
                      campground_site_type = []
                      for item in first_campsite_list:
                          campground_site_type.append({
                              "name": '{}'.format(item['name'] if item else ""),
                              "type": '{}'.format(item['type'] if item['type'] else ""),
                              "campground_type": item['site_type'],
                          })
                      row['campground_site_type'] = campground_site_type

                      rowcount = rowcount + 1
                      filteredResults.append(row)
                      if length != 'all': 
                          if rowcount > int(length):
                              break
                jsonresults = json.dumps({'filteredResults': filteredResults, 'recordsFiltered': recordsFiltered})
                cache.set('BookingViewSet'+data_hash, jsonresults, 604800)
            else:
                jsonresults = json.loads(jsonresults)
                filteredResults = jsonresults['filteredResults']
                recordsFiltered = jsonresults['recordsFiltered']

                #print (bookings)

                #canceled = 't' if canceled else 'f'
                #
                #sql = ''
                #http_status = status.HTTP_200_OK
                #sqlSelect = 'select parkstay_booking.id as id,parkstay_booking.created,parkstay_booking.customer_id, parkstay_campground.name as campground_name,parkstay_region.name as campground_region,parkstay_booking.legacy_name,\
                #    parkstay_booking.legacy_id,parkstay_campground.site_type as campground_site_type,\
                #    parkstay_booking.arrival as arrival, parkstay_booking.departure as departure,parkstay_campground.id as campground_id,coalesce(accounts_emailuser.first_name || \' \' || accounts_emailuser.last_name) as full_name'
                #sqlCount = 'select count(parkstay_booking.id)'

                #sqlFrom = ' from parkstay_booking\
                #    join parkstay_campground on parkstay_campground.id = parkstay_booking.campground_id\
                #    join parkstay_park on parkstay_campground.park_id = parkstay_park.id\
                #    join parkstay_district on parkstay_park.district_id = parkstay_district.id\
                #    full outer join accounts_emailuser on parkstay_booking.customer_id = accounts_emailuser.id\
                #    join parkstay_region on parkstay_district.region_id = parkstay_region.id\
                #    left outer join parkstay_campgroundgroup_campgrounds cg on cg.campground_id = parkstay_booking.campground_id\
                #    full outer join parkstay_campgroundgroup_members cm on cm.campgroundgroup_id = cg.campgroundgroup_id'

                #sql = sqlSelect + sqlFrom + " where "
                #sqlCount = sqlCount + sqlFrom + " where "
                #sqlParams = {}
                #print("MLINE 3.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                ## Filter the camgrounds that the current user is allowed to view
                #sqlFilterUser = ' cm.emailuser_id = %(user)s'
                #sql += sqlFilterUser
                #sqlCount += sqlFilterUser
                #sqlParams['user'] = request.user.id
                #if campground:
                #    sqlCampground = ' parkstay_campground.id = %(campground)s'
                #    sql = sql + " and " + sqlCampground
                #    sqlCount = sqlCount + " and " + sqlCampground
                #    sqlParams['campground'] = campground
                #if region:
                #    sqlRegion = " parkstay_region.id = %(region)s"
                #    sql = sql + " and " + sqlRegion
                #    sqlCount = sqlCount + " and " + sqlRegion
                #    sqlParams['region'] = region
                #if arrival:
                #    sqlArrival = ' parkstay_booking.departure > %(arrival)s'
                #    sqlCount = sqlCount + " and " + sqlArrival
                #    sql = sql + " and " + sqlArrival
                #    sqlParams['arrival'] = arrival
                #if departure:
                #    sqlDeparture = ' parkstay_booking.arrival <= %(departure)s'
                #    sqlCount = sqlCount + ' and ' + sqlDeparture
                #    sql = sql + ' and ' + sqlDeparture
                #    sqlParams['departure'] = departure
                ## Search for cancelled bookings
                #sql += ' and parkstay_booking.is_canceled = %(canceled)s'
                #sqlCount += ' and parkstay_booking.is_canceled = %(canceled)s'
                #sqlParams['canceled'] = canceled
                ## Remove temporary bookings
                #sql += ' and parkstay_booking.booking_type <> 3'
                #sqlCount += ' and parkstay_booking.booking_type <> 3'
                #if search:
                #    if search[:2] == 'PS':
                #        bid = search.replace("PS","")
                #        sqlsearch = "parkstay_booking.id = '"+bid+"' " 
                #    else:
                #        sqlsearch = ' lower(parkstay_campground.name) LIKE lower(%(wildSearch)s)\
                #        or lower(parkstay_region.name) LIKE lower(%(wildSearch)s)\
                #        or lower(parkstay_booking.details->>\'first_name\') LIKE lower(%(wildSearch)s)\
                #        or lower(parkstay_booking.details->>\'last_name\') LIKE lower(%(wildSearch)s)\
                #        or lower(parkstay_booking.legacy_name) LIKE lower(%(wildSearch)s)\
                #        or lower(parkstay_booking.legacy_name) LIKE lower(%(wildSearch)s)'
                #        sqlParams['wildSearch'] = '%{}%'.format(search)
                #        if search.isdigit:
                #            sqlsearch += ' or CAST (parkstay_booking.id as TEXT) like %(upperSearch)s'
                #            sqlParams['upperSearch'] = '{}%'.format(search)

                #    sql += " and ( " + sqlsearch + " )"
                #    sqlCount += " and  ( " + sqlsearch + " )"

                #sql += ' ORDER BY parkstay_booking.arrival DESC'

                #if length != 'all':
                #    sql = sql + ' limit %(length)s offset %(start)s'
                #    sqlParams['length'] = length
                #    sqlParams['start'] = start

                #if length == 'all':
                #    sql = sql + ' limit %(length)s offset %(start)s'
                #    sqlParams['length'] = 2000
                #    sqlParams['start'] = start

                #sql += ';'
                #print("MLINE 4.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #cursor = connection.cursor()
                ##cursor.execute("Select count(*) from parkstay_booking ")
                #recordsTotal = Booking.objects.all().count()
                ##recordsTotal = cursor.fetchone()[0]

                #cursor.execute(sqlCount, sqlParams)
                #print("MLINE 5.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #recordsFiltered = cursor.fetchone()[0]
                #cursor.execute(sql, sqlParams)
                #print("MLINE 6.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

                #columns = [col[0] for col in cursor.description]
                #data = [
                #    dict(zip(columns, row))
                #    for row in cursor.fetchall()
                #]
                #print("MLINE 7.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                ##for b in data:
                ##   print (b['id'])
                #sql_id=Q()
                #for b in data:
                #    sql_id |= Q(id=b['id'])
                #bookings_qs = Booking.objects.filter(sql_id).prefetch_related('campground', 'campsites', 'campsites__campsite', 'customer', 'regos', 'history', 'invoices', 'canceled_by')
                ##bookings_qs = Booking.objects.filter(id__in=[b['id'] for b in data]) #.values('id','campground', 'campsites', 'campsites__campsite', 'customer', 'regos', 'history', 'invoices', 'canceled_by')
                #booking_map = {b.id: b for b in bookings_qs}
                #clean_data = []
                #print("MLINE 8.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))  

                #for bk in data:
                #    print("MLINE 9.00", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    cg = None
                #    booking = booking_map[bk['id']]
                #    #cg = booking.campground
                #    get_property_cache = booking.get_property_cache()
                #    if 'active_invoices' not in get_property_cache or 'invoices' not in get_property_cache or 'first_campsite_list2' not in get_property_cache:
                #         print ("Sending Update Cache Request")
                #         get_property_cache = booking.update_property_cache()

                #    print("MLINE 9.01", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    bk['editable'] = booking.editable
                #    bk['status'] = get_property_cache['status'] #booking.status
                #    bk['booking_type'] = booking.booking_type
                #    bk['has_history'] = get_property_cache['has_history'] #booking.has_history
                #    print("MLINE 9.11", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    bk['cost_total'] = booking.cost_total
                #    bk['amount_paid'] = get_property_cache['amount_paid'] #booking.amount_paid
                #    bk['vehicle_payment_status'] = get_property_cache['vehicle_payment_status'] #booking.vehicle_payment_status
                #    bk['refund_status'] = get_property_cache['refund_status'] #booking.refund_status
                #    bk['is_canceled'] = 'Yes' if booking.is_canceled else 'No'
                #    print("MLINE 9.21", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    bk['cancelation_reason'] = booking.cancellation_reason
                #    bk['canceled_by'] = '' #booking.canceled_by.get_full_name() if booking.canceled_by else ''
                #    bk['cancelation_time'] = booking.cancelation_time if booking.cancelation_time else ''
                #    bk['paid'] = get_property_cache['paid']  #booking.paid
                #    bk['invoices'] = get_property_cache['invoices'] #[i.invoice_reference for i in booking.invoices.all()]
                #    print("MLINE 9.31", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    bk['active_invoices'] = get_property_cache['active_invoices']  #[i.invoice_reference for i in booking.invoices.all() if i.active]
                #    bk['guests'] = booking.guests
                #    bk['campsite_names'] = get_property_cache['campsite_name_list'] #booking.campsite_name_list
                #    print("MLINE 9.41", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    bk['regos'] = get_property_cache['regos'] #[{r.type: r.rego} for r in booking.regos.all()]
                #    bk['firstname'] = booking.details.get('first_name', '')
                #    bk['lastname'] = booking.details.get('last_name', '')
                #    print("MLINE 9.51", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    if booking.override_reason:
                #        bk['override_reason'] = booking.override_reason.text
                #    if booking.override_reason_info:
                #        bk['override_reason_info'] = booking.override_reason_info
                #    if booking.send_invoice:
                #        bk['send_invoice'] = booking.send_invoice
                #    if booking.override_price is not None and booking.override_price >= 0:
                #        bk['discount'] = booking.discount
                #    if not get_property_cache['paid']: #booking.paid:
                #        bk['payment_callback_url'] = '/api/booking/{}/payment_callback.json'.format(booking.id)
                #    print("MLINE 9.61", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    if booking.customer:
                #        bk['email'] = booking.customer.email if booking.customer and booking.customer.email else ""
                #        if booking.customer.phone_number:
                #            bk['phone'] = booking.customer.phone_number
                #        elif booking.customer.mobile_number:
                #            bk['phone'] = booking.customer.mobile_number
                #        else:
                #            bk['phone'] = ''
                #        if booking.is_canceled:
                #            bk['campground_site_type'] = ""
                #        else:
                #            first_campsite_list = get_property_cache['first_campsite_list2']
                #            campground_site_type = []
                #            for item in first_campsite_list:
                #                campground_site_type.append({
                #                    "name": '{}'.format(item['name'] if item else ""),
                #                    "type": '{}'.format(item['type'] if item['type'] else ""),
                #                    "campground_type": item['site_type'],
                #                })
                #            bk['campground_site_type'] = campground_site_type
                #    else:
                #        bk['campground_site_type'] = ""
                #    print("MLINE 9.71", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                #    if refund_status and canceled == 't':
                #        refund_statuses = ['All', 'Partially Refunded', 'Not Refunded', 'Refunded']
                #        if refund_status in refund_statuses:
                #            if refund_status == 'All':
                #                clean_data.append(bk)
                #            else:
                #                if refund_status == get_property_cache['refund_status']: #booking.refund_status:
                #                    clean_data.append(bk)
                #    else:
                #        clean_data.append(bk)
                #    print("MLINE 9.81", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            return Response(OrderedDict([
                ('config', {'ledger_url': settings.LEDGER_UI_URL }),
                ('recordsTotal', recordsTotal),
                ('recordsFiltered', recordsFiltered),
                ('results', filteredResults)
            ]), status=status.HTTP_200_OK)
            print("MLINE 9.91", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def create(self, request, format=None):
        userCreated = False

        try:
            if 'ps_booking' in request.session:
                del request.session['ps_booking']
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            start_date = serializer.validated_data['arrival']
            end_date = serializer.validated_data['departure']
            guests = request.data['guests']
            costs = request.data['costs']
            regos = request.data['regos']
            override_price = serializer.validated_data.get('override_price', None)
            override_reason = serializer.validated_data.get('override_reason', None)
            override_reason_info = serializer.validated_data.get('override_reason_info', None)
            do_not_send_invoice = serializer.validated_data.get('do_not_send_invoice', True)
            overridden_by = None if (override_price is None) else request.user

            try:
                emailUser = request.data['customer']
                customer = EmailUser.objects.get(email=emailUser['email'].lower())
            except EmailUser.DoesNotExist:
                customer = EmailUser.objects.create(
                    email=emailUser['email'].lower(),
                    first_name=emailUser['first_name'],
                    last_name=emailUser['last_name'],
                    phone_number=emailUser['phone'],
                    mobile_number=emailUser['phone'],
                )
                userCreated = True
                try:
                    country = emailUser['country']
                    country = Country.objects.get(iso_3166_1_a2=country)
                    Address.objects.create(line1='address', user=customer, postcode=emailUser['postcode'], country=country.iso_3166_1_a2)
                except Country.DoesNotExist:
                    raise serializers.ValidationError("Country you have entered does not exist")

            booking_details = {
                'campsites': Campsite.objects.filter(id__in=request.data['campsites']),
                'start_date': start_date,
                'end_date': end_date,
                'num_adult': guests['adult'],
                'num_concession': guests['concession'],
                'num_child': guests['child'],
                'num_infant': guests['infant'],
                'cost_total': costs['total'],
                'override_price': override_price,
                'override_reason': override_reason,
                'override_reason_info': override_reason_info,
                'do_not_send_invoice': do_not_send_invoice,
                'send_invoice': False,
                'overridden_by': overridden_by,
                'customer': customer,
                'first_name': emailUser['first_name'],
                'last_name': emailUser['last_name'],
                'country': emailUser['country'],
                'postcode': emailUser['postcode'],
                'phone': emailUser['phone'],
                'regos': regos
            }

            data = utils.internal_booking(request, booking_details)
            serializer = self.get_serializer(data)
            return Response(serializer.data)
        except serializers.ValidationError:
            utils.delete_session_booking(request.session)
            if userCreated:
                customer.delete()
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(str(e))
        except Exception as e:
            utils.delete_session_booking(request.session)
            if userCreated:
                customer.delete()
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def update(self, request, *args, **kwargs):
        try:
            http_status = status.HTTP_200_OK

            instance = self.get_object()
            start_date = datetime.strptime(request.data['arrival'], '%d/%m/%Y').date()
            end_date = datetime.strptime(request.data['departure'], '%d/%m/%Y').date()
            guests = request.data['guests']
            booking_details = {
                'campsites': request.data['campsites'],
                'start_date': start_date,
                'campground': request.data['campground'],
                'end_date': end_date,
                'num_adult': guests['adults'],
                'num_concession': guests['concession'],
                'num_child': guests['children'],
                'num_infant': guests['infants'],
                'regos': request.data['entryFees']['regos'],
            }
            data = utils.update_booking(request, instance, booking_details)
            serializer = BookingSerializer(data)
            return Response(serializer.data, status=http_status)

        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            if hasattr(e, 'error_dict'):
                raise serializers.ValidationError(repr(e.error_dict))
            else:
                raise serializers.ValidationError(repr(e[0].encode('utf-8')))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def destroy(self, request, *args, **kwargs):

        http_status = status.HTTP_200_OK
        try:
            reason = request.GET.get('reason', None)
            if not reason:
                raise serializers.ValidationError('A reason is needed before canceling a booking')
            booking = self.get_object()
            booking.cancelBooking(reason, user=request.user)
            emails.send_booking_cancelation(booking, request)
            serializer = self.get_serializer(booking)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(permission_classes=[PaymentCallbackPermission], methods=['GET', 'POST'], detail=True)
    def payment_callback(self, request, *args, **kwargs):
        http_status = status.HTTP_200_OK
        try:
            response = {
                'status': 'rejected',
                'error': ''
            }
            if request.method == 'GET':
                response = {'status': 'accessible'}
            elif request.method == 'POST':
                instance = self.get_object()

                invoice_ref = request.data.get('invoice', None)
                if invoice_ref:
                    try:
                        invoice = Invoice.objects.get(reference=invoice_ref)
                        if invoice.payment_status in ['paid', 'over_paid']:
                            # Get the latest cash payment and see if it was paid in the last 1 minute
                            latest_cash = invoice.cash_transactions.last()
                            # Check if the transaction came in the last 10 seconds
                            if (timezone.now() - latest_cash.created).seconds < 10 and instance.paid:
                                # Send out the confirmation pdf
                                instance.confirmation_sent = False
                                instance.save()
                                #emails.send_booking_confirmation(instance, request)
                            else:
                                response['error'] = 'Booking is not fully paid or the transaction was not done in the last 10 secs'
                        else:
                            response['error'] = 'Invoice is not fully paid'

                    except Invoice.DoesNotExist:
                        response['error'] = 'Invoice was not found'
                else:
                    response['error'] = 'Invoice was not found'

                response['status'] = 'approved'
            return Response(response, status=status.HTTP_200_OK)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(permission_classes=[], methods=['GET'], detail=True)
    def booking_checkout_status(self, request, *args, **kwargs):
        from django.utils import timezone
        http_status = status.HTTP_200_OK
        try:
            instance = self.get_object()
            response = {
                'status': 'rejected',
                'error': ''
            }
            # Check the type of booking
            if instance.booking_type != 3:
                response['error'] = 'This booking has already been paid for'
                return Response(response, status=status.HTTP_200_OK)
            # Check if the time for the booking has elapsed
            if instance.expiry_time <= timezone.now():
                response['error'] = 'This booking has expired'
                return Response(response, status=status.HTTP_200_OK)
            # if all is well
            response['status'] = 'approved'
            return Response(response, status=status.HTTP_200_OK)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['GET'], detail=True)
    def history(self, request, *args, **kwargs):
        http_status = status.HTTP_200_OK
        try:
            history = self.get_object().history.all()
            data = BookingHistorySerializer(history, many=True).data
            return Response(data, status=status.HTTP_200_OK)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))


class CampsiteRateViewSet(viewsets.ModelViewSet):
    queryset = CampsiteRate.objects.all()
    serializer_class = CampsiteRateSerializer
    permission_classes = [OfficerPermission]

    def create(self, request, format=None):
        try:
            http_status = status.HTTP_200_OK
            rate = None
            rate_serializer = RateDetailSerializer(data=request.data)
            rate_serializer.is_valid(raise_exception=True)
            rate_id = rate_serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=rate_serializer.validated_data['adult'], concession=rate_serializer.validated_data['concession'], child=rate_serializer.validated_data['child'])[0]
            if rate:
                booking_policy_obj = models.BookingPolicy.objects.get(id=request.data['booking_policy'])
                data = {
                    'rate': rate.id,
                    'date_start': rate_serializer.validated_data['period_start'],
                    'campsite': rate_serializer.validated_data['campsite'],
                    'reason': rate_serializer.validated_data['reason'],
                    'update_level': 2,
                    'booking_policy': request.data['booking_policy'] 
                }
                serializer = self.get_serializer(data=data)
                serializer.is_valid(raise_exception=True)
                res = serializer.save()

                serializer = CampsiteRateReadonlySerializer(res)
                return Response(serializer.data, status=http_status)

        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    def update(self, request, *args, **kwargs):
        try:
            http_status = status.HTTP_200_OK
            rate = None
            rate_serializer = RateDetailSerializer(data=request.data)
            rate_serializer.is_valid(raise_exception=True)
            rate_id = rate_serializer.validated_data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=rate_serializer.validated_data['adult'], concession=rate_serializer.validated_data['concession'], child=rate_serializer.validated_data['child'])[0]
                pass
            if rate:
                data = {
                    'rate': rate.id,
                    'date_start': rate_serializer.validated_data['period_start'],
                    'campsite': rate_serializer.validated_data['campsite'],
                    'reason': rate_serializer.validated_data['reason'],
                    'booking_policy': request.data['booking_policy'],
                    'update_level': 2
                }
                instance = self.get_object()
                partial = kwargs.pop('partial', False)
                serializer = self.get_serializer(instance, data=data, partial=partial)
                serializer.is_valid(raise_exception=True)
                self.perform_update(serializer)

                return Response(serializer.data, status=http_status)

        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))


class BookingRangeViewset(viewsets.ModelViewSet):
    permission_classes = [OfficerPermission]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        original = bool(request.GET.get("original", False))
        serializer = self.get_serializer(instance, original=original, method='get')
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            if instance.range_end and not serializer.validated_data.get('range_end'):
                instance.range_end = None
            self.perform_update(serializer)

            return Response(serializer.data)
        except serializers.ValidationError:
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            raise serializers.ValidationError(str(e))


class CampgroundBookingRangeViewset(BookingRangeViewset):
    queryset = CampgroundBookingRange.objects.all()
    serializer_class = CampgroundBookingRangeSerializer


class CampsiteBookingRangeViewset(BookingRangeViewset):
    queryset = CampsiteBookingRange.objects.all()
    serializer_class = CampsiteBookingRangeSerializer


class RateViewset(viewsets.ModelViewSet):
    queryset = Rate.objects.all()
    serializer_class = RateSerializer
    permission_classes = [OfficerPermission]

# Reasons
# =========================


class ClosureReasonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ClosureReason.objects.all()
    serializer_class = ClosureReasonSerializer


class PriceReasonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PriceReason.objects.all()
    serializer_class = PriceReasonSerializer


class MaximumStayReasonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MaximumStayReason.objects.all()
    serializer_class = MaximumStayReasonSerializer


class DiscountReasonViewset(viewsets.ReadOnlyModelViewSet):
    queryset = DiscountReason.objects.all()
    serializer_class = DiscountReasonSerializer


class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Country.objects.order_by('-display_order', 'printable_name')
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticated]


class UsersViewSet(viewsets.ModelViewSet):
    queryset = EmailUser.objects.all()
    serializer_class = UsersSerializer

    def list(self, request, *args, **kwargs):
        start = request.GET.get('start') if request.GET.get('draw') else 1
        length = request.GET.get('length') if request.GET.get('draw') else 10
        q = request.GET.get('q')
        if q:
            queryset = EmailUser.objects.filter(email__icontains=q)[:10]
        else:
            queryset = self.get_queryset()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @detail_route(methods=['POST', ], detail=True)
    def update_personal(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = PersonalSerializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['POST', ], detail=True)
    def update_contact(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = UserContactSerializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))

    @detail_route(methods=['POST', ], detail=True)
    def update_address(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = UserAddressSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            address, created = Address.objects.get_or_create(
                line1=serializer.validated_data['line1'],
                locality=serializer.validated_data['locality'],
                state=serializer.validated_data['state'],
                country=serializer.validated_data['country'],
                postcode=serializer.validated_data['postcode'],
                user=instance
            )
            instance.residential_address = address
            instance.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))
# Bulk Pricing
# ===========================


class BulkPricingView(generics.CreateAPIView):
    serializer_class = BulkPricingSerializer
    renderer_classes = (JSONRenderer,)
    permission_classes = [OfficerPermission,]

    def create(self, request, *args, **kwargs):
        try:
            http_status = status.HTTP_200_OK
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            rate_id = serializer.data.get('rate', None)
            if rate_id:
                try:
                    rate = Rate.objects.get(id=rate_id)
                except Rate.DoesNotExist as e:
                    raise serializers.ValidationError('The selected rate does not exist')
            else:
                rate = Rate.objects.get_or_create(adult=serializer.validated_data['adult'], concession=serializer.validated_data['concession'], child=serializer.validated_data['child'])[0]
            if rate:
                data = {
                    'rate': rate,
                    'date_start': serializer.validated_data['period_start'],
                    'reason': PriceReason.objects.get(pk=serializer.data['reason']),
                    'details': serializer.validated_data.get('details', None)
                }
            if serializer.data['type'] == 'Park':
                for c in serializer.data['campgrounds']:
                    data['update_level'] = 0
                    Campground.objects.get(pk=c).createCampsitePriceHistory(data)
            elif serializer.data['type'] == 'Campsite Type':
                data['update_level'] = 1
                CampsiteClass.objects.get(pk=serializer.data['campsiteType']).createCampsitePriceHistory(data)

            return Response(serializer.data, status=http_status)

        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e[0]))


class BookingRefundsReportView(views.APIView):
    renderer_classes = (JSONRenderer,)
    permission_classes = [OfficerPermission,]

    def get(self, request, format=None):
        try:
            http_status = status.HTTP_200_OK
            # parse and validate data
            report = None
            data = {
                "start": request.GET.get('start'),
                "end": request.GET.get('end'),
            }
            serializer = ReportSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            filename = 'Booking Refunds Report-{}-{}'.format(str(serializer.validated_data['start']), str(serializer.validated_data['end']))
            # Generate Report
            report = reports.booking_refunds(serializer.validated_data['start'], serializer.validated_data['end'])
            if report:
                response = HttpResponse(FileWrapper(report), content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(filename)
                return response
            else:
                raise serializers.ValidationError('No report was generated.')
        except serializers.ValidationError:
            raise
        except Exception as e:
            traceback.print_exc()


class BookingSettlementReportView(views.APIView):
    renderer_classes = (JSONRenderer,)    
    permission_classes = [OfficerPermission,]

    def get(self, request, format=None):
        try:
            http_status = status.HTTP_200_OK
            # parse and validate data
            report = None
            data = {
                "date": request.GET.get('date'),
            }
            serializer = BookingSettlementReportSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            filename = 'Booking Settlement Report-{}'.format(str(serializer.validated_data['date']))
            # Generate Report
            report = reports.booking_bpoint_settlement_report(serializer.validated_data['date'])
            if report:
                response = HttpResponse(FileWrapper(report), content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(filename)
                return response
            else:
                raise serializers.ValidationError('No report was generated.')
        except serializers.ValidationError:
            raise
        except Exception as e:
            traceback.print_exc()


class BookingReportView(views.APIView):
    renderer_classes = (JSONRenderer,)
    permission_classes = [OfficerPermission,]
    
    def get(self, request, format=None):
        try:
            http_status = status.HTTP_200_OK
            # parse and validate data
            report = None
            data = {
                "date": request.GET.get('date'),
            }
            serializer = BookingSettlementReportSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            filename = 'Booking Report-{}'.format(str(serializer.validated_data['date']))
            # Generate Report
            report = reports.bookings_report(serializer.validated_data['date'])
            if report:
                response = HttpResponse(FileWrapper(report), content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(filename)
                return response
            else:
                raise serializers.ValidationError('No report was generated.')
        except serializers.ValidationError:
            raise
        except Exception as e:
            traceback.print_exc()


class GetProfile(views.APIView):
    renderer_classes = [JSONRenderer, ]
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        # Check if the user has any address and set to residential address
        user = request.user
        if not user.residential_address:
            user.residential_address = user.profile_addresses.first() if user.profile_addresses.all() else None
            user.save()
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class GetServerDate(views.APIView):
    """Returns the server current datetime (TZ-aware) in order to restrict dates in frontend
    calendar components independent of client timezone.
    """
    renderer_classes = [JSONRenderer, ]
    permission_classes = []

    def get(self, request, format=None):
        return Response(timezone.make_aware(datetime.now()).isoformat())


class UpdateProfilePersonal(views.APIView):
    renderer_classes = [JSONRenderer, ]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            instance = request.user
            serializer = PersonalSerializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))


class UpdateProfileContact(views.APIView):
    renderer_classes = [JSONRenderer, ]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            instance = request.user
            serializer = PhoneSerializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))


class UpdateProfileAddress(views.APIView):
    renderer_classes = [JSONRenderer, ]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            instance = request.user
            serializer = UserAddressSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            address, created = Address.objects.get_or_create(
                line1=serializer.validated_data.get('line1'),
                locality=serializer.validated_data.get('locality'),
                state=serializer.validated_data.get('state'),
                country=serializer.validated_data.get('country'),
                postcode=serializer.validated_data.get('postcode'),
                user=instance
            )
            instance.residential_address = address
            instance.save()
            serializer = UserSerializer(instance)
            return Response(serializer.data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e))


class OracleJob(views.APIView):
    renderer_classes = [JSONRenderer, ]
    permission_classes = [OfficerPermission,]

    def get(self, request, format=None):
        try:
            data = {
                "date": request.GET.get("date"),
                "override": request.GET.get("override")
            }
            serializer = OracleSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            utils.oracle_integration(serializer.validated_data['date'].strftime('%Y-%m-%d'), serializer.validated_data['override'])
            data = {'successful': True}
            return Response(data)
        except serializers.ValidationError:
            print(traceback.print_exc())
            raise
        except ValidationError as e:
            raise serializers.ValidationError(repr(e.error_dict))
        except Exception as e:
            print(traceback.print_exc())
            raise serializers.ValidationError(str(e[0]))
