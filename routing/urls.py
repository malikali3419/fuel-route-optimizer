from django.urls import path

from . import views

# Each endpoint answers with or without a trailing slash, since Django can't
# redirect a POST to the slash URL without dropping its body.
urlpatterns = [
    path('api/route/', views.RoutePlanView.as_view(), name='route-plan'),
    path('api/route', views.RoutePlanView.as_view()),
    path('api/route/map/', views.route_map, name='route-map'),
    path('api/route/map', views.route_map),
]
