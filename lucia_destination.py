"""Editable LUCIA destination layouts and transfer previews, without robot control.

Layouts are ``{plate_id: {'name': str, 'wells': {well: assignment}}}``, where
an assignment has ``a_protein_id``, ``b_protein_id``, ``a_control`` and ``label``
strings, plus an optional numeric ``control_volume_uL``. The A layer contains
either a calibrated A protein or the mCherry control; the B layer is separate.
Empty protein IDs are valid drafts, but prevent a complete transfer preview.
Every public editing function returns a deep copy and validates before editing.
"""
from copy import deepcopy
import json
import math

from reader_plates import WELLS


def protein_catalog(report):
    """Return full calibration records keyed by reader group and protein ID.

    Unsuccessful calibrations remain in the catalog, including their errors,
    so an existing draft never silently loses its selected protein.
    """
    catalog = {'A': {}, 'B': {}}
    for protein in report.get('proteins', []):
        group, identity = protein.get('group'), protein.get('protein_id')
        if group not in catalog or not isinstance(identity, str) or not identity.strip():
            raise ValueError('Every protein needs a reader group (A or B) and a protein ID.')
        if identity in catalog[group]:
            raise ValueError(f'Duplicate protein ID in reader group {group}: {identity}.')
        catalog[group][identity] = deepcopy(protein)
    return catalog


def _text(value, description, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f'{description} must be a {"text value" if allow_empty else "nonempty text value"}.')
    return value.strip()


