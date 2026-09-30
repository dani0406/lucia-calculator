import io
import json
import unittest
from openpyxl import Workbook
from lucia_calculations import A_DOSES, B_DOSES, calculate_workbook
from reader_plates import (assign_wells, calculate_reader_plates, normalize_well,
                           original_layout, read_reader_plate, selected_wells)


def fixture_workbook():
    workbook = Workbook()
    a = workbook.active
    a.title = 'Raw reader A'
    b = workbook.create_sheet('Raw reader B')
    for ws, groups, doses, target, volume, well_row in [
        (a, 2, A_DOSES, 100_000_000, 20, 'F'),
        (b, 6, B_DOSES, 400_000_000, .5, 'B'),
    ]:
        for index in range(groups * len(doses)):
            ws.cell(40 + index, 1, f'{chr(ord(well_row) + index // 12)}{index % 12 + 1}')
            ws.cell(40 + index, 6, doses[index % len(doses)] * target / volume)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class ReaderPlateTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixture_workbook()
        self.plates = {group: read_reader_plate(self.raw, f'Raw reader {group}') for group in ('A', 'B')}

    def test_original_layout_matches_existing_calculator(self):
        layouts = {group: original_layout(plate, group) for group, plate in self.plates.items()}
        report = calculate_reader_plates(self.plates, layouts)
        legacy = calculate_workbook(self.raw, 'Raw reader A', 'Raw reader B')
        self.assertFalse(report['errors'])
        self.assertEqual(len(report['proteins']), 8)
        for new, old in zip(report['proteins'], legacy['proteins']):
            for field in ('cfe_equivalent_uL', 'dispense_uL', 'pbs_uL', 'dilution_factor'):
                self.assertAlmostEqual(new[field], old[field])

    def test_arbitrary_groups_are_independent_and_controls_do_not_enter_fit(self):
        a = assign_wells({}, self.plates['A']['readings'], ['F1', 'F2', 'F5'],
                         'Calibration', 'shared-id', 'A protein', [1, .5, 1])
        a = assign_wells(a, self.plates['A']['readings'], ['F3'], 'Control', label='mCherry')
        a = assign_wells(a, self.plates['A']['readings'], ['F4'], 'Exclude', label='omit')
        b = assign_wells({}, self.plates['B']['readings'], ['B1', 'B2'],
                         'Calibration', 'shared-id', 'B protein', [.01, .001])
        report = calculate_reader_plates(self.plates, {'A': a, 'B': b})
        self.assertFalse(report['errors'])
        self.assertEqual([p['protein_name'] for p in report['proteins']], ['A protein', 'B protein'])
        self.assertEqual(report['proteins'][0]['reader_wells'], ['F1', 'F2', 'F5'])
        self.assertAlmostEqual(report['proteins'][0]['cfe_equivalent_uL'], 20)
        self.assertAlmostEqual(report['proteins'][1]['dispense_uL'], 5)
        self.assertEqual(report['reader_plates']['A']['assignments']['F3']['label'], 'mCherry')
        self.assertIn('F6', report['unassigned_wells']['A'])
        json.dumps(report, allow_nan=False)

    def test_assignments_validate_atomically_and_use_numeric_well_order(self):
        readings = self.plates['B']['readings']
        previous = assign_wells({}, readings, ['B1'], 'Control', label='keep')
        for wells, doses in [(['B1', 'B2'], [1]), (['B1'], [float('nan')]),
                             (['B1'], [-1]), (['H12'], [1]), (['Z99'], [1])]:
            with self.assertRaises(ValueError):
                assign_wells(previous, readings, wells, 'Calibration', 'p', doses=doses)
        self.assertEqual(previous['B1']['role'], 'Control')
        result = assign_wells({}, readings, ['B10', 'B2'], 'Calibration', 'p', doses=[1, .1])
        self.assertEqual(result['B2']['cfe_uL'], 1)
        self.assertEqual(result['B10']['cfe_uL'], .1)

    def test_parser_uses_well_identity_at_arbitrary_rows_and_rejects_duplicates(self):
        workbook = Workbook()
        ws = workbook.active
        ws['A4'], ws['F4'] = ' h012 ', 321
        ws['A9'], ws['F9'] = 'A2', 'OVER'
        output = io.BytesIO()
        workbook.save(output)
        plate = read_reader_plate(output.getvalue(), ws.title)
        self.assertEqual(plate['readings']['H12']['signal_cell'], 'F4')
        self.assertIsNone(plate['readings']['A2']['signal'])
        with self.assertRaises(ValueError):
            assign_wells({}, plate['readings'], ['A2'], 'Calibration', 'p', doses=[1])
        ws['A10'], ws['F10'] = 'H12', 10
        output = io.BytesIO()
        workbook.save(output)
        with self.assertRaisesRegex(ValueError, 'duplicate well H12'):
            read_reader_plate(output.getvalue(), ws.title)
        self.assertIsNone(normalize_well('A13'))

    def test_partial_groups_report_fit_errors_and_selections_filter_empty_wells(self):
        a = assign_wells({}, self.plates['A']['readings'], ['F1', 'F2'],
                         'Calibration', 'p', doses=[1, 1])
        report = calculate_reader_plates(self.plates, {'A': a, 'B': {}})
        self.assertTrue(report['errors'])
        self.assertNotIn('dispense_uL', report['proteins'][0])
        event = {'selection': {'points': [{'customdata': ['F2']}, {'customdata': ['H12']}, {'customdata': ['F1']}]}}
        self.assertEqual(selected_wells(event, self.plates['A']['readings']), ['F1', 'F2'])


if __name__ == '__main__':
    unittest.main()
