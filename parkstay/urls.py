from django.conf import settings
# from django.conf.urls import url, include
from django.urls import include, re_path
from django.conf.urls.static import static
from rest_framework import routers
from parkstay import views, api
from parkstay.admin import admin
from parkstay import view_file
from django.contrib.auth.views import LogoutView, LoginView

#from ledger.urls import urlpatterns as ledger_patterns
from ledger_api_client.urls import urlpatterns as ledger_patterns
from django_media_serv.urls import urlpatterns as media_serv_patterns
from django.urls import path

#from django_site_queue import urls as site_queue_urls

# API patterns
router = routers.DefaultRouter()
router.include_root_view = settings.SHOW_API_ROOT

#router.register(r'campground_map', api.CampgroundMapViewSet)
router.register(r'campground_map_filter', api.CampgroundMapFilterViewSet)
router.register(r'availability', api.AvailabilityViewSet, 'availability')
router.register(r'availability_admin', api.AvailabilityAdminViewSet, basename="api_campgrounds_avail_admin")
router.register(r'availability_ratis', api.AvailabilityRatisViewSet, 'availability_ratis')
router.register(r'campgrounds', api.CampgroundViewSet, basename="api_campgrounds")
router.register(r'campsites', api.CampsiteViewSet)
router.register(r'campsite_bookings', api.CampsiteBookingViewSet)
router.register(r'promo_areas', api.PromoAreaViewSet)
router.register(r'parks', api.ParkViewSet)
router.register(r'parkentryrate', api.ParkEntryRateViewSet)
router.register(r'features', api.FeatureViewSet)
router.register(r'regions', api.RegionViewSet)
router.register(r'districts', api.DistrictViewSet)
router.register(r'campsite_classes', api.CampsiteClassViewSet)
router.register(r'booking', api.BookingViewSet)
router.register(r'campground_booking_ranges', api.CampgroundBookingRangeViewset)
router.register(r'campsite_booking_ranges', api.CampsiteBookingRangeViewset)
router.register(r'campsite_rate', api.CampsiteRateViewSet)
router.register(r'campsites_stay_history', api.CampsiteStayHistoryViewSet)
router.register(r'campground_stay_history', api.CampgroundStayHistoryViewSet)
router.register(r'rates', api.RateViewset)
router.register(r'closureReasons', api.ClosureReasonViewSet)
router.register(r'priceReasons', api.PriceReasonViewSet)
router.register(r'maxStayReasons', api.MaximumStayReasonViewSet)
#router.register(r'users', api.UsersViewSet)
router.register(r'contacts', api.ContactViewSet)
router.register(r'countries', api.CountryViewSet)
router.register(r'discountReasons', api.DiscountReasonViewset)

# To test sentry
def trigger_error(request):
    division_by_zero = 1 / 0  # noqa

api_patterns = [
    re_path(r'^api/profile$', api.GetProfile.as_view(), name='get-profile'),
    #url(r'^api/profile/update_personal$', api.UpdateProfilePersonal.as_view(), name='update-profile-personal'),
    #url(r'^api/profile/update_contact$', api.UpdateProfileContact.as_view(), name='update-profile-contact'),
    #url(r'^api/profile/update_address$', api.UpdateProfileAddress.as_view(), name='update-profile-address'),
    re_path(r'^api/oracle_job$', api.OracleJob.as_view(), name='get-oracle'),
    re_path(r'^api/bulkPricing', api.BulkPricingView.as_view(), name='bulkpricing-api'),
    re_path(r'^api/campground_availabilty_view/', api.campground_availabilty_view, name='campground_availabilty_view'),
    re_path(r'^api/campsite_availablity_view/(?P<campground_id>[0-9]+)/', api.campsite_availablity_view, name='campsite_availablity_view'),
    re_path(r'^api/search_suggest', api.search_suggest, name='search_suggest'),
    re_path(r'^api/get_date_diff_in_days', api.get_date_diff_in_days, name='get_date_diff_in_days'),    
    re_path(r'^api/create_booking', api.create_booking, name='create_booking'),
    re_path(r'^api/complete_booking/(?P<booking_hash>[\w]+)/(?P<booking_id>[0-9]+)/', api.complete_booking, name='complete_booking'),
    re_path(r'^api/campground_map/$', api.campground_map_view, name='campground_map'),
    re_path(r'^api/places/', api.places, name='places'),
    re_path(r'^api/booking_pricing/$', api.get_booking_pricing, name='booking_pricing'),
    re_path(r'^api/booking_updates/$', api.booking_updates,  name='booking_updates'),
    re_path(r'^api/booking_vehicle_update/$', api.booking_vehicle_update,  name='update_booking_vehicle_info'),
    re_path(r'^api/get_booking_vehicle_info/(?P<booking_id>[0-9]+)/$', api.get_booking_vehicle_info, name='get_booking_vehicle_info'),
    re_path(r'^api/peak_groups/', api.peak_groups, name='peak_groups'),
    re_path(r'^api/bulk_refund/', api.bulk_refund, name='bulk_refund'),
    re_path(r'^api/save_peak_group/', api.save_peak_group, name='peak_group_save'),
    re_path(r'^api/save_peak_period/', api.save_peak_period, name='save_peak_period'),
    re_path(r'^api/save_booking_policy/', api.save_booking_policy, name='save_booking_policy'),
    re_path(r'^api/save_bulk_refund_period/', api.save_bulk_refund_period, name='save_bulk_refund_period'),    
    re_path(r'^api/peak_periods/', api.peak_periods, name='peak_periods'),
    re_path(r'^api/booking_policy/', api.booking_policy, name='booking_policy'),
    re_path(r'^api/get_confirmation/(?P<booking_id>[0-9]+)/$', api.get_confirmation, name='get_confirmation'),
    re_path(r'^api/reports/booking_refunds$', api.BookingRefundsReportView.as_view(), name='booking-refunds-report'),
    re_path(r'^api/reports/bookings$', api.BookingReportView.as_view(), name='bookings-report'),
    re_path(r'^api/reports/booking_settlements$', api.BookingSettlementReportView.as_view(), name='booking-settlements-report'),
    re_path(r'^api/server-date$', api.GetServerDate.as_view(), name='get-server-date'),
    re_path(r'^api/test_server_api/', api.test_server_api, name='test_server_api'),
    re_path(r'^api/', include(router.urls)),
    re_path(r'^sentry-debug/', trigger_error)
]

