# events/forms.py
from django import forms
from .models import Event
from athletes.models import Athlete
from core.models import Statistic, Team
from django.db.models import Q
#from django.utils import timezone


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        # We will handle 'participants' separately
        fields = ['name', 'description', 'start_time', 'end_time', 'location']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            # Use HTML5 date/time input for better UX
            'schedule': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }

       # --- DELETE OR COMMENT OUT THIS ENTIRE METHOD ---
    # def clean_schedule(self):
    #     """
    #     This method is no longer needed as the form field now correctly
    #     provides a timezone-aware datetime.
    #     """
    #     schedule_time = self.cleaned_data.get('schedule')
    #     if schedule_time:
    #         return timezone.make_aware(schedule_time, timezone.get_current_timezone())
    #     return schedule_time



class ParticipantManagementForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=Athlete.objects.none(), # Start with an empty queryset
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="" # Hide the default label
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The queryset will be set dynamically in the view
        # We set the full queryset here as a fallback
        self.fields['participants'].queryset = Athlete.objects.all().select_related('user', 'sport', 'campus')

        
    class Meta:
        model = Event
        fields = ['participants']


class EventScheduleForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['name', 'description', 'start_time', 'end_time', 'location']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }


class GameReportForm(forms.Form):
    """
    A dynamic form for entering a "game report" (stats for an athlete in an event).
    It dynamically builds IntegerFields for both universal and sport-specific stats.
    """
    def __init__(self, *args, **kwargs):
        # The view must pass the 'sport' object to this form
        sport = kwargs.pop('sport', None)
        super().__init__(*args, **kwargs)

        if sport:
            # Get universal stats (where sport is None) AND stats for the specific sport
            all_stats_for_sport = Statistic.objects.filter(Q(sport__isnull=True) | Q(sport=sport))
            
            for stat in all_stats_for_sport:
                # Use the stat's short_name as the field's internal name
                # and the full name as the user-facing label.
                self.fields[stat.short_name] = forms.IntegerField(
                    label=stat.name,
                    required=False,
                    # Use NumberInput for the +/- buttons and better mobile UX.
                    # 'min=0' provides basic client-side validation.
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control form-control-sm text-center',
                        'min': '0',
                        'value': '0' # Start with a default value of 0
                    })
                )


class EventOutcomeForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['our_score', 'opponent_score']
        labels = {
            'our_score': 'Our Team\'s Score',
            'opponent_score': 'Opponent\'s Score',
        }
        widgets = {
            'our_score': forms.NumberInput(attrs={'class': 'form-control'}),
            'opponent_score': forms.NumberInput(attrs={'class': 'form-control'}),
        }