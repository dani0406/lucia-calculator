"""LUCIA luminescence calibration from the user's Tecan workbook layout.

Column F is the measured signal (y), calibration CFE µL is x.
No blank correction, background subtraction, or automatic outlier removal.
This module calculates volumes only; it does not control the robot.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from openpyxl import load_workbook

A_DOSES = (1.0, 0.5, 0.25, 0.125)
B_DOSES = (0.01, 0.001, 0.0001)


def fit_volume(doses, signals, target):
    """Ordinary least squares, equivalent to Excel INTERCEPT/SLOPE(y, x)."""
    if len(doses) != len(signals) or len(doses) < 2:
        raise ValueError('Calibration needs at least two matched points.')
    values = list(doses) + list(signals) + [target]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('Calibration inputs must be finite numeric values; missing cells and reader errors are not accepted.')
    mean_x = math.fsum(doses) / len(doses)
    mean_y = math.fsum(signals) / len(signals)
    ss_x = math.fsum((x - mean_x) ** 2 for x in doses)
    if ss_x == 0:
        raise ValueError('Calibration doses must differ.')
    slope = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(doses, signals)) / ss_x
    if slope <= 0:
        raise ValueError('Calibration slope must be positive.')
    intercept = mean_y - slope * mean_x
    volume = (target - intercept) / slope
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError('Calculated CFE volume must be positive and finite.')
    residual = math.fsum((y - (slope * x + intercept)) ** 2 for x, y in zip(doses, signals))
    total = math.fsum((y - mean_y) ** 2 for y in signals)
    return {'slope': slope, 'intercept': intercept, 'r_squared': 1 - residual / total,
            'cfe_equivalent_uL': volume, 'extrapolated': not min(doses) <= volume <= max(doses)}


def calculate_workbook(source, a_sheet='UL8 (A)', b_sheet='Binders (B)', require_more_than_18=False,
                       minimum_samples=None, protein_names=None):
    minimum = minimum_samples if minimum_samples is not None else (19 if require_more_than_18 else 18)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or not 1 <= minimum <= 50:
        raise ValueError('Required sample capacity must be a whole number from 1 to 50.')
    protein_names = protein_names or {}
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    workbook = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    records, errors = [], []
    try:
        for sheet in [a_sheet, b_sheet]:
            if sheet not in workbook.sheetnames:
                raise ValueError(f'Missing worksheet: {sheet}')
        groups = [('A', a_sheet, row, A_DOSES, 100_000_000, 20, 'M', i + 1)
                  for i, row in enumerate([40, 44])]
        groups += [('B', b_sheet, row, B_DOSES, 400_000_000, 40, 'N', i + 1)
                   for i, row in enumerate([40, 43, 46, 49, 52, 55])]
        for group, sheet, start, doses, target, pmol, dose_col, number in groups:
            ws = workbook[sheet]
            end = start + len(doses) - 1
            identity = f'{group}{number}'
            protein_name = str(protein_names.get(identity, '')).strip() or identity
            record = {'protein_id': identity, 'protein_name': protein_name,
                      'group': group, 'sheet': sheet, 'signal_cells': f'F{start}:F{end}',
                      'dose_cells': f'{dose_col}{start}:{dose_col}{end}', 'target_signal': target,
                      'target_pmol': pmol, 'calibration_cfe_uL': list(doses),
                      'signals': [ws[f'F{r}'].value for r in range(start, end + 1)]}
            record_errors = []
            try:
                record.update(fit_volume(doses, record['signals'], target))
                volume = record['cfe_equivalent_uL']
                factor = 10 if group == 'B' and volume < 1 else 1
                record['dilution_factor'] = factor
                record['dispense_uL'] = volume * factor
                record['pbs_uL'] = 200 - record['dispense_uL']
                record['stage'] = 'A before wash' if group == 'A' else 'B after wash'
                record['incubation_minutes'] = 60 if group == 'A' else 5
                if record['dispense_uL'] > 200:
                    record_errors.append('Required protein dispense exceeds 200 µL.')
                if group == 'A':
                    record['available_cfe_uL'] = 540
                    record['max_samples'] = math.floor(540 / volume)
                    record['minimum_samples'] = minimum
                    if record['max_samples'] < minimum:
                        record_errors.append(f"Only {record['max_samples']} samples available; requires at least {minimum}.")
            except ValueError as exc:
                record_errors.append(str(exc))
            record['errors'] = record_errors
            records.append(record)
            errors.extend(f'{identity} ({record["protein_name"]}): {message}' for message in record_errors)
    finally:
        workbook.close()
    return {'source_sha256': hashlib.sha256(raw).hexdigest(), 'signal_column': 'F',
            'signal_type': 'luminescence', 'blank_correction': 'none',
            'a_sample_rule': f'>={minimum}', 'minimum_samples': minimum,
            'final_well_volume_uL': 200, 'proteins': records, 'errors': errors,
            'sequence': ['Add A and PBS to 200 µL', 'Incubate 60 minutes', 'Wash (details pending)',
                         'Add B and PBS to 200 µL', 'Incubate 5 minutes', 'Measure'],
            'pbs_basis': 'Each stage is prepared separately to 200 µL; no retained wash volume is included.',
            'robot_ready': False, 'unresolved': ['CFE source wells and pooling volumes',
            'destination wells', 'B dilution preparation quantity', 'wash procedure and residual volume',
            'deck labware and pipettes']}


def summary_rows(report):
    keys = ['protein_id', 'protein_name', 'target_pmol', 'cfe_equivalent_uL',
            'dilution_factor', 'dispense_uL', 'pbs_uL', 'stage', 'incubation_minutes',
            'max_samples', 'r_squared', 'extrapolated']
    return [dict({key: p.get(key) for key in keys}, error='; '.join(p['errors'])) for p in report['proteins']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--a-sheet', default='UL8 (A)')
    parser.add_argument('--b-sheet', default='Binders (B)')
    parser.add_argument('--require-more-than-18', action='store_true', help='Optional stricter rule; default allows exactly 18.')
    parser.add_argument('--minimum-samples', type=int, help='Required A sample capacity, 1–50 (default 18).')
    args = parser.parse_args()
    report = calculate_workbook(args.workbook, args.a_sheet, args.b_sheet, args.require_more_than_18,
                                minimum_samples=args.minimum_samples)
    destination = Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'lucia_results.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    rows = summary_rows(report)
    with (destination / 'lucia_volumes.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for p in report['proteins']:
        print(p['protein_id'], p['protein_name'], 'CFE µL:', p.get('cfe_equivalent_uL'),
              'dilution:', p.get('dilution_factor'), 'dispense µL:', p.get('dispense_uL'),
              'samples:', p.get('max_samples', 'n/a'))
    for error in report['errors']:
        print('ERROR:', error)
    raise SystemExit(2 if report['errors'] else 0)


if __name__ == '__main__':
    main()
