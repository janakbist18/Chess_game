from django.contrib import admin
from django.urls import path, include
from chessapp.views import lobby

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", lobby, name="lobby"),
    path("chess/", include("chessapp.urls")),
]