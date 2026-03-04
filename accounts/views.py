from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from .forms import RegisterForm

def register_view(request):
    if request.user.is_authenticated:
        return redirect("lobby")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("lobby")
    return render(request, "accounts/register.html", {"form": form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect("lobby")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("lobby")
    return render(request, "accounts/login.html", {"form": form})

def logout_view(request):
    logout(request)
    return redirect("login")