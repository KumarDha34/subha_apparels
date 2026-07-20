from django.shortcuts import render


def login_view(request):
    return render(request, "frontend/login.html")


def page_view(request, page):
    return render(request, f"frontend/{page}.html")

