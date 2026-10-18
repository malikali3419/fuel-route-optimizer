from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='route-map'), name='home'),
    path('', include('routing.urls')),
]
