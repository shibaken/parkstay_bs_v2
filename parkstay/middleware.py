import re
import datetime
from django.contrib import messages

#from django.core.urlresolvers import reverse
from django.urls import reverse
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.utils import timezone
from parkstay.models import Booking
import hashlib

CHECKOUT_PATH = re.compile('^/ledger-api')
PROCESS_PAYMENT =  re.compile('^/ledger-api/process-payment')
TOKEN_CHECKOUT_PATH = re.compile('^/ledger-api/create-token-session')

class BookingTimerMiddleware(object):

    def __init__(self, get_response):            
            self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Run before executing any function code

        if 'ps_booking' in request.session:               
               if "token_payment_session" in request.session:
                    del request.session["token_payment_session"]
               if request.path.startswith("/ledger-api/process-payment") or request.path.startswith('/ledger-api/payment-details'):                                       
                    checkouthash =  hashlib.sha256(str(request.session["ps_booking"]).encode('utf-8')).hexdigest()
                    checkouthash_cookie = request.COOKIES.get('checkouthash')
                    print ("MIDDLE 1")
                    print (request.session['ps_booking'])
                    print (checkouthash_cookie)
                    print (checkouthash)
                    total_booking = Booking.objects.filter(pk=request.session['ps_booking']).count()
                    if checkouthash_cookie != checkouthash or total_booking == 0:                         
                         # messages.error(request, "There was a booking mismatch issue while trying to complete your booking, your inprogress booking has been cancelled and will need to be completed again.  This can sometimes be caused by using multiple browser tabs and recommend only to complete a booking using one browser tab window. ")          
                         # return HttpResponseRedirect("/")  
                         print ("MIDDLE 2")
                         url_redirect = reverse('public_make_booking')
                         response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                         return response          
        else:
               if request.path.startswith("/ledger-api/process-payment") and not "token_payment_session" in request.session:
                    # booking as expired or session been removed
                    url_redirect = reverse('public_make_booking')
                    response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                    return response             
        return None

    def __call__(self, request):            
            # Run after executing any function code
            return self.pr(request)

    def pr(self, request):
        response= self.get_response(request)
        if request.path.startswith('/static') or request.path.startswith('/favicon') or request.path.startswith('/media') or request.path.startswith('/api') or request.path.startswith('/search-availability/information/') or request.path.startswith('/search-availability/campground/') or request.path.startswith('/campground-image') or request.path == '/':
             if "token_payment_session" in request.session:
                  del request.session["token_payment_session"]
        else:
            if 'ps_booking' in request.session:
                if "token_payment_session" in request.session:
                    del request.session["token_payment_session"]
                try:
                    booking = Booking.objects.get(pk=request.session['ps_booking'])
                except:
                    # no idea what object is in self.request.session['ps_booking'], ditch it
                    del request.session['ps_booking']
                    return response
                #if booking.booking_type != 3:
                #    # booking in the session is not a temporary type, ditch it
                #    del request.session['ps_booking']
                if booking.expiry_time is not None:
                    if timezone.now() > booking.expiry_time and booking.booking_type == 3:
                    # expiry time has been hit, destroy the Booking then ditch it
                    #booking.delete()
                        del request.session['ps_booking']

                if request.path.startswith("/ledger-api/process-payment") or request.path.startswith('/ledger-api/payment-details'):      
                    
                    if "ps_booking" not in request.session:
                         url_redirect = reverse('public_make_booking')
                         response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                         return response    

                    checkouthash =  hashlib.sha256(str(request.session["ps_booking"]).encode('utf-8')).hexdigest() 

                    checkouthash_cookie = request.COOKIES.get('checkouthash')
                    total_booking = Booking.objects.filter(pk=request.session['ps_booking']).count()
                    if checkouthash_cookie != checkouthash or total_booking == 0:                         
                         # messages.error(request, "There was a booking mismatch issue while trying to complete your booking, your inprogress booking has been cancelled and will need to be completed again.  This can sometimes be caused by using multiple browser tabs and recommend only to complete a booking using one browser tab window. ")          
                         # return HttpResponseRedirect("/")  
                         url_redirect = reverse('public_make_booking')
                         response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                         return response                                                                                                 

                if CHECKOUT_PATH.match(request.path) and request.method == 'POST' and booking.booking_type == 3:
                    # safeguard against e.g. part 1 of the multipart checkout confirmation process passing, then part 2 timing out.
                    # on POST boosts remaining time to at least 2 minutes
                    booking.expiry_time = max(booking.expiry_time, timezone.now()+datetime.timedelta(minutes=2))
                    booking.save()
            else:
                 if request.path.startswith("/ledger-api/process-payment") and not "token_payment_session" in request.session:
                    # booking as expired or session been removed
                    url_redirect = reverse('public_make_booking')
                    response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                    return response

            # force a redirect if in the checkout
            if ('ps_booking_internal' not in request.COOKIES) and CHECKOUT_PATH.match(request.path):
                if ('ps_booking' not in request.session) and CHECKOUT_PATH.match(request.path) and ('payment_session' not in request.session) and not TOKEN_CHECKOUT_PATH.match(request.path):
                    url_redirect = reverse('public_make_booking')
                    response = HttpResponse("<script> window.location='"+url_redirect+"';</script> <center><div class='container'><div class='alert alert-primary' role='alert'><a href='"+url_redirect+"'> Redirecting please wait: "+url_redirect+"</a><div></div></center>")
                    return response
                    #return HttpResponseRedirect(reverse('public_make_booking'))
               
                #parkstay request.session for token-based payment to prevent redirect (delete on non-relevant requests)
                else:
                    if TOKEN_CHECKOUT_PATH.match(request.path):
                         request.session["token_payment_session"] = request.GET.get("token")
                    return response
        return response


class CacheControl(object):

    def __init__(self, get_response):
            self.get_response = get_response

    def __call__(self, request):
       response= self.get_response(request)

       if request.path == '/':
            response['Cache-Control'] = 'public, max-age=60'
       elif request.path == '/map/':
            response['Cache-Control'] = 'public, max-age=300'
       elif request.path[:19] == '/api/search_suggest':
            response['Cache-Control'] = 'public, max-age=300'
       elif request.path[:12] == '/api/places/':
            response['Cache-Control'] = 'public, max-age=300'
       elif request.path[:20] == '/api/campground_map/':
            response['Cache-Control'] = 'public, max-age=300'
       elif request.path[:17] == '/campground-image':
            response['Cache-Control'] = 'public, max-age=3600'
       elif request.path[:31] == '/api/campsite_availablity_view/':
            response['Cache-Control'] = 'private, no-store'
       elif request.path[:5] == '/api/':
            response['Cache-Control'] = 'private, no-store'
            #response['Cache-Control'] = 'public, max-age=60'
       elif request.path[:8] == '/static/':
            response['Cache-Control'] = 'public, max-age=3600'
       elif request.path[:7] == '/media/':
            response['Cache-Control'] = 'public, max-age=3600'
       else:
            pass
            #response['Cache-Control'] = 'private, no-store'
       return response
    #def patch_response_headers(response, cache_timeout=None):
        #response['Cache-Control'] = 'private, no-store'
        #patch_cache_control(response, max_age=cache_timeout)        
    #def process_response(self, request, response):
        #print ("PATH")
        #print (request.path)
        #response['Cache-Control'] = 'private, no-store'
        #return add_cache_control(response)
