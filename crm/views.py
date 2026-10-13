from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from properties.models import Property

from .models import Client, Visit

staff_required = user_passes_test(lambda u: u.is_staff)


@login_required
@staff_required
def client_list(request):
    if request.method == 'POST':
        name  = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        if name and phone:
            Client.objects.create(
                name=name,
                phone=phone,
                email=request.POST.get('email', '').strip(),
                city=request.POST.get('city', '').strip(),
                property_type=request.POST.get('property_type', ''),
                price_min=request.POST.get('price_min') or None,
                price_max=request.POST.get('price_max') or None,
                bedrooms_min=request.POST.get('bedrooms_min') or None,
                notes=request.POST.get('notes', '').strip(),
                agent=request.user,
            )
            messages.success(request, 'Client ajouté.')
            return redirect('crm:client_list')
        messages.error(request, 'Le nom et le téléphone sont obligatoires.')

    clients = Client.objects.select_related('agent').all()
    villes = (Property.objects.exclude(city='')
              .values_list('city', flat=True).distinct().order_by('city'))
    return render(request, 'crm/client_list.html', {
        'clients': clients,
        'villes': villes,
        'type_choices': Property.TYPE_CHOICES,
    })


@login_required
@staff_required
def client_detail(request, pk):
    client  = get_object_or_404(Client, pk=pk)
    matches = client.matching_properties()
    visits  = client.visits.select_related('target_property').all()
    return render(request, 'crm/client_detail.html', {
        'client':  client,
        'matches': matches,
        'visits':  visits,
    })


@login_required
@staff_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.delete()
        messages.success(request, 'Client supprimé.')
    return redirect('crm:client_list')


@login_required
@staff_required
def visit_create(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        prop = get_object_or_404(Property, pk=request.POST.get('property_id'))
        scheduled_at = request.POST.get('scheduled_at')
        if scheduled_at:
            Visit.objects.create(
                client=client,
                target_property=prop,
                scheduled_at=scheduled_at,
                notes=request.POST.get('notes', '').strip(),
            )
            messages.success(request, 'Visite planifiée.')
    return redirect('crm:client_detail', pk=client.pk)


@login_required
@staff_required
def visit_update_status(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status in dict(Visit.STATUS_CHOICES):
            visit.status = status
            visit.save(update_fields=['status'])
    return redirect('crm:client_detail', pk=visit.client.pk)
