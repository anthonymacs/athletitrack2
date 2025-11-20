# athletes/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.forms import formset_factory
import datetime

from django.http import JsonResponse # Add JsonResponse
import json # Add json import
from django.urls import reverse
# --- Correct, consolidated imports ---
from .models import Athlete, CustomUser, PerformanceStat
from events.models import Event
from coaches.models import Coach
from core.models import Sport, Campus, Team, Statistic
from .forms import (
    AthleteUserForm, AthleteProfileForm, ScorecardForm, UNIVERSAL_STATISTICS,
    TeamSelectForm, BulkAthleteEntryForm, CORE_STATISTICS
)

# --- VIEWS ---

@login_required
def athlete_list(request):
    """
    Displays a list of athletes with role-based visibility and powerful filtering.
    - Admins see all athletes.
    - Coaches see only athletes on their team.
    - Athletes see only their teammates.
    Also handles bulk deletion of selected athletes.
    """
    # --- Step 1: Determine the base queryset based on user role ---
    base_queryset = Athlete.objects.none() # Default to seeing nothing

    if request.user.role == CustomUser.Role.ADMINISTRATOR:
        base_queryset = Athlete.objects.all()
    elif request.user.role == CustomUser.Role.COACH:
        if hasattr(request.user, 'coach') and request.user.coach.team:
            base_queryset = Athlete.objects.filter(team=request.user.coach.team)
    elif request.user.role == CustomUser.Role.ATHLETE:
        if hasattr(request.user, 'athlete') and request.user.athlete.team:
            base_queryset = Athlete.objects.filter(team=request.user.athlete.team)

    # Pre-fetch related data for efficiency
    athlete_list = base_queryset.select_related('user', 'team__sport', 'team__campus', 'coach__user')


    # --- Step 2: Handle Bulk Delete POST requests ---
    if request.method == 'POST':
        user_ids_to_delete = request.POST.getlist('athlete_ids')
        # Security: Ensure the user has permission to delete these athletes
        # by filtering the deletable users against their own visible queryset.
        deletable_users = base_queryset.filter(user_id__in=user_ids_to_delete).values_list('user_id', flat=True)
        
        if deletable_users:
            deleted_count, _ = CustomUser.objects.filter(pk__in=deletable_users).delete()
            messages.success(request, f"Successfully deleted {deleted_count} athlete(s).")
        
        return redirect('athlete-list')


    # --- Step 3: Apply GET filters to the role-based queryset ---
    sport_filter = request.GET.get('sport')
    campus_filter = request.GET.get('campus')
    coach_filter = request.GET.get('coach')
    gender_filter = request.GET.get('gender')

    if sport_filter:
        athlete_list = athlete_list.filter(team__sport_id=sport_filter)
    if campus_filter:
        athlete_list = athlete_list.filter(team__campus_id=campus_filter)
    if coach_filter:
        athlete_list = athlete_list.filter(coach_id=coach_filter)
    if gender_filter:
        athlete_list = athlete_list.filter(user__gender=gender_filter)


    # --- Step 4: Prepare context for the template ---
    # The filter dropdowns should only show options relevant to the visible athletes
    visible_athlete_pks = athlete_list.values_list('pk', flat=True)
    
    context = {
        'athletes': athlete_list.order_by('user__first_name'),
        # Data for populating the filter dropdowns
        'sports': Sport.objects.filter(team__athlete__pk__in=visible_athlete_pks).distinct(),
        'campuses': Campus.objects.filter(team__athlete__pk__in=visible_athlete_pks).distinct(),
        'coaches': Coach.objects.filter(athlete__pk__in=visible_athlete_pks).distinct(),
        'genders': CustomUser.Gender.choices,
    }
    return render(request, 'athletes/athlete_list.html', context)

