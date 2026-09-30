"""Reader positions, user assignments and calibration records, independent of the UI."""
import hashlib
import io
import math
import re
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from lucia_calculations import A_DOSES, B_DOSES, calculate_records

WELLS = tuple(f'{row}{column}' for row in 'ABCDEFGH' for column in range(1, 13))


def normalize_well(value):
    match = re.fullmatch(r'([A-H])0?([1-9]|1[0-2])', str(value).strip().upper())
    return f'{match[1]}{int(match[2])}' if match else None


def read_reader_plate(raw, sheet, signal_column='F'):
    """Read a Tecan well-per-row export; never infer identities from row order."""
    column = column_index_from_string(signal_column)
    if not 2 <= column <= 16384:
        raise ValueError('Choose a measurement column after the well names in column A.')
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    readings = {}
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f'Missing worksheet: {sheet}')
        for row_number, row in enumerate(workbook[sheet].iter_rows(max_col=column, values_only=True), 1):
            well = normalize_well(row[0])
            if not well:
                continue
            if well in readings:
                raise ValueError(f'{sheet}: duplicate well {well}. Choose an export with one row per well.')
            value = row[column - 1]
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            readings[well] = {'well': well, 'row': row_number,
                              'signal_cell': f'{signal_column}{row_number}',
                              'signal': value if valid else None,
                              'error': '' if valid else f'Missing or nonnumeric reading in {signal_column}{row_number}.'}
    finally:
        workbook.close()
    if not readings:
        raise ValueError(f'{sheet}: no 96-well addresses found in column A (expected A1–H12).')
    return {'sheet': sheet, 'signal_column': signal_column,
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'readings': readings}


def selected_wells(event, readings):
    """Map chart events by well identity, not trace indices."""
    identities = {point.get('customdata', [None])[0]
                  for point in event.get('selection', {}).get('points', [])
                  if point.get('customdata')}
    return [well for well in WELLS if well in identities and well in readings]


def assign_wells(current, readings, wells, role, protein_id='', protein_name='', doses=None, label=''):
    """Validate the full edit before replacing any assignments."""
    requested = set(wells)
    if any(well not in WELLS or well not in readings for well in requested):
        raise ValueError('Every selected well must be present in the reader export.')
    wells = [well for well in WELLS if well in requested]
    if not wells:
        raise ValueError('Select at least one measured well.')
    if role not in ('Calibration', 'Control', 'Exclude'):
        raise ValueError('Choose calibration, control or exclude.')
    protein_id = protein_id.strip()
    protein_name = protein_name.strip() or protein_id
    if role == 'Calibration':
        if not protein_id:
            raise ValueError('Enter a protein group ID.')
        if any(readings[well]['signal'] is None for well in wells):
            raise ValueError('Calibration wells need numeric readings. Check the selected measurement column.')
        if doses is None or len(doses) != len(wells):
            raise ValueError('Enter one calibration volume per selected well, in the displayed well order.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in doses):
            raise ValueError('Calibration volumes must be finite numbers of zero or more.')
    result = {well: dict(assignment) for well, assignment in current.items()}
    for index, well in enumerate(wells):
        result[well] = {'role': role, 'protein_id': protein_id if role == 'Calibration' else '',
                        'protein_name': protein_name if role == 'Calibration' else '',
                        'cfe_uL': doses[index] if role == 'Calibration' else None,
                        'label': label.strip() if role != 'Calibration' else ''}
    # A group has one display name, even when its wells were assigned in several edits.
    if role == 'Calibration':
        for assignment in result.values():
            if assignment['role'] == role and assignment['protein_id'] == protein_id:
                assignment['protein_name'] = protein_name
    return result


def original_layout(plate, group):
    doses = A_DOSES if group == 'A' else B_DOSES
    starts = (40, 44) if group == 'A' else (40, 43, 46, 49, 52, 55)
    by_row = {reading['row']: well for well, reading in plate['readings'].items()}
    assignments = {}
    for index, start in enumerate(starts, 1):
        rows = range(start, start + len(doses))
        if any(row not in by_row for row in rows):
            raise ValueError('The original layout needs measured wells at all original calibration rows. Assign this plate manually instead.')
        # Preserve original row-to-dose mapping even if the export order is unusual.
        for row, dose in zip(rows, doses):
            assignments = assign_wells(assignments, plate['readings'], [by_row[row]],
                                       'Calibration', f'{group}{index}', doses=[dose])
    return assignments


def calculate_reader_plates(plates, assignments, minimum_samples=18):
    records = []
    for group in ('A', 'B'):
        plate = plates[group]
        layout = assignments[group]
        if any(well not in plate['readings'] for well in layout):
            raise ValueError(f'Reader plate {group} has an assignment without a matching reading.')
        groups = {}
        for well in WELLS:
            item = layout.get(well)
            if not item or item['role'] != 'Calibration':
                continue
            groups.setdefault(item['protein_id'], []).append(well)
        for identity, wells in groups.items():
            records.append({'protein_id': identity, 'protein_name': layout[wells[0]]['protein_name'],
                            'group': group, 'sheet': plate['sheet'], 'reader_wells': wells,
                            'signal_cells': [plate['readings'][well]['signal_cell'] for well in wells],
                            'target_signal': 100_000_000 if group == 'A' else 400_000_000,
                            'target_pmol': 20 if group == 'A' else 40,
                            'calibration_cfe_uL': [layout[well]['cfe_uL'] for well in wells],
                            'signals': [plate['readings'][well]['signal'] for well in wells]})
    report = calculate_records(records, minimum_samples, plates['A']['source_sha256'],
                               {group: plate['signal_column'] for group, plate in plates.items()})
    report['reader_plates'] = {
        group: dict(plate, assignments=assignments[group]) for group, plate in plates.items()}
    report['replicate_handling'] = 'Every assigned calibration well contributes equally to the regression.'
    report['unassigned_wells'] = {
        group: [well for well in WELLS if well in plate['readings'] and well not in assignments[group]]
        for group, plate in plates.items()}
    return report