# URL Patterns
urlpatterns = [
    path(r'admin/', admin.site.urls),
    path('summernote/', include('django_summernote.urls')),
    #url(r'^login/', LoginView.as_view(),name='login'),
    #url(r'^logout/$', LogoutView.as_view(), {'next_page': '/'}, name='logout'),
    #url(r'^logout/$', LogoutView.as_view(), {'next_page': settings.LOGOUT_REDIRECT_URL}, name='logout'),
    #url(r'^admin/', admin.site.urls, name='admin_urls'),
    re_path(r'', include(api_patterns)),
    #url(r'', include(site_queue_urls)),
    #url(r'^account/', views.ProfileView.as_view(), name='account'),
    re_path(r'^$', views.ParkstayRoutingView.as_view(), name='ps_home'),
    re_path(r'^$', views.ParkstayRoutingView.as_view(), name='home'),
    re_path(r'^login-success/$', views.LoginSuccess.as_view(), name='login-success'),
    re_path(r'^testing-server/$', views.TestView.as_view(), name='test_view'),
    re_path(r'^status/$', views.StatusView.as_view(), name='status_view'),
    re_path(r'^testing-server-with-auth/$', views.TestViewAuth.as_view(), name='test_view'),
    re_path(r'^search-availability/information/', views.SearchAvailablity.as_view(), name='search_availability_information'),
    re_path(r'^search-availability/campground/', views.SearchAvailablityByCampground.as_view(), name='search_availability_campground'),
    re_path(r'^page/(?P<page_slug>[-\w]+)/$', views.PagesView.as_view(), name='page_detail'),
    re_path(r'^campsites/(?P<ground_id>[0-9]+)/$', views.CampsiteBookingSelector.as_view(), name='campsite_booking_selector'),
    #url(r'^availability/$', views.CampsiteAvailabilitySelector.as_view(), name='campsite_availaiblity_selector'),
    #url(r'^availability_admin/$', views.AvailabilityAdmin.as_view(), name='availability_admin'),
    #url(r'^ical/campground/(?P<ground_id>[0-9]+)/$', views.CampgroundFeed(), name='campground_calendar'),
    re_path(r'^dashboard/peak-periods/$', views.PeakPeriodGroup.as_view(), name='dash-peak-periods'),
    re_path(r'^dashboard/booking-policy/$', views.BookingPolicy.as_view(), name='dash-booking-policy'),
    re_path(r'^dashboard/campgrounds$', views.DashboardView.as_view(), name='dash-campgrounds'),
    re_path(r'^dashboard/campsite-types$', views.DashboardView.as_view(), name='dash-campsite-types'),
    re_path(r'^dashboard/bookings/edit/', views.DashboardView.as_view(), name='dash-bookings'),
    re_path(r'^dashboard/bookings$', views.DashboardView.as_view(), name='dash-bookings'),
    re_path(r'^dashboard/bulkpricing$', views.DashboardView.as_view(), name='dash-bulkpricing'),
    re_path(r'^dashboard/batch-refund-cancellation/$', views.BatchRefundCancel.as_view(), name='dash-batch-refund-cancel'),
    re_path(r'^dashboard/', views.DashboardView.as_view(), name='dash'),
    re_path(r'^booking-session/abort$', views.SessionAbortView.as_view(), name='public_booking_aborted_session'),
    re_path(r'^booking-session/abort-redirect$', views.SessionAbortRedirectView.as_view(), name='public_booking_aborted_redirect'),
    re_path(r'^booking/abort$', views.abort_booking_view, name='public_abort_booking'),
    re_path(r'^booking/abort_session$', views.SessionAbortView.as_view(), name='public_booking_aborted'),
    re_path(r'^booking/abort_session_redirect$', views.SessionAbortRedirectView.as_view(), name='public_booking_aborted_redirect'),            
    re_path(r'^booking/cancel/(?P<booking_id>[0-9]+)/$', views.CancelBookingView.as_view(), name='cancel_booking'),
    re_path(r'^booking/change/(?P<booking_id>[0-9]+)/$', views.ChangeBookingView.as_view(), name='change_booking'),
    re_path(r'^booking/', views.MakeBookingsView.as_view(), name='public_make_booking'),
    re_path(r'^booking-history/(?P<pk>[0-9]+)/', views.ViewBookingHistory.as_view(), name='view_booking_history'),
    re_path(r'^mybookings/', views.MyBookingsView.as_view(), name='public_my_bookings'),
    re_path(r'^success/', views.BookingSuccessView.as_view(), name='public_booking_success'),
    re_path(r'^map/', views.MapView.as_view(), name='map'),
    re_path(r'^campground-image/(?P<height>[0-9]+)/(?P<width>[0-9]+)/', view_file.getFile, name='campground_image_resize'), 
    re_path(r'^campground-image-cropped-square/(?P<height>[0-9]+)/(?P<width>[0-9]+)/', view_file.getFileCroppedResized, name='campground_image_resize_cropped_square'),
] + ledger_patterns + media_serv_patterns

#if settings.DEBUG:  # Serve media locally in development.
#urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