@login_required
def athlete_detail(request, pk):
    """
    Displays the complete profile for a single athlete, providing all necessary
    data for the stats table/flipper and the interactive charts.
    """
    athlete = get_object_or_404(Athlete.objects.select_related('user', 'team', 'coach__user'), pk=pk)
    
    # --- LOGIC FOR THE INTERACTIVE STATS "FLIPPER" ---
    # Get all events where this athlete has stats, ordered from newest to oldest.
    events_with_stats = Event.objects.filter(
        game_stats__athlete=athlete
    ).distinct().order_by('-start_time')

    # For the initial page load, get the stats for only the most recent event.
    most_recent_event = events_with_stats.first()
    if most_recent_event:
        initial_performance_stats = PerformanceStat.objects.filter(athlete=athlete, event=most_recent_event).select_related('statistic')
    else:
        initial_performance_stats = PerformanceStat.objects.none()

    # Get a JSON-serializable list of all event IDs for the JavaScript flipper.
    event_ids_list = list(events_with_stats.values_list('pk', flat=True))
    # --- END OF FLIPPER LOGIC ---

    # --- LOGIC FOR THE CHARTS ---
    # Get a unique list of all stat names ever recorded for this athlete (for the trend chart).
    all_performance_stats = athlete.performance_stats.all()
    athlete_stat_names = all_performance_stats.values_list('statistic__name', flat=True).distinct()
    
    # Get a list of distinct years for the summary chart filter.
    years_with_stats = all_performance_stats.values_list(
        'event__start_time__year', flat=True
    ).distinct().order_by('-event__start_time__year')
    # --- END OF CHART LOGIC ---

    context = {
        'athlete': athlete,
        'performance_stats': initial_performance_stats, # Pass only the most recent stats to the table initially
        'current_event': most_recent_event,
        'event_ids_json': json.dumps(event_ids_list), # For the flipper JS
        'athlete_stat_names': athlete_stat_names,   # For the trend chart JS
        'events_with_stats': events_with_stats,      # For the summary chart filter dropdown
        'years_with_stats': years_with_stats,      # For the summary chart filter dropdown
    }
    return render(request, 'athletes/athlete_detail.html', context)


@login_required
def get_athlete_event_stats(request):
    """
    API endpoint that returns the performance stats for a specific
    athlete in a specific event, used by the stats "flipper".
    """
    athlete_id = request.GET.get('athlete_id')
    event_id = request.GET.get('event_id')

    if not athlete_id or not event_id:
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    event = get_object_or_404(Event, pk=event_id)
    stats = PerformanceStat.objects.filter(athlete_id=athlete_id, event_id=event_id).select_related('statistic')

    stats_data = [{'name': stat.statistic.name, 'value': stat.value} for stat in stats]
    
    response_data = {
        'event_name': event.name,
        'event_date': event.start_time.strftime('%b %d, %Y'),
        'stats': stats_data
    }
    return JsonResponse(response_data)


class AthleteUpdateView(LoginRequiredMixin, UpdateView):
    model = Athlete
    form_class = AthleteProfileForm
    second_form_class = AthleteUserForm
    template_name = 'athletes/athlete_form.html'
    success_url = reverse_lazy('athlete-list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = f"Edit Athlete: {self.object.user.get_full_name()}"
        if 'form2' not in context:
            context['form2'] = self.second_form_class(instance=self.object.user)
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        form2 = self.second_form_class(request.POST, request.FILES, instance=self.object.user)
        if form.is_valid() and form2.is_valid():
            form.save()
            form2.save()
            messages.success(request, 'Athlete profile updated successfully!')
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form, form2=form2))


class AthleteDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    # --- THIS IS THE CORRECT PATTERN ---
    # We target the CustomUser model for deletion.
    model = CustomUser
    # --- END OF PATTERN ---
    
    template_name = 'athletes/athlete_confirm_delete.html'
    success_url = reverse_lazy('athlete-list')
    context_object_name = 'user_to_delete'

    def test_func(self):
        """
        Security check: Ensure only an Admin can delete, and that the
        user being deleted actually has the Athlete role.
        """
        user_to_delete = self.get_object()
        is_admin = self.request.user.role == CustomUser.Role.ADMINISTRATOR
        is_athlete = user_to_delete.role == CustomUser.Role.ATHLETE
        return is_admin and is_athlete

    def form_valid(self, form):
        messages.success(self.request, f"Athlete '{self.get_object().get_full_name()}' and their user account have been permanently deleted.")
        return super().form_valid(form)


