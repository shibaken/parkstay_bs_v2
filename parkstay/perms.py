from rest_framework.permissions import BasePermission, SAFE_METHODS
from parkstay.helpers import is_officer


# REST permissions
class OfficerPermission(BasePermission):
    def has_permission(self, request, view):
        return is_officer(request.user)


class OfficerOrReadOnlyPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return is_officer(request.user)


class PaymentCallbackPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method == 'GET':
            return True
        return is_officer(request.user)