def _validated_layouts(layouts):
    if not isinstance(layouts, dict):
        raise ValueError('Destination layouts must be a collection of named plates.')
    try:
        json.dumps(layouts, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Destination layouts must contain only JSON-compatible values and finite numbers.') from exc
    for plate_id, plate in layouts.items():
        if _text(plate_id, 'Plate ID') != plate_id:
            raise ValueError('Plate IDs cannot have leading or trailing spaces.')
        if not isinstance(plate, dict):
            raise ValueError(f'{plate_id}: the plate layout is not valid.')
        _text(plate.get('name'), 'Plate name')
        if not isinstance(plate.get('wells'), dict):
            raise ValueError(f'{plate_id}: wells must be a collection of assignments.')
        for well, assignment in plate['wells'].items():
            if well not in WELLS:
                raise ValueError(f'{plate_id}: invalid destination well {well}; use A1–H12.')
            if not isinstance(assignment, dict):
                raise ValueError(f'{plate_id} {well}: the assignment is not valid.')
            for field in ('a_protein_id', 'b_protein_id', 'a_control', 'label'):
                _text(assignment.get(field, ''), f'{plate_id} {well} {field}', allow_empty=True)
            control = assignment.get('a_control', '')
            if control not in ('', 'mCherry'):
                raise ValueError(f'{plate_id} {well}: choose mCherry or no A control.')
            if control and assignment.get('a_protein_id', ''):
                raise ValueError(f'{plate_id} {well}: the A layer cannot contain both an A protein and mCherry.')
            volume = assignment.get('control_volume_uL')
            if volume is not None and (not _number(volume, positive=True) or volume > 200):
                raise ValueError(f'{plate_id} {well}: mCherry volume must be greater than 0 and at most 200 µL.')
    return deepcopy(layouts)


def validate_layouts(layouts):
    """Validate a restored layout and return a detached copy.

    Calibration IDs are checked against the current report by the preview;
    this structural check allows older drafts to be restored and corrected.
    """
    return _validated_layouts(layouts)


def _plate(layouts, plate_id):
    if plate_id not in layouts:
        raise ValueError(f'Unknown destination plate: {plate_id}.')
    return layouts[plate_id]


def _selected(wells):
    requested = set(wells)
    if not requested:
        raise ValueError('Select at least one destination well.')
    if any(well not in WELLS for well in requested):
        raise ValueError('Every destination well must be between A1 and H12.')
    return [well for well in WELLS if well in requested]


def create_plate(layouts, plate_id, name):
    """Add a named, empty plate; never overwrite an existing plate ID."""
    result = _validated_layouts(layouts)
    plate_id = _text(plate_id, 'Plate ID')
    name = _text(name, 'Plate name')
    if plate_id in result:
        raise ValueError(f'Destination plate ID already exists: {plate_id}.')
    result[plate_id] = {'name': name, 'wells': {}}
    return result


def rename_plate(layouts, plate_id, name):
    result = _validated_layouts(layouts)
    _plate(result, plate_id)['name'] = _text(name, 'Plate name')
    return result


def remove_plate(layouts, plate_id):
    result = _validated_layouts(layouts)
    _plate(result, plate_id)
    del result[plate_id]
    return result


def assign_destination_wells(layouts, plate_id, wells, *, a_protein_id=None,
                             b_protein_id=None, label=None, catalog=None,
                             a_control=None, control_volume_uL=None):
    """Apply one edit to selected wells atomically.

    ``None`` leaves a field unchanged; ``''`` clears it. A catalog is required
    when assigning a nonempty protein ID. Failed calibration IDs can be saved
    in a draft but will produce blocking errors in the transfer preview.
    Selecting a nonempty A protein clears the A control and its volume;
    selecting mCherry clears the A protein. B edits preserve the A layer.
    """
    result = _validated_layouts(layouts)
    plate = _plate(result, plate_id)
    selected = _selected(wells)
    updates = {}
    for group, value in (('A', a_protein_id), ('B', b_protein_id)):
        if value is None:
            continue
        value = _text(value, f'Protein {group} ID', allow_empty=True)
        if value and (catalog is None or value not in catalog.get(group, {})):
            raise ValueError(f'Unknown protein {group} ID: {value}. Choose a calibrated protein from reader plate {group}.')
        updates[f'{group.lower()}_protein_id'] = value
    if label is not None:
        updates['label'] = _text(label, 'Well label', allow_empty=True)
    if a_control is not None:
        a_control = _text(a_control, 'A control', allow_empty=True)
        if a_control not in ('', 'mCherry'):
            raise ValueError('Choose mCherry or no A control.')
        updates['a_control'] = a_control
    if updates.get('a_protein_id') and updates.get('a_control'):
        raise ValueError('The A layer cannot contain both an A protein and mCherry.')
    if updates.get('a_protein_id'):
        updates.update(a_control='', control_volume_uL=None)
    elif updates.get('a_control'):
        updates['a_protein_id'] = ''
    if control_volume_uL is not None:
        if control_volume_uL == '':
            updates['control_volume_uL'] = None
        elif not _number(control_volume_uL, positive=True) or control_volume_uL > 200:
            raise ValueError('mCherry volume must be greater than 0 and at most 200 µL.')
        else:
            updates['control_volume_uL'] = control_volume_uL
    for well in selected:
        assignment = dict(a_protein_id='', b_protein_id='', label='', a_control='', control_volume_uL=None)
        assignment.update(plate['wells'].get(well, {}))
        assignment.update(updates)
        plate['wells'][well] = assignment
    return result


def clear_destination_wells(layouts, plate_id, wells):
    """Remove all assignments in selected wells, preserving every other well."""
    result = _validated_layouts(layouts)
    plate = _plate(result, plate_id)
    for well in _selected(wells):
        plate['wells'].pop(well, None)
    return result


def _number(value, positive=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def _calculation_errors(protein, group):
    errors = list(protein.get('errors', []))
    raw = protein.get('cfe_equivalent_uL')
    dispense, pbs = protein.get('dispense_uL'), protein.get('pbs_uL')
    factor = protein.get('dilution_factor')
    if not _number(raw, positive=True):
        errors.append('Calculated CFE volume must be positive and finite.')
    if (not _number(dispense, positive=True) or not _number(pbs)
            or (isinstance(dispense, (int, float)) and dispense > 200)):
        errors.append('Calculated protein and PBS volumes must fit within 200 µL.')
    elif not math.isclose(dispense + pbs, 200, rel_tol=0, abs_tol=1e-8):
        errors.append('Calculated protein and PBS volumes must total 200 µL.')
    if _number(raw, positive=True):
        expected_factor = 10 if group == 'B' and raw < 1 else 1
        if isinstance(factor, bool) or factor != expected_factor:
            errors.append('The dilution factor does not match the calculated CFE volume.')
        elif _number(dispense, positive=True) and not math.isclose(dispense, raw * factor, rel_tol=1e-12, abs_tol=1e-12):
            errors.append('The dispense volume does not match the calculated CFE volume and dilution factor.')
    return list(dict.fromkeys(errors))


def build_transfer_preview(report, layouts):
    """Expand each occupied well into separate A and B stage transfers.

    The preview retains full precision and calibration provenance. Only used
    proteins are checked, and partial assignments remain saved as drafts.
    ``ready`` describes a complete calculated layout, not robot readiness:
    source labware, pipettes, wash handling and prepared B dilutions are
    configured and verified separately before protocol generation.
    """
    result = {'layouts': deepcopy(layouts), 'transfers': [], 'errors': [],
              'warnings': [], 'a_usage': [], 'ready': False,
              'source_sha256': report.get('source_sha256', ''),
              'final_well_volume_uL': 200, 'occupied_wells': 0}
    try:
        layouts = _validated_layouts(layouts)
        catalog = protein_catalog(report)
    except ValueError as exc:
        result['errors'].append(str(exc))
        return result
    used_a, used_b, checked = {}, set(), {}
    for plate_id, plate in layouts.items():
        for well in WELLS:
            assignment = plate['wells'].get(well)
            if not assignment:
                continue
            identities = {group: assignment.get(f'{group.lower()}_protein_id', '') for group in ('A', 'B')}
            control = assignment.get('a_control', '')
            # Cleared fields with no label are an empty well, even if imported
            # JSON retained the entry instead of deleting it.
            if not any(identities.values()) and not control and not assignment.get('label', ''):
                continue
            result['occupied_wells'] += 1
            location = f'{plate["name"]} ({plate_id}) {well}'
            missing = [group for group, identity in identities.items() if not identity and not (group == 'A' and control)]
            if missing:
                result['errors'].append(f'{location}: assign protein {" and ".join(missing)} to complete both stages.')
            for group in ('A', 'B'):
                if group == 'A' and control:
                    volume = assignment.get('control_volume_uL')
                    if volume is None:
                        result['errors'].append(f'{location}: mCherry volume not configured; enter the control volume to calculate its transfer.')
                        continue
                    result['transfers'].append({
                        'plate_id': plate_id, 'plate_name': plate['name'], 'well': well,
                        'label': assignment.get('label', ''), 'stage': 'A', 'group': 'A',
                        'protein_id': 'mCherry', 'protein_name': 'mCherry', 'kind': 'control',
                        'cfe_equivalent_uL': None, 'dispense_uL': volume, 'pbs_uL': 200 - volume,
                        'dilution_factor': 1, 'requires_prepared_solution': False,
                        'target_pmol': None, 'incubation_minutes': 60,
                        'provenance': {'volume_source': 'manual control volume',
                                       'source_sha256': report.get('source_sha256', '')}})
                    continue
                identity = identities[group]
                if not identity:
                    continue
                if identity not in catalog[group]:
                    result['errors'].append(f'{location}: unknown protein {group} ID {identity}.')
                    continue
                if group == 'A':
                    used_a[identity] = used_a.get(identity, 0) + 1
                else:
                    used_b.add(identity)
                protein = catalog[group][identity]
                key = (group, identity)
                if key not in checked:
                    checked[key] = _calculation_errors(protein, group)
                    result['errors'].extend(f'Protein {group} {identity}: {error}' for error in checked[key])
                if checked[key]:
                    continue
                columns = report.get('signal_column', '')
                provenance = {field: deepcopy(protein[field]) for field in
                              ('sheet', 'reader_wells', 'signal_cells', 'dose_cells',
                               'calibration_cfe_uL', 'signals', 'slope', 'intercept', 'r_squared')
                              if field in protein}
                provenance.update(source_sha256=report.get('source_sha256', ''),
                                  signal_column=columns.get(group, '') if isinstance(columns, dict) else columns)
                result['transfers'].append({
                    'plate_id': plate_id, 'plate_name': plate['name'], 'well': well,
                    'label': assignment.get('label', ''), 'stage': group, 'group': group,
                    'protein_id': identity, 'protein_name': protein.get('protein_name') or identity,
                    'kind': 'protein',
                    'cfe_equivalent_uL': protein['cfe_equivalent_uL'],
                    'dispense_uL': protein['dispense_uL'], 'pbs_uL': protein['pbs_uL'],
                    'dilution_factor': protein['dilution_factor'],
                    'requires_prepared_solution': group == 'B' and protein['dilution_factor'] == 10,
                    'target_pmol': protein.get('target_pmol'),
                    'incubation_minutes': 60 if group == 'A' else 5,
                    'provenance': provenance})
    for identity, count in used_a.items():
        protein = catalog['A'][identity]
        volume = protein.get('cfe_equivalent_uL')
        available = protein.get('available_cfe_uL', 540)
        usage = {'protein_id': identity, 'protein_name': protein.get('protein_name') or identity,
                 'assigned_wells': count, 'available_cfe_uL': available,
                 'required_cfe_uL': None, 'remaining_cfe_uL': None, 'max_samples': None}
        if not _number(available, positive=True):
            result['errors'].append(f'Protein A {identity}: available CFE volume must be positive and finite.')
        elif _number(volume, positive=True):
            usage.update(required_cfe_uL=count * volume, remaining_cfe_uL=available - count * volume,
                         max_samples=math.floor(available / volume))
            if count > usage['max_samples']:
                result['errors'].append(f'Protein A {identity}: {count} assigned wells exceed the {usage["max_samples"]}-well capacity from {available:g} µL CFE.')
        result['a_usage'].append(usage)
    for identity in sorted(used_b):
        if catalog['B'][identity].get('dilution_factor') == 10:
            result['warnings'].append(f'Protein B {identity}: use a separately prepared 10× diluted solution as the source for the displayed dispense volume.')
    if not result['occupied_wells']:
        result['errors'].append('Assign proteins to at least one destination well.')
    result['ready'] = not result['errors']
    return result