@login_required
def bulk_add_by_team_view(request):
    team_id = request.GET.get('team')
    show_formset = False
    team = None
    filter_form = None
    formset = None

    if team_id:
        try:
            team = Team.objects.get(pk=team_id)
            show_formset = True
        except Team.DoesNotExist:
            messages.error(request, "Invalid Team selected.")
            return redirect('athlete-list')

    AthleteEntryFormSet = formset_factory(BulkAthleteEntryForm, extra=1)

    if request.method == 'POST' and show_formset:
        formset = AthleteEntryFormSet(request.POST, request.FILES)
        if formset.is_valid():
            
            new_athletes_info = []
            emails_in_this_batch = set()

            # --- PASS 1: VALIDATION (No change here, this is correct) ---
            for form in formset:
                if form.has_changed():
                    email = form.cleaned_data.get('email')
                    if not email: continue
                    if CustomUser.objects.filter(email__iexact=email).exists() or email.lower() in emails_in_this_batch:
                        messages.warning(request, f"Skipped athlete with email '{email}' as it already exists or was duplicated.")
                        continue
                    emails_in_this_batch.add(email.lower())
                    new_athletes_info.append(form.cleaned_data)
            
            # --- PASS 2: CREATION ---
            if new_athletes_info:
                try:
                    with transaction.atomic():
                        for data in new_athletes_info:
                            first_name = data.get('first_name')
                            last_name = data.get('last_name')
                            email = data.get('email')

                            base_username = f"{first_name.lower()}.{last_name.lower()}"
                            username = base_username
                            counter = 1
                            while CustomUser.objects.filter(username=username).exists():
                                username = f"{base_username}{counter}"
                                counter += 1
                            
                            # 1. Create the user. The signal will fire IMMEDIATELY after this line.
                            user = CustomUser.objects.create_user(
                                username=username, email=email, password='password123',
                                first_name=first_name, last_name=last_name,
                                gender=team.gender, image=data.get('image'),
                                role=CustomUser.Role.ATHLETE
                            )

                            # --- THIS IS THE FINAL FIX ---
                            # 2. The signal has created a blank Athlete profile. GET it.
                            athlete_profile = Athlete.objects.get(user=user)
                            
                            # 3. UPDATE it with the rest of the data.
                            athlete_profile.team = team
                            athlete_profile.birthday = data.get('birthday')
                            athlete_profile.contact_details = data.get('contact_details', '')
                            athlete_profile.save() # The coach will be assigned automatically by the model's save() method.
                            # --- END OF FIX ---
                    
                    messages.success(request, f"Successfully added {len(new_athletes_info)} new athletes to team '{team}'!")
                except Exception as e:
                    messages.error(request, f"An unhandled error occurred during database creation: {e}.")
            else:
                messages.info(request, "No new valid athletes were added.")

            return redirect('athlete-list')
    else: # GET Request
        if show_formset:
            formset = AthleteEntryFormSet()
            filter_form = None
        else:
            filter_form = TeamSelectForm()
            formset = None

    context = {
        'filter_form': filter_form,
        'formset': formset,
        'show_formset': show_formset,
        'selected_team': team,
    }
    return render(request, 'athletes/athlete_bulk_by_team.html', context)


@login_required
def manage_athlete_stats(request, pk):
    athlete = get_object_or_404(Athlete, pk=pk)
    # Authorization Check
    is_their_coach = hasattr(request.user, 'coach') and (athlete.coach == request.user.coach)
    is_admin = (request.user.role == CustomUser.Role.ADMINISTRATOR)

    if not athlete.team:
        messages.error(request, "Cannot manage stats for an athlete with no team assigned.")
        return redirect('athlete-detail', pk=pk)
    
    athlete_sport = athlete.team.sport
    # Get the list of statistics defined for that sport.
    sport_specific_stats = Statistic.objects.filter(sport=athlete_sport)


    if not (is_their_coach or is_admin):
        messages.error(request, "You are not authorized to manage these statistics.")
        return redirect('athlete-detail', pk=pk)

    if request.method == 'POST':
        form = ScorecardForm(request.POST, sport=athlete_sport)
        if form.is_valid():
            year = form.cleaned_data.get('year')
            for key, label in UNIVERSAL_STATISTICS:
                value = form.cleaned_data.get(key)
                if value:
                    stat_obj, created = Statistic.objects.get_or_create(
                        name=label,
                        # Universal stats don't belong to a specific sport, so we leave it null.
                        sport=None,
                        defaults={'short_name': key}
                    )
                    PerformanceStat.objects.update_or_create(
                        athlete=athlete, statistic=stat_obj, year=year,
                        defaults={'value': value}
                    )


            for stat_definition in sport_specific_stats:
                value = form.cleaned_data.get(stat_definition.short_name)
                if value:
                    PerformanceStat.objects.update_or_create(
                        athlete=athlete,
                        statistic=stat_definition,
                        year=year,
                        defaults={'value': value}
                    )
            messages.success(request, f"Statistics for {year} have been updated successfully.")
            return redirect('athlete-detail', pk=pk)
    else:
        initial_data = {'year': datetime.date.today().year}
        existing_stats = PerformanceStat.objects.filter(athlete=athlete, year=datetime.date.today().year)
        for stat_record in existing_stats:
                initial_data[stat_record.statistic.short_name] = stat_record.value
        
        # Pass the initial data AND the athlete's sport to the form
        form = ScorecardForm(initial=initial_data, sport=athlete_sport)

    context = {
        'form': form,
        'athlete': athlete
    }
    return render(request, 'athletes/manage_stats_form.html', context)
