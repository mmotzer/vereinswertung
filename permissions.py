"""Role templates with explicit per-user overrides, stored in each club database."""
import json

LABELS = {
    'view': 'Ranglisten, Spielerprofile und Turniere ansehen',
    'submit': 'Partien einreichen', 'import': 'Turniere und Partien direkt importieren',
    'approve': 'Einreichungen genehmigen oder ablehnen', 'undo': 'Eigene Importe zurücknehmen',
    'manage_users': 'Zugänge, Rollen und Rechte verwalten', 'manage_members': 'Mitglieder und Registrierungscodes verwalten',
    'settings': 'Vereinseinstellungen ändern', 'export': 'Wertungen exportieren und drucken',
    'backup': 'Datenbanksicherungen herunterladen', 'audit': 'Verwaltungsprotokoll ansehen',
    'billing': 'Vereinsabo verwalten',
}
DEFAULTS = {
    'member': {'view', 'submit', 'export'},
    'director': {'view', 'submit', 'export', 'import', 'approve', 'undo'},
    'admin': set(LABELS),
}

def effective(role, overrides='{}'):
    changes=json.loads(overrides) if isinstance(overrides,str) else overrides
    return {key:changes.get(key,key in DEFAULTS[role]) for key in LABELS}

def validate(value):
    if not isinstance(value,dict) or any(key not in LABELS or type(flag) is not bool for key,flag in value.items()):
        raise ValueError('Ungültige Berechtigungen')
    return value

ENDPOINTS = {
    'rankings':'view', 'player':'view', 'tournaments':'view', 'tournament':'view',
    'users':'manage_users', 'add_user':'manage_users', 'update_user':'manage_users',
    'club_members':'manage_members', 'add_club_members':'manage_members', 'invitation':'manage_members',
    'onboarding':'manage_members',
    'settings':'settings', 'save_settings':'settings', 'audit_log':'audit', 'backup_download':'backup',
    'export_csv':'export', 'print_rankings':'export', 'inspect':'import', 'preview':'import',
    'undo':'undo', 'hide_tournament':'manage_users', 'set_lichess':'import', 'reject':'approve',
    'inspect_submission':'submit', 'submit':'submit',
}
